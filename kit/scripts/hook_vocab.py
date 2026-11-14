#!/usr/bin/env python3
"""
kuaidui-kit / hook_vocab.py — 钩子门禁的**统一词汇表**（单一定义处）。

为什么需要：④ `check_hook_targets.py` 与 ⑥ `smali_usage.py` 此前各自演出一套标签
（`OK` / `OK(load)` / `USED(self)` / `TYPE-ONLY` / `SKIP(platform)` … 混着出现在两列里），
读报告的人得来回对照才能确定"这个功能到底算不算过"。词汇表把它们钉在一处。

两层概念，不要混：
  * **判定** (`verdict`) —— 这个目标能不能钩（类/方法在不在、参数对不对）。
  * **使用证据** (`evidence`) —— 有没有人**调用**它（钩上去会不会执行）。

一条钩子的完整结论 = 判定 + 证据。两者独立的例子：
  * 判定 `OK` + 证据 `TYPE-ONLY`：类与方法都在，但只在类型位置出现
    （DTO/Gson 形态）—— 钩方法体很可能永远不执行，但钩**构造器/字段读**是有效的；
  * 判定 `MISSING` + 证据 `-`：连类都没有，谈不到证据。

字段说明
--------
verdict
  `OK`            类与方法都存在，参数类型吻合
  `OK(load)`      只校验了类（`clazzOrNull` 用法），方法不在本次判定范围
  `OK(platform)`  平台类（android.*/java.*），在 framework 里，不参与离线判定
  `MISSING`       类或方法不存在 —— **必红**
  `SIG-MISMATCH`  参数类型不符 —— **必红**

evidence（按强度从强到弱）
  `USED`          别的文件里有 invoke 指向它
  `USED(self)`    只有本类**别的方法**在调它（入口在别处，仍算活）
  `REFLECTIVE`    由注解/框架按名字反射调用（`@FeAction`、JS bridge）⇒ 静态 0 调用方是设计如此
  `SUPER-SLOT`    父类型声明了同名同参方法且槽位有 invoke-virtual ⇒ 可能经虚表进入
  `TYPE-ONLY`     只作为类型出现（字段/形参/new/const-class/res 布局）—— DTO 形态，不是死代码
  `DEAD`          本类之外**零**引用 ⇒ 钩方法体必空转 —— **必红**
  `-`             没有证据可谈（判定已经 MISSING）

只对 `MISSING` / `SIG-MISMATCH` / `DEAD` 报红。方法级的"不可达"需要全程序可达性分析，
静态证据不足，拿"看不见"当"不存在"正是本仓库反复踩的坑（`NEW_TARGETS.md` 那三条误报）。
"""

VERDICT_OK = 'OK'
VERDICT_LOAD = 'OK(load)'
VERDICT_PLATFORM = 'OK(platform)'
VERDICT_MISSING = 'MISSING'
VERDICT_SIG_MISMATCH = 'SIG-MISMATCH'

VERDICTS = {
    'OK': '类与方法都存在，参数类型吻合',
    'OK(load)': '只校验了类（clazzOrNull 用法），方法不在本次判定范围',
    'OK(platform)': '平台类，在 framework 里，不参与离线判定',
    'MISSING': '类或方法不存在',
    'SIG-MISMATCH': '参数类型不符',
}

EVIDENCE = {
    'USED': '别的文件里有 invoke 指向它',
    'USED(self)': '只有本类别的方法在调它（入口在别处，仍算活）',
    'REFLECTIVE': '注解/框架按名字反射调用，静态 0 调用方是设计如此',
    'SUPER-SLOT': '父类型槽位有 invoke-virtual，可能经虚表进入',
    'TYPE-ONLY': '只作为类型出现（DTO 形态），不是死代码',
    'DEAD': '本类之外零引用，钩方法体必空转',
    '-': '没有证据可谈（判定已 MISSING）',
}

# 判红的三类。排序即报告里的优先顺序（最严重的在前）。
RED = ('MISSING', 'SIG-MISMATCH', 'DEAD')

