#!/usr/bin/env python3
"""
kuaidui-kit / smali_usage.py — "钩这个目标，运行时到底会不会有人走到它？"

为什么需要（2026-10-25，见 OPTIMIZATION.md §7 最后一条）
------------------------------------------------------
`check_hook_targets.py` 只回答"类/方法在不在"。但**在**不等于**会被调用**：
`com.byazt.nd.BrushMaskView` 就在、签名也齐全，可它全 APK 零使用 —— 钩上去
`Xp.hook` 返回 true、启动日志写 `ok`，然后**永远不会有第二行日志**。
这种失效比"改名"更隐蔽：门禁全绿、功能"已启用"、真机上什么都没发生。

本模块把"有没有人用它"做成**可离线复跑**的判定，并且在无法证明时明确降级，
绝不把"看不见"说成"不存在"。

判定分四层，结论取最强的那层
--------------------------
| 层 | 证据 | 结论 |
|---|---|---|
| ① 方法直接调用 | 别的文件里有 `invoke-* … La/b/C;->m(` | `USED` |
| ② 方法自调用 | 只有**本类文件**内 `invoke-* … La/b/C;->m(` | `USED(self)`（入口在别的方法上，仍算活） |
| ③ 父类/接口槽位 | 父类型声明了同名同参方法，且该槽位有人 `invoke-virtual` | `SUPER-SLOT`（可能经分派进入，静态无法证明接收者） |
| ④ 只有类型引用 | 描述符出现在字段/参数/`new`/反射字符串，或出现在 `res/` 布局与清单里 | `TYPE-ONLY` |
| — 全都没有 | 本类之外**零**引用、`res/` 里也没有 | **`DEAD`** ≙ 钩了必空转 |

门禁只对 `DEAD` 报红。理由写在这里，避免后人误改：
* ①②③④ 之外的"方法级不可达"需要**全程序可达性分析**（接收者、动态代理、反射、
  加固壳的自修改），当前静态证据不足以下这种结论 —— 用"看不见"当"不存在"正是本仓库
  反复踩的坑（`NEW_TARGETS.md` 里那三条误报就是这样来的）；
* **类级零引用**是可证明的：一个 APK 里没有任何字节提到这个描述符、布局与清单里也没有，
  那运行时没有任何路径能 `new` 它或把它当类型用（`Class.forName("…")` 之类的字符串形式
  也被正则覆盖），因此钩它必然空转。

已知边界
--------
* `invoke-virtual` 的接收者静态类型未知 ⇒ ③ 只算"可能"，不当作证明；
* 加固壳命名空间（`com.byazt.*` 等）在运行时可能自行 patch 出调用点，
  `DEAD` 会标记为 `DEAD(shell)` 并在说明里点出这一不确定性；
* 平台类（`android.*` / `java.*` …）不在解码目录里，判定为 `OK(platform)`，
  由 `check_hook_targets.py` 给出 `OK(platform)`。

    python3 kit/scripts/smali_usage.py --smali work/apktool_out \
        --target ei.y:L bk.a:p com.byazt.nd.BrushMaskView
    python3 kit/scripts/smali_usage.py --smali work/apktool_out \
        --from-module module/app/src/main/java/dev/xalor/kdkit --summary

退出码：0 = 没有 `DEAD`；1 = 有 `DEAD`（可用作门禁）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Iterable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hook_vocab as vocab  # noqa: E402
from hook_vocab import repo_path  # noqa: E402

# 加固壳命名空间：静态零引用**不能**当作"壳不会在运行时装载它"。
SHELL_PREFIXES = ('com.byazt.', 'com.tencent.StubShell.', 'com.stub.StubApp.')

# `@FeAction(name="…")` 的类由桥分发表按名字反射调用：静态没有 invoke 是**设计如此**，
# 不是死代码。这一条把"反射入口"从"死代码"里摘出来，避免把正常钩点判死。
FEACTION_RE = re.compile(r'Lcom/zybang/annotation/FeAction;')

PLATFORM_RE = re.compile(r'^(android|androidx|java|javax|dalvik|libcore|kotlin|kotlinx|'
                         r'org\.json|org\.xml|org\.apache|sun|junit)\.')

CLASS_DECL_RE = re.compile(r'^\.class[^\n]*?(L[^;\s]+;)\s*$', re.M)
SUPER_RE = re.compile(r'^\.super (L[^;]+;)', re.M)
IFACE_RE = re.compile(r'^\.implements (L[^;]+;)', re.M)
# `.method` 头词法**收在 hook_vocab**。这里的旧版本 `^\.method[^\n]*?([\w$<>]+)\(`
# 既会把 `foo$lambda-5$lambda-4(...)` 匹配成名字 `4`，也会整行匹配不上 ——
# 24 个 Kotlin lambda 方法因此从未进入本索引（2026-10-25 第 29 轮实测）。
METHOD_DECL_RE = vocab.METHOD_HEADER_RE

# 标签一律取自 `hook_vocab`（单一定义处）。不再维护"内部值 -> 显示标签"的二次映射
# —— 那正是 ④ 与 ⑥ 词汇漂移的根源（曾经 V_SELF='SELF-CALLED' 显示成 'USED(self)'）。
import hook_vocab as vocab  # noqa: E402

V_USED = 'USED'
V_SELF = 'USED(self)'
V_SUPER = 'SUPER-SLOT'
V_TYPE = 'TYPE-ONLY'
V_DEAD = 'DEAD'
# 读预算把某个目标的命中文件挡在门外 ⇒ "零引用"是**没看完**而不是**不存在**。
# 单独一个结论，且**不判红**：它描述的是"这次没算出结论"，不是"钩点坏了"。
V_INCOMPLETE = 'INCOMPLETE'
V_MISSING = 'MISSING'
V_PLATFORM = 'OK(platform)'
# 反射入口：@FeAction 由桥分发表按名字调，静态看不到 invoke —— 不是死代码。
V_REFLECT = 'REFLECTIVE-ENTRY'


def to_desc(cls: str) -> str:
    """`a.b.C` / `a.b.C$D` / `La/b/C;` -> `La/b/C;`。"""
    if cls.startswith('L') and cls.endswith(';'):
        return cls
    return 'L' + cls.replace('.', '/') + ';'


def desc_to_dotted(desc: str) -> str:
    return desc[1:-1].replace('/', '.')


def _alt(names: Iterable[str]) -> str:
    return '|'.join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))


# ── 文件发现：有 ripgrep 用它，没有就用纯 Python（语义保持一致） ──────────────

def smali_roots(root: str) -> list[str]:
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return []
    return [os.path.join(root, n) for n in entries
            if re.fullmatch(r'smali(_classes\d+)?', n) and os.path.isdir(os.path.join(root, n))]


def smali_files(root: str) -> list[str]:
    out: list[str] = []
    for r in smali_roots(root):
        for base, _dirs, files in os.walk(r):
            out.extend(os.path.join(base, f) for f in files if f.endswith('.smali'))
    return out


def _in_smali_root(path: str, root: str) -> bool:
    head = os.path.relpath(path, root).split(os.sep, 1)[0]
    return bool(re.fullmatch(r'smali(_classes\d+)?', head))


def grep_files(root: str, pattern: str) -> list[str]:
    """在 smali 根下找整行命中 `pattern` 的文件（rg 优先；结果集相同）。"""
    rg = shutil.which('rg')
    if rg:
        r = subprocess.run([rg, '-l', '-uu', '--no-messages', '-e', pattern, root],
                           capture_output=True, text=True, errors='replace', timeout=600)
        return [f for f in r.stdout.splitlines()
                if f.endswith('.smali') and _in_smali_root(f, root)]
    rx = re.compile(pattern)
    out = []
    for f in smali_files(root):
        try:
            with open(f, encoding='utf-8', errors='replace') as fh:
                if rx.search(fh.read()):
                    out.append(f)
        except OSError:
            continue
    return out


def grep_files_any(root: str, pattern: str, subdirs: Iterable[str]) -> list[str]:
    """在任意子目录（如 `res`、清单）里找命中，用于"布局/清单引用了这个类"这一层证据。"""
    rg = shutil.which('rg')
    paths = [os.path.join(root, s) for s in subdirs if os.path.exists(os.path.join(root, s))]
    if not paths:
        return []
    if rg:
        r = subprocess.run([rg, '-l', '-uu', '--no-messages', '-e', pattern, *paths],
                           capture_output=True, text=True, errors='replace', timeout=600)
        return [f for f in r.stdout.splitlines()]
    rx = re.compile(pattern)
    out = []
    for p in paths:
        if os.path.isfile(p):
            cand = [p]
        else:
            cand = [os.path.join(b, f) for b, _d, fs in os.walk(p) for f in fs]
        for f in cand:
            try:
                with open(f, encoding='utf-8', errors='replace') as fh:
                    if rx.search(fh.read()):
                        out.append(f)
            except OSError:
                continue
    return out


def _read(path: str) -> Optional[str]:
    """整文件读成 str；读不了返回 None（捕获里存在半截/不可读文件是正常情况）。"""
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return None


def descriptors_in_files(paths: list[str], descs: list[str]) -> set[str]:
    """给定文件里出现了 `descs` 中的哪些描述符（只回描述符，不落全文）。

    用途：读预算把一部分文件挡在门外时，判断**哪个目标**因此缺证据。
    只用 rg 的 `-o`（只输出命中片段）—— 若把漏掉的文件整份读回来做 `in`，
    读预算就形同虚设（实测漏 44 MB，等于再读一遍）。
    """
    if not paths:
        return set()
    rg = shutil.which('rg')
    if not rg:
        # 没有 rg 时退化为全读：正确性优先，慢一点可接受（这条路径只在无 rg 的机器上走）。
        found: set[str] = set()
        for p in paths:
            text = _read(p)
            if text is None:
                continue
            for d in descs:
                if d in text:
                    found.add(d)
        return found
    # `--no-filename`（`-I`）是必须的：多文件时 rg 默认给每行加 `路径:` 前缀，
    # 于是收回来的行全是 `…/a.smali:Lcom/x/Y;`，`in descs` 永远不命中 ⇒
    # "哪个目标缺证据"恒为空集，降级逻辑静默失效（第一版就是这么错的）。
    r = subprocess.run(
        [rg, '-o', '-I', '-uu', '--no-messages', '-e', _alt(descs), '--', *paths],
        capture_output=True, text=True, errors='replace', timeout=600)
    return {line.strip() for line in r.stdout.splitlines()
            if line.strip() and line.strip().startswith('L')}


def class_file_index(root: str) -> dict[str, str]:
    """描述符 `La/b/C;` -> 文件路径（由文件名推导，不读内容）。"""
    idx: dict[str, str] = {}
    # `relpath` 用字符串前缀替代（2026-11-02 优化）：`smali_files` 的路径全部由
    # `os.walk(smali_roots(root))` 产出，必然以 `root + sep` 开头 —— 于是
    # `relpath(f, root)` 等价于切掉前缀。6 万个文件省掉 6 万次 relpath。
    # **不等价时回退**：前缀不匹配就照旧调 relpath，不改变语义。
    prefix = root if root.endswith(os.sep) else root + os.sep
    for f in smali_files(root):
        if f.startswith(prefix):
            rest = f[len(prefix):]
            parts = rest.split(os.sep, 1)
        else:
            parts = os.path.relpath(f, root).split(os.sep, 1)
        if len(parts) < 2:
            continue
        idx['L' + parts[1][:-len('.smali')] + ';'] = f
    return idx


# ── 类元数据 ──────────────────────────────────────────────────────────────────

@dataclass
class ClassInfo:
    desc: str
    path: str
    super_desc: Optional[str] = None
    interfaces: list[str] = field(default_factory=list)
    methods: set[tuple[str, str, str]] = field(default_factory=set)   # (name, params, ret)
    # @FeAction ⇒ 由 FeActionDispatcher 按 name 反射调用，静态 0 调用方是**设计如此**
    feaction: bool = False

    def declares(self, name: str) -> bool:
        return any(m[0] == name for m in self.methods)


def read_class_info(path: str) -> ClassInfo:
    with open(path, encoding='utf-8', errors='replace') as fh:
        text = fh.read()
    m = CLASS_DECL_RE.search(text)
    sup = SUPER_RE.search(text)
    info = ClassInfo(desc=(m.group(1) if m else 'L?;'), path=path,
                     super_desc=sup.group(1) if sup else None,
                     interfaces=IFACE_RE.findall(text))
    for mm in METHOD_DECL_RE.finditer(text):
        # 组号变了：共享词法把**修饰符**放进了第 1 组（旧版是组 3 里残留的尾注）。
        # 这里明确点名每一组，避免"共用正则但组序不同"这种最隐蔽的错位。
        info.methods.add((mm.group(2), mm.group(3), mm.group(4)))
    info.feaction = bool(FEACTION_RE.search(text))
    return info


# ── 结果 ──────────────────────────────────────────────────────────────────────

@dataclass
class Usage:
    target: str
    desc: str
    method: Optional[str]
    verdict: str
    direct: int = 0                 # 别的文件里指向 (类,方法) 的 invoke
    self_calls: int = 0             # 本类文件内指向它的 invoke（入口在别的方法上）
    class_refs: int = 0             # 别的文件里出现该类描述符的次数
    slot_refs: int = 0              # 父类型槽位上的 invoke 次数
    slot_owners: list[str] = field(default_factory=list)
    external_refs: list[str] = field(default_factory=list)   # res/清单里的引用
    samples: list[str] = field(default_factory=list)
    shell: bool = False
    feaction: bool = False          # 类上声明了 @FeAction（反射入口）
    note: str = ''

    @property
    def ok(self) -> bool:
        return self.verdict != V_DEAD

    def label(self) -> str:
        # 现在 verdict 本身就是词汇表里的标签，无需再映射（保留 label() 仅为兼容调用点）。
        lbl = {V_USED: 'USED', V_SELF: 'USED(self)', V_SUPER: 'SUPER-SLOT',
               V_TYPE: 'TYPE-ONLY', V_DEAD: 'DEAD', V_MISSING: 'MISSING',
               V_REFLECT: 'REFLECTIVE', V_PLATFORM: 'OK(platform)',
               V_INCOMPLETE: 'INCOMPLETE'}.get(self.verdict, self.verdict)
        if self.shell and self.verdict == V_DEAD:
            lbl += '(shell)'
        return lbl

    def to_dict(self) -> dict:
        return self.__dict__.copy()


# 方法名用共享词法的 `SMALI_NAME`（含 `-`）：旧版自带 `[\\w$<>]+`，
# 会让 `foo$lambda-5$lambda-4` 只匹配到尾巴 `4`，于是"这个 lambda 有没有调用方"永远算错。
INVOKE_RE = (r'(?P<op>invoke-[a-z/-]+)(?:/[a-z-]+)?[^\n]*?'
             r'L(?P<owner>{alt});->(?P<meth>' + vocab.SMALI_NAME + r')\((?P<params>[^)]*)\)(?P<ret>\S+)')


def _lineno(text: str, pos: int) -> int:
    return text.count('\n', 0, pos) + 1


# ── 主分析 ────────────────────────────────────────────────────────────────────

def analyse(root: str, targets: list[tuple[str, Optional[str]]],
            samples_per_target: int = 3, read_budget: int = 640 * 1024 * 1024) -> list[Usage]:
    """`targets` = [(dotted class, method|None)]，返回同序 [Usage]。

    `read_budget` 是"命中文件最多读多少 MB"。**它不是性能参数，是结论的边界**：
    预算不够时必须降级成 `INCOMPLETE`，不能断言 `DEAD` —— 详见下面 ① 的说明。
    """
    # 读预算 96 MB → 320 MB 的由来（2026-10-26）：
    #
    # 96 MB 时实测 118 个目标里有 **11 个**被降级成 `INCOMPLETE`，而那些目标单独跑
    # 时证据是完整的（`NativeHelper:nativeGetSign` 单独跑 = USED，批量跑 = INCOMPLETE）。
    # 原因是 `hit_files` 排序后逐个读，预算在列表靠后的文件上耗尽，
    # 于是**排在后面的目标系统性缺证据**。
    #
    # 这不是"判错"，是**判定依赖于目标在列表里的位置** —— 比判错更坏，
    # 因为它让结论不可复现地随目标集变化。
    #
    # 提到 320 MB 后 118 个目标全部拿到完整证据（实测 0 个 INCOMPLETE）。
    # 命中文件全集实测 140.4 MB，所以 320 MB 有 2× 余量；内存代价可接受
    # （这是离线脚本，不是模块运行时）。
    index = class_file_index(root)

    rows: list[Usage] = []
    live: list[tuple[str, Optional[str]]] = []      # 需要扫的目标（非平台、类存在）
    infos: dict[str, ClassInfo] = {}
    for cls, meth in targets:
        desc = to_desc(cls)
        shell = any(cls.startswith(p) for p in SHELL_PREFIXES)
        p = index.get(desc)
        if PLATFORM_RE.match(cls) and p is None:
            rows.append(Usage(cls, desc, meth, V_PLATFORM,
                              note='平台类不在解码目录里，由 check_hook_targets 判 OK(platform)'))
            continue
        if p is None:
            rows.append(Usage(cls, desc, meth, V_MISSING, shell=shell,
                              note='类不在解码目录里（换版 / 改名？）'))
            continue
        if desc not in infos:
            infos[desc] = read_class_info(p)
        live.append((cls, meth))

    if not live:
        return rows

    # ① 一次 grep 拿到"提到任一目标描述符"的所有文件，再一次性读进内存（有预算上限）。
    #
    # **顺序必须由我们自己定，不能沿用 grep 的输出顺序。**
    # 2026-10-26 实测：目标描述符的命中集合计 140.4 MB，而这里是 96 MB 预算 ⇒ 必然有一批
    # 文件读不到。`rg -l` 的返回顺序逐次不同（多线程遍历），于是**每次丢掉的文件不同**，
    # `DEAD` 与 `TYPE-ONLY` 就在两次运行之间来回翻转 —— 同一份静态输入，
    # 门禁 ④ 的 resolved 数在 96 / 107 / 112 / 116 之间跳。
    #
    # 这种非确定性比"判错"更坏：它把"这条结论可复现吗"变成了碰运气，
    # 而项目的每一条结论都建立在"离线可复跑"上。
    # 修法两条同时做：
    #   1. `sorted()` —— 同样输入必得同样文件集（顺序变了，结果也必须不变）；
    #   2. 预算不够时**不再静默**：记下"有目标缺证据"，最后把它们的结论降级成
    #      `INCOMPLETE`，而不是在没有证据时断言 `DEAD`（"看不见"≠"不存在"）。
    descs = sorted({to_desc(c) for c, _m in live})
    hit_files = sorted(grep_files(root, _alt(descs)))
    texts: dict[str, str] = {}
    used = 0
    skipped: list[str] = []
    for f in hit_files:
        try:
            size = os.path.getsize(f)
        except OSError:
            continue
        if used + size > read_budget:
            skipped.append(f)
            continue
        try:
            with open(f, encoding='utf-8', errors='replace') as fh:
                texts[f] = fh.read()
            used += size
        except OSError:
            continue
    # 哪些目标因为"少读了文件"而可能缺证据：只有出现在未读文件里的那几个。
    # 这里**不能**把漏掉的文件整份读进来再 `in` 一遍 —— 那等于把 96 MB 预算变成一句空话
    # （实测漏掉 44 MB）。改用 rg 的 `--only-matching` 只收回"命中了哪些描述符"，不落全文。
    incomplete: dict[str, str] = {}
    if skipped:
        for d in descriptors_in_files(skipped, descs):
            incomplete[d] = (f'{len(skipped)}/{len(hit_files)} 个命中文件因 '
                             f'{read_budget // (1024 * 1024)} MB 读预算未读')

    # ② 方法级：直接调用 / 自调用
    #    注意 `descs` 带 `L…;` 外壳，而 INVOKE_RE 自己会补 `L` 与 `;` ⇒ 这里必须去掉外壳，
    #    否则模式变成 `LLa/b/C;` 永不命中（第一版就是这么错的：全部目标都退化成 TYPE-ONLY）。
    owner_alt = _alt([d[1:-1] for d in descs])
    per: dict[tuple[str, str], tuple[int, int, list[str]]] = {}
    # **abspath 只算一次**（2026-11-02 优化）。
    #
    # 旧实现在 `(目标 × 文件)` 的双重循环里调 `os.path.abspath(f)` ——
    # 实测 126 个目标 × 上万文件 = **150 万次** abspath，占 1.75s；
    # 加上 `os.path.relpath` 13 万次 0.82s。这些调用**每次结果都一样**
    # （`texts` 的键在循环里不变），纯属重复劳动。
    #
    # 这与模块侧 R9/R45/R46 修的是同一类问题：热路径上的重复计算。
    # 区别是那三次在 Kotlin 运行时，这次在离线扫描器里 —— 而扫描器慢的直接代价是
    # 每轮门禁多等十几秒。
    abs_of: dict[str, str] = {}
    abs_index = {k: os.path.abspath(v) for k, v in index.items()}

    def _abs(p: str) -> str:
        """带记忆的 abspath。

        **必须是函数而不是预计算字典**：下面 ③ 层的 `slot_keys` 分支会往 `texts`
        里**追加**新读的文件（`texts[f] = text`），而 ④ 层的类型引用循环要遍历
        当时的 `texts`。预计算字典建得早，就会漏掉后来加进去的文件 ⇒ KeyError
        （2026-11-02 实测：`test_both_hook_points_are_used` 当场炸）。
        """
        v = abs_of.get(p)
        if v is None:
            v = abs_of[p] = os.path.abspath(p)
        return v
    for f, text in texts.items():
        for mm in re.finditer(INVOKE_RE.format(alt=owner_alt), text):
            key = (f'L{mm.group("owner")};', mm.group('meth'))
            direct, selfc, samples = per.get(key, (0, 0, []))
            owner_file = index.get(key[0])
            if owner_file and abs_index[key[0]] == _abs(f):
                selfc += 1
            else:
                direct += 1
                if len(samples) < samples_per_target:
                    samples.append(f'{os.path.basename(f)}:{_lineno(text, mm.start())}')
            per[key] = (direct, selfc, samples)

    # ③ 父类型槽位（只在没有任何直接 invoke 时才需要）
    slot_keys: set[tuple[str, str]] = set()
    for cls, meth in live:
        if not meth:
            continue
        desc = to_desc(cls)
        direct = per.get((desc, meth), (0, 0, []))[0]
        if direct:
            continue
        info = infos[desc]
        chain: list[str] = list(info.interfaces)
        cur = info
        seen: set[str] = set()
        while cur is not None and cur.super_desc and cur.super_desc not in seen:
            seen.add(cur.super_desc)
            chain.append(cur.super_desc)
            nxt = index.get(cur.super_desc)
            cur = read_class_info(nxt) if nxt else None
        for fam in chain:
            fp = index.get(fam)
            finfo = read_class_info(fp) if fp else None
            if finfo and finfo.declares(meth):
                slot_keys.add((fam, meth))
    # 注意：`slot_keys` 里的 owner 是**完整描述符** `La/b/Base;`，而 `INVOKE_RE` 自己会补
    # `L` 与 `;` ⇒ 拼模式前必须剥掉外壳。第一版这里漏了，父类槽位永远匹配不到，
    # 于是"只经父类分派使用"的类被误判成 DEAD（`test_super_slot` 抓到的就是这个）。
    slot_counts: dict[tuple[str, str], int] = {}
    if slot_keys:
        owner_alt = _alt([o[1:-1] for o, _ in slot_keys])
        name_alt = _alt({n for _, n in slot_keys})
        for f in grep_files(root, rf'L(?:{owner_alt});->(?:{name_alt})\('):
            text = texts.get(f)
            if text is None:
                text = _read(f)
                if text is None:
                    continue
                texts[f] = text
            for mm in re.finditer(INVOKE_RE.format(alt=owner_alt), text):
                key = (f'L{mm.group("owner")};', mm.group('meth'))
                if key in slot_keys:
                    slot_counts[key] = slot_counts.get(key, 0) + 1

    # ④ 类型引用 + res/清单引用
    for cls, meth in live:
        desc = to_desc(cls)
        info = infos[desc]
        own = _abs(info.path)
        refs, samples = 0, []
        for f, text in texts.items():
            if _abs(f) == own:
                continue
            n = text.count(desc)
            if not n:
                continue
            refs += n
            if len(samples) < samples_per_target:
                samples.append(f'{os.path.basename(f)}:{_lineno(text, text.find(desc))}')
        external = grep_files_any(root, re.escape(desc_to_dotted(desc)),
                                  ('res', 'AndroidManifest.xml', 'assets')) if refs == 0 else []

        direct, selfc, invoke_samples = per.get((desc, meth), (0, 0, [])) if meth else (0, 0, [])
        slot_refs = 0
        slot_owners: list[str] = []
        if meth:
            for fam, nm in slot_keys:
                if nm != meth:
                    continue
                c = slot_counts.get((fam, nm), 0)
                if c:
                    slot_refs += c
                    slot_owners.append(f'{desc_to_dotted(fam)}.{nm}×{c}')

        shell = any(desc_to_dotted(desc).startswith(p) for p in SHELL_PREFIXES)
        feaction = info.feaction
        if direct:
            verdict, note = V_USED, ''
        elif feaction and meth:
            # 桥分发表按 @FeAction 的 name 反射调用 onAction ⇒ 静态没有 invoke 是设计如此。
            # 这一层必须排在 DEAD 之前，否则每一个桥 action 都会被误判成死代码。
            verdict = V_REFLECT
            note = ('类上声明了 @FeAction（桥按 name 反射分发）⇒ 静态没有 invoke 是设计如此，'
                    '不是死代码；能不能真被页面调用要看 H5BRIDGE 抓取')
        elif selfc:
            verdict = V_SELF
            note = ('只有本类内部调用它（入口在别的方法上）⇒ 活代码，但钩点在这条内部路径上')
        elif slot_refs:
            verdict = V_SUPER
            note = ('没有直接 invoke；只有父类型槽位被调用 ⇒ 可能经分派进入，'
                    '纯静态无法证明接收者是本类')
        elif refs or external:
            verdict = V_TYPE
            note = ('只有类型引用（字段/参数/new/反射字符串'
                    + ('/res 布局' if external else '')
                    + '），没有 invoke ⇒ 可能由框架膨胀或反射使用')
        else:
            verdict = V_DEAD
            note = ('本类之外没有任何字节提到它，res/ 与清单里也没有 ⇒ '
                    '运行时没有任何路径能构造/使用它，钩它必然空转')
            if shell:
                note += '（加固壳命名空间：仍可能由壳在运行时 patch）'

        # **最后一道保险：证据不全时不许断言 DEAD。**
        # 读预算挡掉了一部分命中文件，而这几个目标恰好可能只在那些文件里被提到。
        # 此时"零引用"是**没看完**，不是**不存在** —— 必须降级成 INCOMPLETE 并说明原因，
        # 否则一次预算抖动就会被读成"钩了必然空转"。
        if verdict == V_DEAD and desc in incomplete:
            verdict = V_INCOMPLETE
            note = ('读预算未覆盖全部命中文件 ⇒ 无法判定是 DEAD 还是被引用（'
                    + incomplete[desc] + '）；提高 --read-budget 或缩小目标集后复跑')

        rows.append(Usage(target=cls, desc=desc, method=meth, verdict=verdict,
                          direct=direct, self_calls=selfc, class_refs=refs,
                          slot_refs=slot_refs, slot_owners=sorted(slot_owners),
                          external_refs=[os.path.relpath(f, root) for f in external][:6],
                          samples=invoke_samples or samples, shell=shell,
                          feaction=feaction, note=note))
    return rows


# ── CLI ───────────────────────────────────────────────────────────────────────

# ── 死代码**发现**（不是判定）───────────────────────────────────────────────────
#
# `analyse()` 回答"我钩的这个目标有没有使用证据"。但它需要**先有人给出目标**。
# `BrushMaskView` 那次失败的真正原因不是判定错了 —— 是**没人想到要把它列为目标**：
# 它看着像水印类，于是被钩了，然后永远不执行。
#
# 这一层做反向枚举：扫出"类存在、零引用、而且它唯一的正常入口只可能是布局/new"
# 的那些类。判据刻意保守，四个条件同时成立才算候选：
#
#   1. 类**不是**平台类，在解码目录里存在；
#   2. 父类链上有 UI 基类（`View` / `ViewGroup` / `Activity` / `Dialog` / `Fragment` …）
#      —— 这类东西的正常入口是布局 inflate 或 `startActivity`，不是代码里 invoke；
#   3. 全 APK 里**没有任何**别的文件提到它的描述符（`analyse` 的 class_refs == 0）；
#   4. `res/` 布局与清单里也没有它（`analyse` 已把这两处计入 external_refs）。
#
# 满足四条 ⇒ 它既没被代码引用、也没被布局引用 ⇒ **没有任何路径能实例化它**。
# 这不是"可疑"，是可证明的死代码。它仍然只是**候选**：加固壳可能在运行时 patch。
UI_BASES = (
    'Landroid/view/View;', 'Landroid/view/ViewGroup;', 'Landroid/widget/',
    'Landroid/app/Activity;', 'Landroid/app/Dialog;', 'Landroid/app/Fragment;',
    'Landroidx/fragment/app/Fragment;', 'Landroid/widget/FrameLayout;',
)


def _ui_ancestor(desc: str, infos: dict, index: dict, depth: int = 8) -> Optional[str]:
    """沿 `.super` 链上溯，返回第一个 UI 基类描述符；不是 UI 类返回 None。"""
    cur = desc
    seen = set()
    while cur and cur not in seen and depth > 0:
        seen.add(cur)
        depth -= 1
        if any(cur.startswith(b) for b in UI_BASES):
            return cur
        info = infos.get(cur)
        if info is None:
            p = index.get(cur)
            if p is None:
                return None
            info = infos[cur] = read_class_info(p)
        cur = info.super_desc
    return None


def find_dead_ui_classes(root: str, limit: int = 200,
                         roots_filter: Optional[Iterable[str]] = None) -> list[dict]:
    """扫出"零引用 + UI 子类"的类 —— 没有任何路径能实例化它们。

    **单遍扫描**，不是对每个类调一次 `analyse()`。第一版就是那样写的，在
    `com/byazt` 的 7416 个类上跑了 10 分钟没出结果：`analyse()` 每个目标都要
    grep 一遍全部 6 万个 smali ⇒ O(n²)。这里改成一次遍历建立"描述符出现次数"表，
    再做纯内存判定。

    `roots_filter` 限定只在某些 smali 根/包下找（唯一能把耗时压下来的手段）。

    判据（四条同时成立才算候选）：
      1. 类在解码目录里存在、不是平台类；
      2. 沿 `.super` 链能上溯到 UI 基类（View/Activity/Dialog/Fragment…）——
         这类东西的正常入口是布局 inflate 或 startActivity，不是代码 invoke；
      3. 该描述符在全 APK 里**只出现在它自己的文件里**（零外部引用）；
      4. `res/` 布局与清单里也没有它。
    ⇒ 既无代码引用、也无布局引用 ⇒ 没有任何路径能实例化。这是**可证明的**死代码，
    不是"可疑"。它仍然只是候选：加固壳可能在运行时 patch 出调用点。
    """
    index = class_file_index(root)
    wanted = {}
    for desc, path in index.items():
        if roots_filter and not any(f'/{r}/' in path.replace(os.sep, '/') for r in roots_filter):
            continue
        wanted[desc] = path
    if not wanted:
        return []

    # ── 单遍：统计每个候选描述符在**别的文件**里出现几次 ──────────────────────
    # 用一次 regex 扫全部 smali，只关心候选集合里的描述符。60 万个类全记会爆内存，
    # 所以用 `_alt` 把候选拼成一个 alternation（候选多时退化成逐类 str.count）。
    external: dict[str, int] = {d: 0 for d in wanted}
    names = list(wanted)
    # 太长会拖慢正则编译且有回溯风险；分批处理。
    BATCH = 400
    for i in range(0, len(names), BATCH):
        chunk = names[i:i + BATCH]
        rx = re.compile(_alt(chunk).encode())  # 字节正则，避免逐行解码
        for path in smali_files(root):
            try:
                with open(path, 'rb') as fh:
                    blob = fh.read()
            except OSError:
                continue
            for m in set(rx.findall(blob)):
                tok = m.decode()
                # 自己文件里的出现不算外部引用
                if wanted.get(tok) == path:
                    continue
                external[tok] = external.get(tok, 0) + 1

    # ── 布局 / 清单引用（`res/` 里按名字出现就算）─────────────────────────────
    res_hit = _res_references(root, wanted)

    infos: dict[str, ClassInfo] = {}
    out = []
    for desc, path in wanted.items():
        if external.get(desc, 0) or res_hit.get(desc):
            continue
        base = _ui_ancestor(desc, infos, index)
        if base is None:
            continue
        out.append({'class': desc_to_dotted(desc), 'ui_base': base, 'file': path,
                    'note': f'{V_DEAD}：零引用且未被布局/清单引用 ⇒ 无法被实例化'})
        if len(out) >= limit:
            break
    return out


def _res_references(root: str, wanted: dict) -> dict:
    """`res/` 下有没有按名字引用这些类（布局里的自定义 View 走 `a.b.C` 全名）。"""
    res = os.path.join(root, 'res')
    hits = {}
    if not os.path.isdir(res):
        return hits
    # 只看可能的布局/清单文本类资源
    names = {desc_to_dotted(d): d for d in wanted}
    rx = re.compile(_alt(names).encode())
    for base, _dirs, files in os.walk(res):
        for f in files:
            if not f.endswith(('.xml',)):
                continue
            try:
                with open(os.path.join(base, f), 'rb') as fh:
                    blob = fh.read()
            except OSError:
                continue
            for m in set(rx.findall(blob)):
                hits[names[m.decode()]] = os.path.join(base, f)
    return hits


def parse_target(spec: str) -> tuple[str, Optional[str]]:
    if ':' in spec:
        cls, meth = spec.split(':', 1)
        return cls.strip(), (meth.split('(', 1)[0].strip() or None)
    return spec.strip(), None


def main(argv):
    ap = argparse.ArgumentParser(description='检查钩子目标在 APK 里是否真的有人调用')
    ap.add_argument('--smali', default=repo_path('work/apktool_out'))
    ap.add_argument('--target', nargs='*', default=[], help='a.b.C 或 a.b.C:method')
    ap.add_argument('--from-module', default=None,
                    help='从模块源码取目标（复用 check_hook_targets.collect_targets）')
    ap.add_argument('--json', default=None)
    ap.add_argument('--summary', action='store_true')
    ap.add_argument('--max-samples', type=int, default=3)
    ap.add_argument('--read-budget', type=int, default=320,
                    metavar='MB',
                    help='命中文件最多读多少 MB（默认 320）。超出部分会被标成 '
                         'INCOMPLETE 而不是 DEAD —— 见 analyse() 的说明')
    ap.add_argument('--find-dead-ui', nargs='*', default=None, metavar='PKG',
                    help='反向枚举：在指定包/目录前缀下扫出"零引用 UI 子类"（可证明的死代码）。'
                         '不给参数 = 全量扫（很慢，几分钟）')
    a = ap.parse_args(argv[1:])

    if a.find_dead_ui is not None:
        found = find_dead_ui_classes(a.smali, roots_filter=a.find_dead_ui or None)
        print(f'[dead-ui] {len(found)} 个"零引用 UI 子类"（无法被实例化）')
        for r in found:
            print(f'  {r["class"]:60s} <- {r["ui_base"]}')
        if a.json:
            json.dump(found, open(a.json, 'w'), indent=2, ensure_ascii=False)
        return 0

    targets = [parse_target(t) for t in a.target]
    if a.from_module:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import check_hook_targets as cht
        for cls, meth, _w in cht.collect_targets(a.from_module):
            if (cls, meth) not in targets:
                targets.append((cls, meth))
    if not targets:
        ap.print_help()
        return 2

    rows = analyse(a.smali, targets, samples_per_target=a.max_samples,
                   read_budget=a.read_budget * 1024 * 1024)
    dead = [r for r in rows if not r.ok]
    if a.summary:
        for r in sorted(rows, key=lambda r: (r.verdict, r.target)):
            print(f'{r.label():16s} {r.target}{":" + r.method if r.method else ""}')
    else:
        print(f'{"结论":16s} {"目标":56s} {"直接":>4s} {"自调":>4s} {"类引":>5s} {"槽位":>4s}  说明')
        for r in rows:
            tgt = f'{r.target}{":" + r.method if r.method else ""}'
            print(f'{r.label():16s} {tgt:56s} {r.direct:4d} {r.self_calls:4d} '
                  f'{r.class_refs:5d} {r.slot_refs:4d}  {r.note}')
            for s in r.samples[:a.max_samples]:
                print(f'{"":16s} {"":56s} 例: {s}')
            for f in r.external_refs:
                print(f'{"":16s} {"":56s} 布局/清单: {f}')
    if a.json:
        json.dump([r.to_dict() for r in rows], open(a.json, 'w'), indent=2, ensure_ascii=False)
        print(f'[usage] -> {a.json}')
    # MISSING 不能被算进"有静态使用证据" —— 类根本不在解码目录里，
    # 我们对它一无所知。把它算成"有证据"是虚假通过（2026-10-25 修）。
    missing = [r for r in rows if r.verdict == V_MISSING]
    ok_n = len(rows) - len(dead) - len(missing)
    print(f'\n[usage] {ok_n}/{len(rows)} 目标有静态使用证据；'
          f'DEAD {len(dead)} 个'
          + (f' -> {", ".join(r.target for r in dead)}' if dead else '')
          + (f'；MISSING {len(missing)} 个（类不在解码目录，等于没有证据）'
             f' -> {", ".join(r.target for r in missing)}' if missing else ''))
    return 0 if not dead else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
