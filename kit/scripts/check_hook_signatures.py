#!/usr/bin/env python3
"""
kuaidui-kit / check_hook_signatures.py — 钩子**签名级**校验（check_hook_targets.py 补位）。

为什么需要第二个脚本：`check_hook_targets.py` 只比对"类名 + 方法名"。
签名写错时它照样报 `OK`，而运行时 `Xp.hook` 返回 false、功能**静默失效** ——
这正是 2026-10-25 静态侦察（`module/NEW_TARGETS.md` U6）指出的盲区。

本脚本只看**能静态确定**的那部分，宁可报"无法判定"也不猜：

  可判定（UNKNOWN → 不参与断言）：
    * 形参是 `String::class.java` / `Int::class.javaPrimitiveType` / `ByteArray::class.java`
      / `java.util.Map::class.java` 等已知映射，或 `a.b.C::class.java`（→ `La/b/C;`）；
    * `clazzOrNull("x.Y")` 形式的类引用（运行时才知道，标 UNKNOWN）。

  不判定：
    * 形参来自变量/常量/`$PKG` 拼串（`Xp.clazzOrNull(...)` 的返回值等）；
    * 方法名是 `<init>`（构造器，`findAndHookMethod` 不接受）。

输出四态：OK / SIGNATURE-MISMATCH / UNKNOWN / MISSING。

    python3 kit/scripts/check_hook_signatures.py                  # 全量
    python3 kit/scripts/check_hook_signatures.py --json out.json
    python3 kit/scripts/check_hook_signatures.py --strict         # UNKNOWN 也算红

退出码：有 SIGNATURE-MISMATCH（或 --strict 下的 UNKNOWN）时 1。
"""
import argparse
import json
import os
import re
import sys

# 调用形态的正则（含 `XposedHelpers.findAndHookMethod`）只定义在词汇表里 ——
# ④⑤⑥ 各写一套正是"三份清单互不相同"的根因。
import hook_vocab as vocab
from hook_vocab import read_text, repo_path

WANTED = {
    'String::class.java': 'Ljava/lang/String;',
    'Int::class.javaPrimitiveType': 'I',
    'Int::class.java': 'I',
    'Boolean::class.javaPrimitiveType': 'Z',
    'Boolean::class.java': 'Z',
    'Long::class.javaPrimitiveType': 'J',
    'Long::class.java': 'J',
    'Float::class.javaPrimitiveType': 'F',
    'Double::class.javaPrimitiveType': 'D',
    'Short::class.javaPrimitiveType': 'S',
    'Byte::class.javaPrimitiveType': 'B',
    'Char::class.javaPrimitiveType': 'C',
    'ByteArray::class.java': '[B',
    'IntArray::class.java': '[I',
    'ByteArray::class': '[B',
    'java.util.Map::class.java': 'Ljava/util/Map;',
    'java.util.List::class.java': 'Ljava/util/List;',
    'java.util.HashMap::class.java': 'Ljava/util/HashMap;',
    'android.os.Bundle::class.java': 'Landroid/os/Bundle;',
    'android.app.Activity::class.java': 'Landroid/app/Activity;',
    'android.content.Context::class.java': 'Landroid/content/Context;',
    'android.view.View::class.java': 'Landroid/view/View;',
    'org.json.JSONObject::class.java': 'Lorg/json/JSONObject;',
}

STOP_TOKENS = ('gate', 'onBefore', 'onAfter', 'cl', 'onAfterCb', 'cb', 'vararg')
# 直接调 `XposedHelpers.*` 时，最后一个实参是**匿名回调对象**：
#     findAndHookMethod("类", cl, "方法", String::class.java, object : XC_MethodHook() { … })
# 它不是形参，遇到就必须停 —— 否则会把它当成"无法静态判定的类型"、
# 把整条钩子降级成 UNKNOWN，看起来像"签名校验不了"，实际只是没识别回调。
CALLBACK_TOKEN_PREFIX = ('object ', 'object:')