# 强 → 弱。多处证据取最强的一条作为结论。
STRENGTH = ['USED', 'USED(self)', 'REFLECTIVE', 'SUPER-SLOT', 'TYPE-ONLY', 'DEAD', '-']


def is_red(verdict: str = '', evidence: str = '') -> bool:
    """这条钩子算不算失败。"""
    return verdict in RED or evidence in RED


def strongest(*evidences: str) -> str:
    """取最强证据（忽略 None/空）。"""
    best = '-'
    for e in evidences:
        if not e:
            continue
        if STRENGTH.index(e) < STRENGTH.index(best):
            best = e
    return best


def explain(verdict: str = '', evidence: str = '') -> str:
    """一行人类可读解释，用于 `--explain`。"""
    v = VERDICTS.get(verdict, '')
    e = EVIDENCE.get(evidence, '')
    return ' | '.join(x for x in (v, e) if x)


# ── 钩子调用形态：三份清单的**单一正则来源** ───────────────────────────────────
#
# 为什么把它放在词汇表里而不是各脚本里：④⑤⑥ 各写一套正则是"三份清单互不相同"的
# 直接原因（`test_hook_gate_agreement.py` 记着 ④ 73 / ⑤ 48 / ⑥ 48 那次）。
# 2026-10-25 又发现第四种形态：**直接调 `XposedHelpers.findAndHookMethod`**。
# `HostFeatures.kt` 的 `ReqHeaders`（3 处）与 `WebRequestLog` 的 java 侧都走这条路径，
# 于是这两个功能在 `VERIFICATION.md` 的「静态钩子」列显示 `-` —— 看着像没有静态依据，
# 实际是门禁不认这种写法。三条 `XposedHelpers.*` 调用与 `Xp.*` 是同一种东西：
# 只是没包一层记账/门控。
#
# 形态清单（每条都对应真实调用点，别凭想象加）：
#   Xp.hook("类","方法", 参数…)                     —— 标准门控钩
#   Xp.hookAll*("类","方法", cl, cb)                —— 全部重载（无形参可比）
#   Xp.hookCtor("类", 参数…)                        —— 构造器，方法名恒 <init>
#   Xp.clazzOrNull("类")                            —— 只有类引用
#   hook("类","方法") / hookBytes(…) / hookAll(…)   —— 功能自写的包装
#   XposedHelpers.findAndHookMethod("类", cl, "方法", 参数…)
#   XposedHelpers.findAndHookConstructor("类", cl, 参数…)
import re as _re

# `XposedHelpers.findAndHookMethod("com.x.Y", Xp.classLoader, "m", A::class.java, …)`
# 第 2 个实参是 classLoader，第 3 个才是方法名 —— 中间那段允许任意非引号字符。
XPOSED_METHOD_RE = _re.compile(
    r'XposedHelpers\.findAndHookMethod\(\s*'
    r'(?:"([^"]+)"|([A-Za-z_]\w*))\s*,\s*[^,]+,\s*"([^"]+)"')
# `XposedHelpers.findAndHookConstructor("com.x.Y", cl, A::class.java, …)`
XPOSED_CTOR_RE = _re.compile(
    r'XposedHelpers\.findAndHookConstructor\(\s*(?:"([^"]+)"|([A-Za-z_]\w*))')


