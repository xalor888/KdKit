/*
 * kuaidui-kit / kit/harness/native/decode_token.c
 *
 * Native oracle for the two internal token-decode helpers of libbaseutil.so.
 *
 * Java cannot call an arbitrary address inside a loaded .so, and Frida cannot attach to the
 * hardened app, so the two functions `nativeSetToken` uses are called from a tiny native
 * program of our own — no ptrace, no detector, no app involved:
 *
 *     blob = func_5ea0( func_41e8(<stored token>), "@fG2SuLA", strlen(token) >> 2 )
 *
 * where (see work/native_reversal.md §5.1)
 *   func_41e8 (0x41e8) expands the stored "nibble hex" string into bits and packs them,
 *   func_5ea0 (0x5ea0) applies the keyed transform that yields the final blob.
 *
 * The signA blob must satisfy `blob[0x35..] == cuid` and `blob[0x13..0x33]` is a 32-char md5;
 * the signB blob carries the 10-char sign input `X` at +0xc. Those invariants are how this
 * output is judged; see the round log for the observed values.
 *
 * Build / run (see build.sh in this directory):
 *     ./build.sh
 *     adb push decode_token /data/local/tmp/ && adb push libbaseutil.so /data/local/tmp/
 *     adb shell /data/local/tmp/decode_token /data/local/tmp/libbaseutil.so '<stored token>'
 */
#include <dlfcn.h>
#include <link.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef char *(*expand_fn)(char *);
typedef char *(*xform_fn)(char *, char *, int);

static uintptr_t g_base = 0;

/* **身份校验**（2026-11-03 修，代码审查 P1）。
 *
 * 旧实现只用 `strstr(dlpi_name, "libbaseutil.so")` 认库，然后用**写死的 RVA**
 * `0x41e8` / `0x5ea0` 算函数地址。库一旦换成别的版本：
 *   * 名字还叫 libbaseutil.so ⇒ 认得出；
 *   * 那两个 RVA 指向的**不是同一段代码** ⇒ 照样调得动，只是结果全错。
 * 于是"换版本"表现为"解出来的 blob 莫名其妙地对不上"，而不是一句报错 ——
 * 与 R94 那个 NUL bug 同一族：**现象与失败模式无法区分**。
 *
 * 现在先读 ELF 的 `NT_GNU_BUILD_ID`（链接产物的哈希，改一个字节就变），
 * 与下面这个期望值比对，不符就**拒绝运行**。
 *
 * 当前值来自 2026-11-03 从 emulator-5558 拉下来的 libbaseutil.so
 * （35336 字节，APK 7.9.0 / versionCode 1840）。
 */
static const char *EXPECTED_BUILD_ID = "099ed762d024505acdf218f4c0999572731aa628";

/* 读一个 ELF 文件的 GNU build-id；成功返回 0 并把十六进制写进 out。 */
static int read_build_id(const char *path, char *out, size_t outsz) {
    FILE *f = fopen(path, "rb");
    if (!f) return -1;
    unsigned char ehdr[64];
    if (fread(ehdr, 1, sizeof(ehdr), f) != sizeof(ehdr) || memcmp(ehdr, "\x7f" "ELF", 4) != 0) {
        fclose(f);
        return -1;
    }
    if (ehdr[4] != 2 || ehdr[5] != 1) { fclose(f); return -1; }   /* 只认 64 位小端 */
    uint64_t e_phoff;
    uint16_t e_phentsize, e_phnum;
    memcpy(&e_phoff, ehdr + 0x20, 8);
    memcpy(&e_phentsize, ehdr + 0x36, 2);
    memcpy(&e_phnum, ehdr + 0x38, 2);
    if (e_phnum == 0 || e_phoff == 0) { fclose(f); return -1; }

    int found = -1;
    for (unsigned i = 0; i < e_phnum && found != 0; i++) {
        unsigned char ph[56];
        if (fseek(f, (long) (e_phoff + (uint64_t) i * e_phentsize), SEEK_SET) != 0) break;
        if (fread(ph, 1, sizeof(ph), f) != sizeof(ph)) break;
        uint32_t p_type;
        uint64_t p_offset, p_filesz;
        memcpy(&p_type, ph, 4);
        memcpy(&p_offset, ph + 8, 8);
        memcpy(&p_filesz, ph + 32, 8);
        if (p_type != 4 /* PT_NOTE */ || p_filesz == 0 || p_filesz > (1u << 20)) continue;

        unsigned char *seg = (unsigned char *) malloc(p_filesz);
        if (!seg) break;
        if (fseek(f, (long) p_offset, SEEK_SET) != 0 ||
            fread(seg, 1, p_filesz, f) != p_filesz) { free(seg); continue; }

        size_t j = 0;
        while (j + 12 <= p_filesz) {
            uint32_t n_namesz, n_descsz, n_type;
            memcpy(&n_namesz, seg + j, 4);
            memcpy(&n_descsz, seg + j + 4, 4);
            memcpy(&n_type, seg + j + 8, 4);
            size_t desc_off = j + 12 + ((n_namesz + 3) & ~(size_t) 3);
            if (desc_off + n_descsz > p_filesz) break;
            if (n_type == 3 && n_descsz * 2 + 1 <= outsz) {   /* NT_GNU_BUILD_ID, name "GNU" */
                size_t w = 0;
                for (uint32_t k = 0; k < n_descsz; k++)
                    w += (size_t) snprintf(out + w, outsz - w, "%02x", seg[desc_off + k]);
                found = 0;
                break;
            }
            j = desc_off + ((n_descsz + 3) & ~(size_t) 3);
        }
        free(seg);
    }
    fclose(f);
    return found;
}