# 运行时才确定的类名：`Xp.hook(name, ...)`，`name` 来自 `cb.javaClass.name` 或注入的
# client 类。**必须显式列出来**，否则它们会被当成"类名叫 name" 的静态目标 ——
# 那不是漏报，而是假报：门禁会说 `MISSING-CLASS name`，而实际运行时是好的。
DYNAMIC_CLASS_VARS = {'name', 'cls', 'className', 'clazz', 'it', 'type'}


def smali_roots(root):
    return [os.path.join(root, n) for n in sorted(os.listdir(root))
            if os.path.isdir(os.path.join(root, n)) and (n == 'smali' or re.fullmatch(r'smali_classes\d+', n))]


def index_classes(root):
    idx = {}
    for r in smali_roots(root):
        for base, _d, files in os.walk(r):
            for f in files:
                if f.endswith('.smali'):
                    rel = os.path.relpath(os.path.join(base, f), r)[:-6].replace(os.sep, '.')
                    idx.setdefault(rel, os.path.join(base, f))
    return idx


DESC_CACHE = {}


def descriptors(path):
    if path in DESC_CACHE:
        return DESC_CACHE[path]
    out = {}
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            for line in fh:
                if line.startswith('.method'):
                    m = re.search(r'([\w$<>]+)\(([^)]*)\)', line)
                    if m:
                        out.setdefault(m.group(1), set()).add('(' + m.group(2) + ')')
    except OSError:
        pass
    DESC_CACHE[path] = out
    return out


def split_args(text):
    """把 hook 调用的形参列表切成 token（尊重嵌套括号与 $ 名称）。"""
    # 直接调 `XposedHelpers.*` 时，正则停在方法名/类名的引号上，剩下的文本以逗号开头，
    # 不清掉会得到一个空 token（并被当成"零参数"或"无法判定"）。`Xp.*` 形态的正则
    # 已经把逗号吃掉了，所以这一步对它是空操作。
    text = text.lstrip(', \t\r\n')
    # **先剥掉 `//` 行尾注释**：`Xp.hook("dr.f", "a", callback,   // dr.f$e  —— 网络回调`
    # 这种写法里，注释会被当成一个形参名，于是拼出 `L// dr/f$e  —— 网络回调` 这种
    # 明显带中文的"签名"，再与真实签名比对就必然是 MISMATCH —— 门禁自己造出来的假红。
    #
    # 只剥到行尾，不管字符串内的 `//`（本文件处理的都是 Class 表达式，不含字符串字面量）。
    text = re.sub(r'//[^\n]*', '', text)
    out, depth, cur = [], 0, ''
    for ch in text:
        if ch in '([':
            depth += 1
        elif ch in ')]':
            if depth == 0:
                break
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur.strip())
            cur = ''
            continue
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


# 两种调用形态，用两个正则分开匹配（合成一个会让 hookCtor 的第一个参数被误当方法名）：
#   Xp.hook("类", "方法", 参数...)
#   Xp.hookCtor("类", 参数...)
#
# `hookAll` 系（`hookAll` / `hookAllBefore` / `hookAllAfter`）**没有形参**：它们按方法名
# 钩全部重载（`Xp.hookAll(className, methodName, cl, cb)`）。所以对它们只做"类+方法存在"
# 的判定（`sig=None` → `UNKNOWN(no parameter check: hookAll …)`），而不是假装比对签名。
# 2026-10-25 之前这些目标**连类都不进本脚本**（正则只认 `Xp.hook(`），于是
# `SignObserver` / `LogSink` / `NativeProbe` / `BridgeGuard` / `H5BridgeLog` / `H5Debug` /
# `ReqHeaders` 这 7 个功能在 `VERIFICATION.md` 的「静态钩子」列只能显示 `-`
# —— 看着像"没有静态证据"，实际是"门禁没看"。
HOOK_RE = re.compile(r'Xp\.hook\(\s*(?:"([^"]+)"|([A-Za-z_]\w*))\s*,\s*"([^"]+)"\s*,?')
# `Xp.hook("类", m, …)` —— 方法名是循环变量。`HOOK_RE` 只认引号形式，于是
# `for (m in listOf("d","f","h")) Xp.hook("aj.a", m, …)` 这 5 个真实钩子
# （`RemoveAdSlotConfig` 3 / `AdSlotProbe` 3）从未被签名校验过。
HOOK_VAR_RE = re.compile(
    r'Xp\.hook\(\s*(?:"([^"]+)"|([A-Za-z_]\w*))\s*,\s*([A-Za-z_]\w*)\s*,')