# ── smali 方法名：**一个定义，三处共用** ──────────────────────────────────────
#
# 2026-10-25 第 29 轮：`check_hook_callers.py`、`smali_usage.py`、
# `check_robust_coverage.py` 各写了一份方法名正则，三份都写成 `[\w$<>]+`，
# 于是 **`-` 不在字符集里**。Kotlin 内联 lambda 的方法名带连字符：
#
#     .method private static final updateRobotPos$lambda-5$lambda-4(L…;IIIIZ…)V
#
# 实测后果（同一份 APK）：
#   * `[\w$<>]+` 把它切成方法名 **`4`**（`5$lambda-` 被甩掉），
#   * 另一种写法（整行锚定 `^\.method[^\n]*?([\w$<>]+)\(`）干脆匹配不上 ⇒ 少记一条。
# 24 个方法的真实名字因此从未进入任何索引 —— 而门禁一直是绿的。
#
# **这就是"正则写窄 = 一整类声明失去保护"第三次复发**（见 PARADIGM §7.6 / OPTIMIZATION §35）。
# 修法不是把三处各改一遍（下一次还会漏一处），而是把词法收到这里：
#   * `SMALI_NAME` —— smali 里合法的成员名：字母数字 `$` `_` `-` `<` `>`。
#     覆盖 `<init>` / `<clinit>` / `foo$lambda-0` / `-$$Lambda$X$Y` 这些真实形态；
#   * `METHOD_HEADER_RE` —— `.method` 头。**名字段不吞修饰符**：先吃掉已知修饰词，
#     再取到第一个 `(` 之前的所有内容当名字（允许空 ⇒ 解析不出来时要能被发现，而不是编个名）。
#   * `INVOKE_TARGET_RE` —— `invoke-*` 的目标（类描述符 + 方法名）。
SMALI_NAME = r'[A-Za-z0-9_$\-<>]+'
METHOD_HEADER_RE = _re.compile(
    r'^\.method\s+((?:(?:public|private|protected|static|final|abstract|synthetic|bridge|'
    r'native|constructor|declared-synchronized|varargs|strictfp|transient|volatile)\s+)*)'
    r'(' + SMALI_NAME + r')\(([^)]*)\)(\S*)',
    # `re.M` 曾经漏掉，于是 `finditer(整个文件)` 返回 **0 条**：
    # 三个脚本都把索引建立在"扫整个文件"上，漏了 M 就等于整张表为空，
    # 而空表不会报错，只会让判定退化成"没有证据"。别再漏。
    _re.M)
# 同时提供**位置组**与**命名组**：三个脚本对组的取法不同（`m.group(2)` vs `m.group('meth')`），
# 合并成一条正则时必须两种都满足，否则会造成"改了 A 脚本、B 脚本静默错位"的新坑。
INVOKE_TARGET_RE = _re.compile(
    r'invoke-(?P<op>[\w/-]+?)(?:/range)?\s+\{[^}]*\},\s*'
    r'L(?P<owner>[\w$/]+);->(?P<meth>' + SMALI_NAME + r')\(')


def parse_method_header(line: str):
    """`.method …` 一行 -> (修饰符, 方法名, 形参描述符, 返回类型+尾注) 或 None。

    单独一个函数是为了让三个脚本用**同一段判定**，而不是各自复制正则
    （复制就会漂移，漂移就会漏一类 —— 本文件已经因为这件事改过两次）。
    """
    m = METHOD_HEADER_RE.match(line.strip())
    if not m:
        return None
    return m.group(1).strip(), m.group(2), m.group(3), m.group(4)


# `for (m in listOf("d","f","h")) { … }` 的**作用域**展开。
#
# 为什么需要作用域：`AdFeatures.kt` 里有两处 `for (m in listOf(…))` ——
# `RemoveAdSlotConfig` 用 `("d","f","h")` 配 `Int` 形参，`AdSlotProbe` 用同一批名字。
# 一处 `("j","k")` 配**零**形参。早先的实现在整个文件里建一个 `{变量名: [字面量]}` 字典，
# 于是同名 `m` 被后来的循环覆盖：`("j","k")` 那两行被按 `("d","f","h")` 展开，
# 得到 `aj.a.d()`/`aj.a.f()`/`aj.a.h()` —— 三条**签名不符**的假目标
# （真实签名是 `(I)`，而 `j()/k()` 才是 `()`）。假红比漏报更糟：它教人无视门禁。
#
# 这里把每个 `listOf` 绑定到它自己的花括号块（区间），查表时按**位置**归属。
def loop_scopes(text: str):
    """-> [(变量名, [字面量], 块起始偏移, 块结束偏移)]，块按花括号配平。

    也用 `for (…) { }` 的**单语句**形态（Kotlin 允许省略花括号）：
    此时作用域取"到下一个 `for` 或文件末尾"，宁可宽一点也不漏。
    """
    out = []
    for m in _re.finditer(r'for\s*\(\s*(\w+)\s+in\s+listOf\(([^)]*)\)\s*\)', text):
        var = m.group(1)
        lits = _re.findall(r'"([^"]*)"', m.group(2))
        brace = text.find('{', m.end())
        # `for (…)` 与 `{` 之间只允许空白/换行；否则视为无花括号的单语句形态。
        if brace >= 0 and text[m.end():brace].strip() == '':
            depth, i = 0, brace
            while i < len(text):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            out.append((var, lits, brace, i))
        else:
            nxt = text.find('for', m.end())
            out.append((var, lits, m.end(), len(text) if nxt < 0 else nxt))
    return out