static int phdr_cb(struct dl_phdr_info *info, size_t size, void *data) {
    (void) size;
    (void) data;
    if (info->dlpi_name && strstr(info->dlpi_name, "libbaseutil.so")) {
        g_base = (uintptr_t) info->dlpi_addr;
        return 1;
    }
    return 0;
}

static void dump(const char *tag, const char *p, size_t len) {
    printf("%s ptr=%p len=%zu\n  hex: ", tag, (const void *) p, len);
    for (size_t i = 0; i < len && i < 128; i++) printf("%02x", (unsigned char) p[i]);
    printf("\n  asc: ");
    for (size_t i = 0; i < len && i < 128; i++) {
        unsigned char c = (unsigned char) p[i];
        putchar(c >= 32 && c < 127 ? c : '.');
    }
    printf("\n");
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);   /* 段错误时不要丢掉已打印的行 */
    if (argc < 3) {
        fprintf(stderr, "usage: %s <libbaseutil.so> <stored-token> [key]\n"
                        "       key defaults to \"@fG2SuLA\" (the signA path); for signB the key is\n"
                        "       <signA blob[7:12]> + \"#G4\" (see nativeSetToken 0x32e0-0x332c)\n", argv[0]);
        return 2;
    }
    void *h = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!h) {
        fprintf(stderr, "dlopen failed: %s\n", dlerror());
        return 1;
    }
    dl_iterate_phdr(phdr_cb, NULL);
    if (!g_base) {
        fprintf(stderr, "could not resolve load base\n");
        return 1;
    }
    printf("base = %#lx\n", (unsigned long) g_base);

    /* 先验身份，再算地址。**顺序很重要**：反过来就等于没验。 */
    char build_id[256];
    if (read_build_id(argv[1], build_id, sizeof(build_id)) != 0) {
        fprintf(stderr, "refusing: cannot read a GNU build-id from %s\n", argv[1]);
        return 1;
    }
    printf("build-id = %s\n", build_id);
    if (strcmp(build_id, EXPECTED_BUILD_ID) != 0) {
        fprintf(stderr,
                "refusing: %s has build-id %s but this oracle was built for %s\n"
                "  => the hardcoded RVAs (0x41e8 / 0x5ea0) do NOT apply to this library.\n"
                "  => re-analyse the new libbaseutil.so, update the RVAs and the expected id.\n",
                argv[1], build_id, EXPECTED_BUILD_ID);
        return 1;
    }

    expand_fn expand = (expand_fn) (g_base + 0x41e8);
    xform_fn xform = (xform_fn) (g_base + 0x5ea0);

    const char *token = argv[2];
    const char *key = argc > 3 ? argv[3] : "@fG2SuLA";
    size_t n = strlen(token);
    int packed = (int) (n >> 2);
    printf("token len=%zu  packed=%d\n", n, packed);

    char *bits = expand((char *) token);
    if (!bits) {
        fprintf(stderr, "expand() returned NULL\n");
        return 1;
    }
    dump("expanded", bits, (size_t) packed);

    printf("key = \"%s\" (%zu)\n", key, strlen(key));
    char *blob = xform(bits, (char *) key, packed);
    if (!blob) {
        fprintf(stderr, "xform() returned NULL\n");
        return 1;
    }
    dump("blob", blob, (size_t) packed);
    return 0;
}