# `listOf(...)` 的参数若含括号嵌套（例如 `listOf(a.name())`），`[^)]*` 会在第一个
# 右括号停下 ⇒ **整个 for 循环不被识别**，循环里的钩子对门禁完全不可见。
# 2026-10-26：`feature_matrix.py` 的 `SwitchFeature(...)` 就是因为同一原因
# （`summary` 里写了 `钩 dj.e.f()`）导致第 37 个功能从文档里消失。
# 改成允许一层嵌套。真需要更深时，应该写括号平衡扫描而不是继续堆正则。
LOOP_LIST_RE = re.compile(r'for\s*\(\s*(\w+)\s+in\s+listOf\(((?:[^()]|\([^()]*\))*)\)\s*\)')
LOOP_STR_RE = re.compile(r'"([^"]*)"')
ALL_RE = re.compile(r'Xp\.hookAll\w*\(\s*(?:"([^"]+)"|([A-Za-z_]\w*))\s*,\s*"([^"]+)"\s*,?')
# `Xp.hookAll("android.util.Log", m, …)` —— 方法名是循环变量。
# `LogSink` 的 6 个目标（v/d/i/w/e/wtf）走这条路径，此前只有 ④ 看得到，
# ⑤ 完全没记录 —— 「三份清单相等」这条断言因此不成立（④ 92 / ⑤ 75）。
ALL_VAR_RE = re.compile(
    r'Xp\.hookAll\w*\(\s*(?:"([^"]+)"|([A-Za-z_]\w*))\s*,\s*([A-Za-z_]\w*)\s*,')
# 第一个实参可以是字面量，也可以是指向 `const val` 的标识符
# （`NetErrorProbe` 写的是 `Xp.hookCtor(CLS, ecCls, …)`，两者都是 const val）。
CTOR_RE = re.compile(r'Xp\.hookCtor\(\s*(?:"([^"]+)"|([A-Za-z_]\w*))\s*,?')
# 功能自写的 `hookAll("类", "方法")` 包装（`ExitGuard` 的 5 个目标走这条路径）。
LOCAL_HOOKALL_RE = re.compile(r'\bhookAll\(\s*"([\w.$]+)"\s*,\s*"([\w$<>]+)"\s*\)')
# 功能自写的 `hook("类", "方法")` 包装（`SignObserver` 的 8 个目标走这条路径）。
# **不对称过**：④ 早已识别这个包装器，⑤ 只认 `Xp.hook(`，于是 `Net.appendSign`、
# `yl.f.*`、`baseutil.a.*` 这 8 个目标的形参类型从未被签名门禁校验过。
# `(?<![\w.])` 排除 `Xp.hook(` —— 那由 HOOK_RE 负责，重复计数会让统计虚高。
LOCAL_HOOK_RE = re.compile(r'(?<![\w.])hook\(\s*"([\w.$]+)"\s*,\s*"([\w$<>]+)"\s*[,)]')
# 本地类引用：val x = Xp.clazzOrNull("a.b.C") / Xp.clazz("a.b.C")
CLAZZ_VAL_RE = re.compile(r'val\s+(\w+)\s*=\s*Xp\.clazz(?:OrNull)?\(\s*"([^"]+)"\s*\)')
# 行内类引用：Xp.clazzOrNull("a.b.C") 直接当实参
CLAZZ_INLINE_RE = re.compile(r'^Xp\.clazz(?:OrNull)?\(\s*"([^"]+)"\s*\)')
# 本地 val 是 `::class.java` 别名：val list = java.util.List::class.java
CLASSREF_VAL_RE = re.compile(r'val\s+(\w+)\s*=\s*([\w.$]+::class\.java(?:PrimitiveType)?)')