def loop_literals_at(scopes, var: str, pos: int):
    """位置 `pos` 处的 `var` 展开成哪些字面量（按最内层作用域）。"""
    best = None
    for v, lits, a, b in scopes:
        if v != var or not (a <= pos <= b):
            continue
        if best is None or (b - a) < (best[3] - best[2]):
            best = (v, lits, a, b)
    return best[1] if best else None


def read_text(path: str) -> str:
    """读一个（Kotlin / smali）文本文件。

    整个门禁链路要扫 5 万个 smali + 500 个 .kt。裸 `open(p).read()` 依赖 CPython
    的引用计数才*恰好*不会堆积句柄 —— 它不是协议保证，换运行时或改 GC 行为就会撞
    `Too many open files`（macOS 默认 `ulimit -n` 只有 256）。同一个写法还产出
    49931 条 `ResourceWarning`，把 `-q` 的输出淹没成 15 万行，真失败反而看不见。
    统一走这一个函数，门禁才有资格说"离线可重复"。
    """
    with open(path, encoding='utf-8', errors='replace') as fh:
        return fh.read()


def repo_path(relative: str) -> str:
    """把 `work/apktool_out` 这类**相对仓库根**的路径解析成绝对路径。

    为什么必须这么写：④⑤⑥ 与 smali_usage 的 `--smali` 默认值是 `'work/apktool_out'`，
    是相对**当前工作目录**的。`verify.sh` 里用 `cd '$ROOT'` 兜住了，所以命令行一直是对的；
    但任何**从 Python 里调**这些门禁的地方（`feature_matrix.static_hook_evidence()`）
    继承的是自己的 cwd，于是 `listdir` 抛 `FileNotFoundError` → 门禁返回空 →
    `VERIFICATION.md` 的「静态钩子」整列变成 `-`。

    这个失效特别危险：它**不报错**，只是让文档看起来"这些功能没有静态证据"。
    2026-10-25 就是这样让 ①b 的 13 个断言集体失败才被发现的。
    """
    import os
    here = os.path.dirname(os.path.abspath(__file__))     # kit/scripts
    root = os.path.dirname(os.path.dirname(here))          # 仓库根
    return os.path.join(root, relative)


# ── 宿主混淆名映射（`HostMap.kt`） ──────────────────────────────────────────────
#
# 为什么门禁要读模块源码里的这张表：4 个钩子的类名在 **7.10.2/1860** 与
# **6.21.11/1865** 之间整个重排了（`di.a`/`dj.a`/`vm.g`/`fh.a` → `bi.a`/`bj.a`/`tm.g`/`dh.a`）。
# 模块的调用点**保留基线字面量**（这样文档、共享表、`PARADIGM` 都仍按基线名对齐），
# 由 `HostMap` 在运行时翻译。于是"在 1865 的树上跑门禁"必须先按同一张表把字面量
# 解析到**这棵树里真实存在的那一侧**，否则门禁会把 4 类目标全报成 MISSING ——
# 而那正是"代码其实是对的、门禁说错了"的假红，比漏报更快教人无视门禁。
#
# 单一定义处：④ 与 ⑤ 都调 `resolve_target()`，两边不可能给出不同答案
# （这个仓库已经因为"两份实现互相不一致"踩过一次，见 `check_hook_targets.py` 的注释）。
#
# 表的一行就是 `Rename("id", "基线名", "1865 名")`。**这个文本形状是契约**：
# `HostMap.kt` 的注释里也写着同一句，改格式会让这里解析不到（`host_map()` 返回空表 ⇒
# 所有目标退回"按字面量查"，1865 一侧立刻变红，不会静默错判）。
HOSTMAP_RE = _re.compile(r'Rename\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')