def expand_all(text, consts):
    for _ in range(4):
        text = re.sub(r'\$\{?(\w+)\}?', lambda x: consts.get(x.group(1), x.group(0)), text)
    # Kotlin 源码里写 `HybridWebView\$ReturnCallback`（转义 $）—— 运行时字符串是 `...$ReturnCallback`。
    # smali 用的是后者，所以这里必须把反斜杠还原，否则每个带内部类的目标都会被误报不符。
    return text.replace('\\$', '$')


#: Kotlin 的 `Array<T>::class.java` 在 JVM 里是**数组类型**的描述符。
#: 不映射会得到 `LArray<Any>;` 这种非法的"类名"，与真实签名永远不匹配 ——
#: 门禁自己造出来的假红（`RobustProbe` 的 `PatchProxy.proxy` 就是这么红的）。
ARRAY_ELEM = {
    'Any': 'java/lang/Object', 'String': 'java/lang/String',
    'Int': 'java/lang/Integer', 'Long': 'java/lang/Long',
    'Byte': 'java/lang/Byte', 'Char': 'java/lang/Character',
    'Boolean': 'java/lang/Boolean', 'Float': 'java/lang/Float',
    'Double': 'java/lang/Double', 'Short': 'java/lang/Short',
    'Class': 'java/lang/Class',
}


def to_desc(class_name):
    # `Array<T>` → `[L<T>;`；`Array<Byte>` → `[B`（原始类型数组）。
    m = re.fullmatch(r'Array<([\w.$]+)>', class_name.strip())
    if m:
        elem = m.group(1)
        prim = {'Byte': 'B', 'Char': 'C', 'Boolean': 'Z', 'Short': 'S',
                'Int': 'I', 'Long': 'J', 'Float': 'F', 'Double': 'D'}
        if elem in prim:
            return '[' + prim[elem]
        body = ARRAY_ELEM.get(elem) or IMPLICIT_JAVA.get(elem) or elem
        return '[L' + body.replace('.', '/') + ';'
    # 简单名先过隐式表：`Any` → `java/lang/Object`、`String` → `java/lang/String`。
    # 不过这一步会得到 `LAny;` —— 非法描述符，永远匹配不上真实签名。
    if '.' not in class_name:
        class_name = IMPLICIT_JAVA.get(class_name, class_name)
    return 'L' + class_name.replace('.', '/') + ';'


# Kotlin/Java 里**不需要 import** 的简单名。写 `HashMap::class.java` 是合法的，
# 但它的二进制描述符是 `Ljava/util/HashMap;`，不是 `LHashMap;`。
# 不补这张表，门禁会把它解成 `LHashMap;` 并报 SIGNATURE-MISMATCH ——
# 一个**假红**，而假红比漏报更危险：它教人忽略门禁。
# 只列真实出现在模块里的（`HostFeatures` 的 `d(…, HashMap)`、`WatermarkOff` 的 `Float`），
# 加上 `java.lang.*` 这批必然隐式可见的。
IMPLICIT_JAVA = {
    'String': 'java.lang.String', 'Object': 'java.lang.Object',
    # Kotlin 的 `Any` 编译成 `java.lang.Object` —— 源码里写 `Any::class.java` 时，
    # 描述符是 `Ljava/lang/Object;`。不映射会得到 `LAny;`（非法）。
    'Any': 'java.lang.Object',
    'Integer': 'java.lang.Integer', 'Long': 'java.lang.Long',
    'Boolean': 'java.lang.Boolean', 'Float': 'java.lang.Float',
    'Double': 'java.lang.Double', 'Short': 'java.lang.Short',
    'Byte': 'java.lang.Byte', 'Character': 'java.lang.Character',
    'CharSequence': 'java.lang.CharSequence', 'Throwable': 'java.lang.Throwable',
    'Exception': 'java.lang.Exception', 'RuntimeException': 'java.lang.RuntimeException',
    'Class': 'java.lang.Class', 'Number': 'java.lang.Number',
    'HashMap': 'java.util.HashMap', 'Map': 'java.util.Map',
    'List': 'java.util.List', 'ArrayList': 'java.util.ArrayList',
    'Set': 'java.util.Set', 'HashSet': 'java.util.HashSet',
    'Collection': 'java.util.Collection', 'Iterator': 'java.util.Iterator',
}