#: 1865 = 内测包 6.21.11（`work/apktool_out_6211/apktool.yml`）。
VERSION_CODE_1865 = 1865

_HOSTMAP_CACHE = {}
_VERSION_CACHE = {}


def host_map(module_dir: str = None):
    """读 `HostMap.kt` 的 `Rename(...)` 行 -> {任意一侧的名字: (id, 基线名, 1865 名)}。

    三种写法（id / 基线名 / 1865 名）都作为键，所以调用点无论写哪一侧都能查到同一条。
    """
    import os
    if module_dir is None:
        module_dir = repo_path('module/app/src/main/java/dev/xalor/kdkit')
    if module_dir in _HOSTMAP_CACHE:
        return _HOSTMAP_CACHE[module_dir]
    path = os.path.join(module_dir, 'HostMap.kt')
    table = {}
    if os.path.isfile(path):
        for m in HOSTMAP_RE.finditer(read_text(path)):
            # Kotlin 里 `$` 在字符串字面量中必须写成 `\$`（内部类名因此写作 `ps.f\$e`），
            # 而运行时字符串与 smali 描述符里都是 `ps.f$e`。不反转义，键就与调用点的
            # `"ps.f\$e"` 对不上 —— 表现是"表里有这条、但永远命中不了"（静默失效）。
            # 三个字段都归一，`resolve_target()` 返回表里的值 ⇒ 自动是对的。
            ident, base, new = (m.group(1).replace('\\$', '$'),
                                m.group(2).replace('\\$', '$'),
                                m.group(3).replace('\\$', '$'))
            entry = (ident, base, new)
            table[ident] = entry
            table[base] = entry
            table[new] = entry
    _HOSTMAP_CACHE[module_dir] = table
    return table


def tree_version(smali_root: str):
    """从 `<tree>/apktool.yml` 读 versionCode（读不到返回 None）。

    为什么要读树而不是命令行参数：同一条命令要在两棵树上跑，人不可能每次记得
    传 `--version`；而 `apktool.yml` 是 apktool 自己写的，**它不会撒谎**。
    """
    import os
    if smali_root in _VERSION_CACHE:
        return _VERSION_CACHE[smali_root]
    code = None
    path = os.path.join(smali_root, 'apktool.yml')
    if os.path.isfile(path):
        m = _re.search(r'^\s*versionCode:\s*(\d+)', read_text(path), _re.M)
        if m:
            code = int(m.group(1))
    _VERSION_CACHE[smali_root] = code
    return code


def resolve_target(cls: str, version_code, module_dir: str = None):
    """把源码里的类字面量解析到**这棵树上该查的那个名字**。

    返回 `(name_to_check, alias_note_or_None)`：
      * 表外的类 —— 原样返回，`None`（绝大多数目标走这条，行为与加表之前逐字节相同）；
      * 表内、且这棵树就是该侧 —— 原样返回，`None`（基线树上是常态）；
      * 表内、跨侧 —— 返回该侧的名字 + 一条 `alias a→b` 说明，让报告里**看得见**翻译。

    版本未知（`apktool.yml` 缺失）时按基线处理：那时的行为与加表之前一致，
    宁可"老行为"也不要"猜一个新的"。
    """
    entry = host_map(module_dir).get(cls)
    if not entry:
        return cls, None
    _ident, base, new = entry
    want = new if version_code == VERSION_CODE_1865 else base
    if want == cls:
        return cls, None
    return want, f'{cls}->{want}'