def import_map(text):
    """`import a.b.C` / `import a.b.C as D` -> {'C': 'a.b.C'}（别名优先）。"""
    out = {}
    for m in re.finditer(r'^import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$', text, re.M):
        fq, alias = m.group(1), m.group(2)
        out[alias or fq.rsplit('.', 1)[-1]] = fq
    return out


def collect(module_dir):
    """返回 [{cls, meth, sig, where}]，sig=None 表示静态无法确定。"""
    rows = []
    for base, _d, files in os.walk(module_dir):
        if os.sep + 'build' + os.sep in base + os.sep:
            continue
        for f in sorted(files):
            if not f.endswith('.kt'):
                continue
            path = os.path.join(base, f)
            text = read_text(path)
            consts = dict(re.findall(r'const val (\w+)\s*=\s*"([^"]*)"', text))
            # 简单类型名 -> 全限定名（`HashMap` -> `java.util.HashMap`）
            imports = import_map(text)
            # 本地 val 指向的类（`val returnCb = Xp.clazzOrNull("...")`）也能静态解析
            clazz_vals = {
                name: expand_all(lit, consts)
                for name, lit in CLAZZ_VAL_RE.findall(text)
            }
            classref_vals = {
                name: expand_all(lit, consts)
                for name, lit in CLASSREF_VAL_RE.findall(text)
            }
            calls = [(m.group(1) or m.group(2), m.group(3), m.end(), False)
                     for m in HOOK_RE.finditer(text)]
            # hookAll* 没有形参：标记 `no_sig` 让下面的解析跳过，sig 保持 None。
            calls += [(m.group(1) or m.group(2), m.group(3), m.end(), True)
                      for m in ALL_RE.finditer(text)]
            calls += [(m.group(1) or m.group(2), '<init>', m.end(), False)
                      for m in CTOR_RE.finditer(text)]
            calls += [(m.group(1), m.group(2), m.end(), True)
                      for m in LOCAL_HOOKALL_RE.finditer(text)]
            # `hook("类","方法")` 包装器：形参由包装器内部决定，这里同样按"无形参可比"处理
            calls += [(m.group(1), m.group(2), m.end(), True)
                      for m in LOCAL_HOOK_RE.finditer(text)]
            # 第四种形态：直接调 `XposedHelpers.findAndHookMethod` / `findAndHookConstructor`。
            # 它们**有形参**（classLoader 之后的那串），所以走签名比对路径。
            # `Xp.classLoader` 那一段由正则吃掉，不在 `split_args` 看到的文本里。
            calls += [(m.group(1) or m.group(2), m.group(3), m.end(), False)
                      for m in vocab.XPOSED_METHOD_RE.finditer(text)]
            calls += [(m.group(1) or m.group(2), '<init>', m.end(), False)
                      for m in vocab.XPOSED_CTOR_RE.finditer(text)]
            # 循环变量方法名：按文件内的 `listOf(...)` **作用域**展开成字面量。
            # 不能用"变量名 -> 列表"的全局字典：`AdFeatures.kt` 有两个同名 `m`
            # （`("d","f","h")` 带 `Int` 形参、`("j","k")` 零形参），后者覆盖前者
            # 会造出 `aj.a.d()` 这样的假目标（真实签名是 `(I)`）。
            scopes = vocab.loop_scopes(text)
            if scopes:
                for m in HOOK_VAR_RE.finditer(text):
                    lits = vocab.loop_literals_at(scopes, m.group(3), m.start())
                    if not lits:
                        continue
                    for val in lits:
                        calls.append((m.group(1) or m.group(2), val, m.end(), False))
                # `hookAll` 的循环形态同样要进来（否则 ④ 看到、⑤ 看不到）。
                for m in ALL_VAR_RE.finditer(text):
                    lits = vocab.loop_literals_at(scopes, m.group(3), m.start())
                    if not lits:
                        continue
                    for val in lits:
                        calls.append((m.group(1) or m.group(2), val, m.end(), True))
            calls.sort(key=lambda c: c[2])
            for cls_raw, meth, _pos, no_sig in calls:
                cls = cls_raw
                for _ in range(3):
                    cls = re.sub(r'\$\{?(\w+)\}?', lambda x: consts.get(x.group(1), x.group(0)), cls)
                # 裸标识符（`Xp.hook(CLS, "b", …)`）也要展开成真实类名：
                # 否则 `VipLimitProbe` 的 `b(...)` 目标在签名门禁里永远解析不到，
                # `VERIFICATION.md` 的「静态钩子」列只能显示 `-` —— 看着像没证据。
                if cls in consts:
                    cls = consts[cls]
                # `\$` → `$`：Kotlin 内部类的**唯一**正确写法，而 smali 里是不带反斜杠的。
                # 这一步漏掉时，下面 `'$' in cls` 那行会把**带内部类的目标整条丢掉** ——
                # `H5BridgeLog` 的 `HybridWebView$ReturnCallback.call`（全 APK 277 处调用点）
                # 因此从未被签名校验过，而门禁一直是绿的（2026-10-25 第 14 轮）。
                # ④ 的 `expand()` 与 `expand_all()` 都做了同一件事，这里原本只做了后者的等价物
                # —— 因为 `HOOK_RE` 抓到的是**原始**字面量，绕过了 `expand_all`。
                cls = cls.replace('\\$', '$')
                if not cls:
                    continue
                if '$' in cls and not re.fullmatch(r'[\w.$]+', cls):
                    continue                # 模板没展开完（`$PKG…`）：留给 ④ 报 MISSING
                if cls in DYNAMIC_CLASS_VARS:
                    # 运行时才知道的类名（`val name = cb.javaClass.name` / 注入的 client 类）。
                    # 这类目标由 ①b 的 `AllRuntimeResolvedClassesExist` 用另一套方式守
                    # （它扫 `clazzOrNull` 字面量），不能在这里假装有静态目标。
                    continue
                lineno = text[:_pos].count('\n') + 1
                where = f'{os.path.basename(path)}:{lineno}'
                if no_sig:
                    # hookAll 命中所有重载 ⇒ 没有"签名对不对"的问题，只有"方法在不在"。
                    rows.append({'class': cls, 'method': meth, 'sig': None, 'where': where,
                                 'form': 'hookAll'})
                    continue
                rest = text[_pos:]
                tokens = split_args(rest)
                desc, ok = [], True
                n_unknown = 0
                for tok in tokens:
                    if tok.startswith(STOP_TOKENS) or tok.startswith(CALLBACK_TOKEN_PREFIX):
                        break
                    name = tok.split('=')[0].strip()
                    if not name:
                        break
                    if name in WANTED:
                        desc.append(WANTED[name])
                    elif name.endswith('::class.java') or name.endswith('::class.javaPrimitiveType'):
                        # 简单名必须先过 import 表 / 隐式表，否则 `HashMap::class.java`
                        # 会变成 `LHashMap;` —— 门禁自己造出来的假红。
                        raw = name.split('::class.java')[0]
                        if '.' not in raw:
                            raw = imports.get(raw) or IMPLICIT_JAVA.get(raw, raw)
                        desc.append(to_desc(raw))
                    elif CLAZZ_INLINE_RE.match(name):
                        lit = expand_all(CLAZZ_INLINE_RE.match(name).group(1), consts)
                        desc.append(to_desc(lit))
                    elif name in clazz_vals:
                        desc.append(to_desc(clazz_vals[name]))
                    elif name in classref_vals:
                        ref = classref_vals[name]
                        desc.append(WANTED.get(ref) or to_desc(ref[:-len('::class.java')]))
                    else:
                        # 变量 / 常量 / 三元表达式：静态不定。
                        #
                        # **不再整条丢弃**（原先是 `ok = False; break`）。
                        # 那会让一个未知形参毁掉整条校验：例如 `PageRequestLog` 的
                        # `dr.f.a` 首参是 `dr.f$e`（运行时解析的变量），于是 7 个形参
                        # 一个都没校验，⑤ 报 UNKNOWN —— 而它其实有 6 个形参是字面量、
                        # 完全可以校验。
                        #
                        # 改成用 `*` 占位：签名变成 `(*Ljava/lang/String;…)`，
                        # 与真实签名逐位比对时 `*` 匹配任意一项。这样**已知部分仍然受检**。
                        desc.append('*')      # 占位：比对时匹配任意一项
                        n_unknown += 1
                        continue
                rows.append({
                    'class': cls, 'method': meth,
                    'sig': '(' + ''.join(desc) + ')' if (ok or n_unknown) else None,
                    'n_unknown': n_unknown,
                    'where': where,
                })
    # 去重（同一目标可能被模板/常量展开后重复出现）
    seen, uniq = set(), []
    for r in rows:
        k = (r['class'], r['method'], r['sig'], r['where'])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq



def sig_matches(wanted: str, variants) -> bool:
    """`wanted` 里可以含 `*` 通配（表示"这个形参静态不定"）。

    `*` 的语义要**按位置**匹配：它代表"一个形参"，不能一口气吃掉多个 ——
    否则 `(Ljava/lang/String;*)` 会匹配 `(Ljava/lang/String;IJ)V`，
    那样"少写两个参数"这种真错误就被放过了。

    例外：**全是 `*`** 的情况（`(*)` 或 `(*;*)`…）。全未知等于"我什么都没读到"，
    这时不能断言不匹配 —— 那会把"解析失败"误报成"签名错了"。
    这种情况按"无法判定"处理（返回 True 但调用方要区分，见下面的 status）。
    """
    if wanted in variants:
        return True
    if '*' not in wanted:
        return False
    if set(wanted) <= set('(*);[]/*'):
        # 全是占位符，没有任何已知形参 —— 不做断言
        return True
    # 有已知部分：逐个形参位置比对（* 只吃一个）
    def split(desc: str):
        out, i = [], 1          # 跳过 '('
        while i < len(desc) - 1:
            if desc[i] == '[':
                j = i
                while desc[j] == '[':
                    j += 1
                if desc[j] == 'L':
                    j = desc.index(';', j) + 1
                elif desc[j] == '*':
                    j += 1
                else:
                    j += 1
                out.append(desc[i:j]); i = j
            elif desc[i] == 'L':
                j = desc.index(';', i) + 1
                out.append(desc[i:j]); i = j
            else:
                out.append(desc[i]); i += 1
        return out

    want = split(wanted)
    for v in variants:
        got = split(v)
        if len(want) != len(got):
            continue
        if all(w == '*' or w == g for w, g in zip(want, got)):
            return True
    return False


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--smali', default=repo_path('work/apktool_out'))
    ap.add_argument('--module', default=repo_path('module/app/src/main/java/dev/xalor/kdkit'))
    ap.add_argument('--json', default=None)
    ap.add_argument('--strict', action='store_true', help='UNKNOWN 也算失败')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv[1:])

    idx = index_classes(a.smali)
    rows = collect(a.module)
    bad = unknown = 0
    out = []
    for r in rows:
        path = idx.get(r['class'])
        if path is None:
            status = 'OK(platform)' if re.match(r'^(android|java|javax)\.', r['class']) else 'MISSING-CLASS'
        elif r['method'] not in descriptors(path):
            status = 'MISSING-METHOD'
        elif r['method'] == '<init>':
            # Xp.hookCtor 已正确走 findAndHookConstructor ⇒ 这里可以真正比对参数
            if r['sig'] is None:
                status = 'UNKNOWN(constructor signature not statically resolvable)'
            else:
                variants = descriptors(path)['<init>']
                if sig_matches(r['sig'], variants):
                    # 同主分支：`(*)` 匹配任何参数个数 ⇒ 没受检，标 opaque。
                    inner = r['sig'][1:-1]
                    status = 'OK(opaque)' if ('*' in inner and inner.strip('*') == '') else 'OK'
                else:
                    status = 'SIGNATURE-MISMATCH'
                if status == 'SIGNATURE-MISMATCH':
                    r['actual'] = sorted(variants)
        elif r.get('form') == 'hookAll':
            # hookAll 钩的是**全部重载**，没有"形参对不上"的可能 ⇒ 方法存在即算过。
            # 这比 `UNKNOWN` 更强：它不是"没法判定"，而是"这条调用形态无需判定形参"。
            status = 'OK(hookAll)'
        elif r['sig'] is None:
            status = 'UNKNOWN(signature not statically resolvable)'
            # 无法静态推出时，把 APK 里的真实签名附上 —— 把"需要人工核对"变成"可以直接核对"。
            r['actual'] = sorted(descriptors(path)[r['method']])
        else:
            variants = descriptors(path)[r['method']]
            if sig_matches(r['sig'], variants):
                # **全是占位符的签名不算"校验通过"**：`(*)` 匹配任何参数个数，
                # 等于这条钩子没受检。把它单独标成 `OK(opaque)`，
                # 否则"62 条 OK"里混着几条什么都比对的，数字会虚高。
                # 只有「含 `*` 且除占位符外一个形参都没有」才是 opaque。
                # **零参数 `()` 是真正校验过的**（没有形参可错），不能算 opaque ——
                # 第一版判据把 `lk.a.k()` 也标成 opaque，18 条里大部分是这种误判。
                inner = r['sig'][1:-1]
                status = 'OK(opaque)' if ('*' in inner and inner.strip('*') == '') else 'OK'
            else:
                status = 'SIGNATURE-MISMATCH'
            if status == 'SIGNATURE-MISMATCH':
                r['actual'] = sorted(variants)
        if status.startswith('SIGNATURE-MISMATCH') or status.startswith('MISSING'):
            bad += 1
        if status.startswith('UNKNOWN'):
            unknown += 1
        out.append({**r, 'status': status})
        if not a.quiet:
            print(f'  {status:45s} {r["class"]}.{r["method"]}{r["sig"] or ""}   ({r["where"]})')
            if status.startswith('SIGNATURE-MISMATCH'):
                print(f'  {"":45s} APK 里实际是: {", ".join(r.get("actual", []))}')
            elif status.startswith('UNKNOWN') and r.get('actual'):
                # 这句以前写的是"← 人工确认代码传的类型与之一致"，读起来像"还没人验过"。
                # 实际上 `test_smali_usage.py` 里已有源码↔APK 的交叉校验
                # （`DynamicParamCrossCheck` / `SignatureCrossCheck`），是自动断言的。
                print(f'  {"":45s} APK 里实际是: {", ".join(r["actual"])}'
                      f'  ← 交叉校验见 test_smali_usage.py')

    total = len(out)
    judged = total - unknown
    print(f'[sig] {total} hooks: {judged - bad} 签名吻合 / {bad} 不符 / {unknown} 无法静态判定')
    if a.json:
        json.dump(out, open(a.json, 'w'), indent=2, ensure_ascii=False)
        print(f'[sig] report -> {a.json}')
    if bad:
        return 1
    if a.strict and unknown:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
