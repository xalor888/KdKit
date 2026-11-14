#!/usr/bin/env python3
"""功能表一致性门禁：`FeatureRegistry.kt` ↔ `module/README.md`。

为什么需要：模块的功能数是 25，但 README 曾长期停在 17 —— 代码加功能不会自动改文档，
交付出去就是"文档说的和跑的不是一回事"。本脚本把这份漂移变成**构建前可失败的检查**。

检查三件事：
  1. `FeatureRegistry.all` 里的每个对象都能在源码里找到（没有引用了不存在的类）；
  2. 每个对象的 `id` 唯一且非空；
  3. README 功能表的 id 集合与注册表**完全相等**（新增/删除都必须同步）。

用法：
  python3 module/scripts/check_feature_parity.py
  python3 module/scripts/check_feature_parity.py --module-dir ../baicizhan-kit/module

BCZKit 可直接复制本脚本：它只依赖目录结构与 README 表格格式，不依赖包名。
"""

# DOC-REALITY: FeatureRegistry.kt ↔ module/README.md 功能表 ↔ ACTIVITY.md/VERIFICATION.md
# （这一行是给 `check_doc_reality.py` 扫的登记标记 —— 新增"文档 ↔ 代码"断言时
#  必须加这一行，否则清单会漏掉它，R40 门禁表漂 8 道那类事就会重演。）
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def find_matching(text: str, open_index: int, open_char: str = "(", close_char: str = ")") -> int:
    depth = 0
    i = open_index
    while i < len(text):
        ch = text[i]
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return i
        elif ch in ('"', "'"):
            quote = ch
            i += 1
            while i < len(text) and text[i] != quote:
                if text[i] == "\\":
                    i += 1
                i += 1
        i += 1
    raise ValueError(f"括号未闭合（起点 {open_index}）")


def parse_registry_objects(registry_path: Path) -> list[str]:
    text = registry_path.read_text(encoding="utf-8")
    m = re.search(r"val\s+all\s*:\s*List<BaseFeature>\s*=\s*listOf\s*\(", text)
    if not m:
        raise SystemExit(f"✗ 找不到 `val all: List<BaseFeature> = listOf(`：{registry_path}")
    start = m.end() - 1
    end = find_matching(text, start)
    block = text[start + 1 : end]
    # 去掉行注释后再取裸标识符
    block = re.sub(r"//[^\n]*", "", block)
    names = [line.strip().rstrip(",") for line in block.splitlines()]
    return [n for n in names if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", n)]


def parse_feature_ids(sources: dict[str, str]) -> dict[str, tuple[str, str]]:
    """object 名 -> (id, 文件)。只解析 `object X : SwitchFeature|BaseFeature(...)`。"""
    result: dict[str, tuple[str, str]] = {}
    for path, text in sources.items():
        for m in re.finditer(r"\bobject\s+([A-Z][A-Za-z0-9_]*)\s*:\s*(?:SwitchFeature|BaseFeature)\s*\(", text):
            name = m.group(1)
            start = m.end() - 1
            end = find_matching(text, start)
            args = text[start + 1 : end]
            idm = re.search(r'\bid\s*=\s*"((?:[^"\\]|\\.)*)"', args, re.S)
            if not idm:
                continue
            result[name] = (idm.group(1), path)
    return result


#: 功能表的一行：`| `id` | 名称 | 类别 | 默认 | 实现要点 | 热 | 选项 |`
README_ROW_RE = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|")


def readme_feature_rows(readme_path: Path) -> list[tuple[int, str, str]]:
    """返回功能表里**连续**那一段的 `(行号, id, 原始行)`，按文件顺序。

    为什么必须"连续"，而不是"全文匹配所有 `| \\`id\\` |` 行"（旧实现）：

    旧实现把命中的行灌进 `set`，于是**两种真实缺陷同时隐身**（2026-10-26 实测）：

    1. **表格被空行切断。** README 第 137 行曾有一个空行，把功能表劈成两半。
       Markdown 里后半段**没有表头**，渲染出来是一堆裸竖线；而 `check_readme_columns`
       走到空行就 `header_seen = False` 收工 ⇒ 后半段 6 行（`bridge_action_log` /
       `skip_update` / `vip_limit_probe` / `vip_unlock` / `watermark_off` /
       `web_picture_watermark`）的「热」「选项」两列**从未被校验过**。
       反向验证：把 `vip_unlock` 的热列从 `是` 改成 `否`（代码里 `hot = true`），
       门禁仍然全绿。

    2. **同一个功能登记两次。** 同一个空行之后，`web_picture_watermark` 又出现了一遍
       —— 物理 **36** 行、唯一 **35** 个 id。`set` 把重复吃掉，摘要照样打印
       "README 35 行"：**数字在说谎，而且是往"没问题"的方向说。

    两处都不是排版洁癖：功能表是读者对这个模块的第一印象，也是第 ③ 道门的比对对象。
    一张会被切断、会重复登记的表，让"新增功能必须同步文档"这条不变量失去意义。

    所以这里取**表头之后连续的非空 `|` 行**，由调用方逐个校验并查重；
    空行之后若还有功能行，`check_readme_columns` 会显式报"表格被切开了"。
    """
    lines = readme_path.read_text(encoding="utf-8").splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("| id |") and "热" in line:
            start = i
            break
    if start is None:
        return []
    rows: list[tuple[int, str, str]] = []
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if not line.startswith("|"):     # 空行 / 段落 / 下一个标题都算表尾
            break
        if set(line) <= set("|-: "):     # `|---|---|` 分隔行
            continue
        m = README_ROW_RE.match(line)
        if m:
            rows.append((i + 1, m.group(1), line))
    return rows


def parse_readme_ids(readme_path: Path) -> set[str]:
    """只认**功能表**里的 id —— 在别处偶然提一句不算登记。"""
    return {fid for _lineno, fid, _line in readme_feature_rows(readme_path)}


def stray_feature_rows(readme_path: Path) -> list[tuple[int, str]]:
    """功能表**之外**还出现的 `| \\`id\\` |` 行 —— 表格被切断的证据。"""
    inside = {lineno for lineno, _fid, _line in readme_feature_rows(readme_path)}
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(readme_path.read_text(encoding="utf-8").splitlines(), 1):
        if lineno in inside:
            continue
        m = README_ROW_RE.match(line.strip())
        if m:
            out.append((lineno, m.group(1)))
    return out




# ─────────────────────────────── 幽灵键门禁（2026-10-25 加） ───────────────────────────────
#
# 由来：模块里曾有 7 个键是"代码在读、界面写不了、schema 里不存在"的状态 ——
# `pk_mock` / `pk_auto_answer` / `bridge_guard_probe_remove_loading` /
# `native_exit_guard_control` / `page_js_script` / `native_probe_capture` / ...。
# 它们只能靠改 prefs 或 kit 脚本设置，用户永远看不到；而反过来的错误（schema 声明了、
# 代码里没人读）会让设置页出现一个拨了没反应的开关 —— 两种都是"文档说的和跑的不是一回事"。
#
# 本检查把两边对齐：
#   ① 代码里 `KdConfig.isOn("x")` / `KdConfig.getString("x")` 读的每个键，
#      必须是某个 feature 的 id 或它声明的 `KdOption.key`；
#   ② 每个 `KdOption.key` 必须真的被代码读过（否则是死选项）。

READ_KEY_RE = re.compile(r'KdConfig\.(?:isOn|getString)\(\s*"([a-z0-9_]+)"')
# 同一个文件里用常量形式的读取（`KdConfig.getString(KEY_LIST, ...)`）也要算 —— 否则
# BridgeGuard 的三个 key 会被误报成"没人读"。常量在文件内解析（const val 与 object 内 const val）。
READ_KEY_CONST_RE = re.compile(r'KdConfig\.(?:isOn|getString)\(\s*([A-Za-z_][A-Za-z0-9_]*)')
OPTION_KEY_RE = re.compile(r'KdOption\(\s*\n?\s*key\s*=\s*"([a-z0-9_]+)"')
OPTION_CONST_RE = re.compile(r'KdOption\(\s*\n?\s*key\s*=\s*([A-Za-z_][\w.]*)\s*,')


def global_consts(sources: dict[str, str]) -> dict[str, str]:
    """所有文件里的 `const val X = "..."`（含 object/companion 内的），按短名合并。

    跨文件常量引用（`KdOption(key = CaptureSettings.KEY_MAX_MB)`）只有这样才解析得出来。
    同名常量取先出现者 —— schema 里的 key 本来就该全局唯一，重名会在别处被门禁抓到。
    """
    out: dict[str, str] = {}
    for _path, text in sources.items():
        for name, value in consts_in(text).items():
            out.setdefault(name, value)
    return out


def collect_keys(sources: dict[str, str], meta: dict[str, tuple[str, str]]) -> tuple[set, set, dict]:
    """返回 (代码读取的键, schema 声明的键, 每个键的出处)。"""
    read: dict[str, str] = {}
    declared: dict[str, str] = {}
    allc = global_consts(sources)
    for path, text in sources.items():
        for m in READ_KEY_RE.finditer(text):
            read.setdefault(m.group(1), f"{Path(path).name}:{text[:m.start()].count(chr(10)) + 1}")
        consts = consts_in(text)
        for m in READ_KEY_CONST_RE.finditer(text):
            name = m.group(1)
            if name in consts:
                read.setdefault(consts[name], f"{Path(path).name}:{text[:m.start()].count(chr(10)) + 1}")
        for m in OPTION_KEY_RE.finditer(text):
            declared.setdefault(m.group(1), f"{Path(path).name}")
        for m in OPTION_CONST_RE.finditer(text):
            name = m.group(1).split('.')[-1]
            if name in consts:
                declared.setdefault(consts[name], f"{Path(path).name} ({m.group(1)})")
            elif name in allc:
                declared.setdefault(allc[name], f"{Path(path).name} ({m.group(1)})")
    return set(read), set(declared), {"read": read, "declared": declared}


def consts_in(text: str) -> dict[str, str]:
    raw = dict(re.findall(r'const val (\w+)\s*=\s*"([^"]*)"', text))
    out = {}
    for k, v in raw.items():
        for _ in range(3):
            v = re.sub(r'\$\{?(\w+)\}?', lambda m: raw.get(m.group(1), m.group(0)), v)
        out[k] = v
    return out


HOT_RE = re.compile(r'\bhot\s*=\s*true\b')
DEFAULT_ON_RE = re.compile(r'\bdefaultOn\s*=\s*(true|false)\b')


def feature_attrs(sources: dict[str, str]) -> dict[str, dict]:
    """每个 feature object 的 `hot` / `defaultOn` / 声明了哪些 KdOption key。"""
    out: dict[str, dict] = {}
    allc = global_consts(sources)
    for path, text in sources.items():
        consts = consts_in(text)
        for m in re.finditer(r'\bobject\s+([A-Z][A-Za-z0-9_]*)\s*:\s*(?:SwitchFeature|BaseFeature)\s*\(', text):
            start = m.end() - 1
            end = find_matching(text, start)
            args = text[start + 1:end]
            idm = re.search(r'\bid\s*=\s*"([^"]+)"', args)
            if not idm:
                continue
            # 该 object 的整个作用域（含 override val options）
            obj_end = text.find('\nobject ', end + 1)
            scope = text[start:obj_end if obj_end > 0 else len(text)]
            keys = [k for k in re.findall(r'KdOption\(\s*\n?\s*key\s*=\s*"([a-z0-9_]+)"', scope)]
            for cm in OPTION_CONST_RE.finditer(scope):
                nm = cm.group(1).split('.')[-1]
                if nm in consts:
                    keys.append(consts[nm])
                elif nm in allc:
                    keys.append(allc[nm])
            out[idm.group(1)] = {
                'name': m.group(1),
                'hot': bool(HOT_RE.search(args)),
                'default_on': (DEFAULT_ON_RE.search(args).group(1) == 'true') if DEFAULT_ON_RE.search(args) else True,
                'options': keys,
            }
    return out


def check_readme_columns(module_dir: Path, readme_path: Path, attrs: dict[str, dict]) -> list[str]:
    """README 的「热」「选项」两列必须与代码一致 —— 否则文档会再次变成"说的和跑的不是一回事"。

    这里**不再**用 `header_seen` 走状态机（见 `readme_feature_rows` 的两条实测缺陷），
    而是先取出连续那段功能表，再逐行比对；表格之外的同形行单独报错。
    行数、唯一性也在这里管：**同一个 id 出现两次，与写了一行错的内容一样是漂移**。
    """
    errors: list[str] = []
    rows = readme_feature_rows(readme_path)

    strays = stray_feature_rows(readme_path)
    if strays:
        shown = ', '.join(f'第 {n} 行 `{fid}`' for n, fid in strays[:6])
        errors.append(
            f'README 功能表被切开了：表外还有 {len(strays)} 行同形功能行（{shown} …）。'
            '表格中间不能有空行 —— 后半段没有表头，渲染成裸竖线')

    # 表格之外的同形行**照样逐列校验**：只报"被切开了"会让操作者以为把空行删掉就完事，
    # 而那些行里的错误内容（热列写反、选项多写）在删空行之前就一直没人看得见。
    # 一次跑就把两件事都说出来，比修一处、再跑一次才发现下一处要省事。
    all_rows = list(rows)
    if strays:
        lines = readme_path.read_text(encoding='utf-8').splitlines()
        all_rows += [(n, fid, lines[n - 1]) for n, fid in strays]

    seen: dict[str, int] = {}
    for lineno, fid, line in all_rows:
        if fid in seen:
            errors.append(f'README `{fid}` 登记了两次（第 {seen[fid]} 行与第 {lineno} 行）'
                          f'—— 两边内容不一致时读者不知道该信哪一行')
            continue
        seen[fid] = lineno
        if fid not in attrs:
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) < 7:
            errors.append(f'README 第 {lineno} 行（`{fid}`）列数不足 7：{len(cells)}')
            continue
        hot_cell = cells[5]
        opt_cell = cells[6]
        a = attrs[fid]
        if a['hot'] and hot_cell != '是':
            errors.append(f'README `{fid}` 标的热={hot_cell!r}，但代码里 hot = true')
        if not a['hot'] and hot_cell == '是':
            errors.append(f'README `{fid}` 标热=是，但代码里是冷开关（没有 hot = true）')
        declared = set(a['options'])
        shown = set(re.findall(r'`([a-z0-9_]+)`', opt_cell))
        if declared - shown:
            errors.append(f'README `{fid}` 选项列缺：{", ".join(sorted(declared - shown))}')
        if shown - declared:
            errors.append(f'README `{fid}` 选项列多了（代码里没声明）：{", ".join(sorted(shown - declared))}')
    return errors


def check_activity_doc(module_dir: Path, attrs: dict[str, dict]) -> list[str]:
    """`ACTIVITY.md` 的**前缀对照表**必须覆盖每个 feature id。

    为什么把它做成门禁：这张表是"日志里看到某个前缀属于哪个功能"的唯一对照。
    新增功能却忘了登记，后果是**报告脚本统计不到它**（计数恒为 0），
    而 0 会被读成"功能没生效"—— 正是这个项目反复踩的那种假红。

    2026-10-25 第 11 轮收紧：旧判据是 `f'`{fid}`' in text`，**全文任意位置提到一次就算通过**。
    于是 §一 的"计数为 0"表里出现一次 `vip_unlock`，§七 对照表完全不写它也算绿 ——
    而 §一 是生成器自动产出的（来自 `FEATURES_WITH_CAPTURE`），根本不需要人去维护。
    真正需要人维护的是 §七（新增功能必须写"写什么前缀 / 落盘到哪 / 限流多少"）。

    新判据：必须出现在 §七 的**表格行**里（`| `fid` |` 开头）。
    """
    doc = module_dir / 'ACTIVITY.md'
    if not doc.exists():
        return []
    text = doc.read_text(encoding='utf-8')
    # 只看 `## 七、` 之后的部分：那是手写的功能↔前缀对照表。
    idx = text.find('\n## 七、')
    if idx < 0:
        return ['ACTIVITY.md 找不到 `## 七、` 小节（功能 ↔ 抓取前缀对照表）—— '
                '它是新增功能必须登记的地方']
    section = text[idx:]
    rows = set()
    for line in section.splitlines():
        m = re.match(r'^\|\s*(?:\*\*)?`([a-z0-9_]+)`(?:\*\*)?\s*\|', line)
        if m:
            rows.add(m.group(1))
    missing = [fid for fid in attrs if fid not in rows]
    if missing:
        return ['ACTIVITY.md §七 的功能↔前缀对照表缺少这些功能（报告脚本会统计不到它们，'
                '计数恒为 0 又会被误读成"功能没生效"）：'
                + ', '.join(f'`{m}`' for m in sorted(missing))]
    return []


def check_declared_counts(module_dir: Path, root_dir: Path, total: int, hot: int) -> list[str]:
    """文档里写的"共 N 个功能 / N 个热开关"必须等于代码里的真实数量。

    为什么做成门禁：功能数是读者对这个模块的第一印象，也是最容易过期的数字。
    2026-10-25 就出现过：实际 29 个，`README.md` 与 `OPTIMIZATION.md` 还写 28。

    ## 这条门禁自己被"看起来是绿的"骗过三次

    每次都是**同一种失效**：不是判错了，而是**有些写法它根本不看**。
    收窄的正则 = 那一整类声明不受保护，而且没有任何信号。已修的三类：

      | 次 | 漏掉的形态 | 当时实际 |
      |---|---|---|
      | 1 | `**N 个热开关**`（无斜杠） | 写 32，实际 33 |
      | 2 | `（N 个热开关）`（括号） | 又一次过期 |
      | 3 | `**N 功能**`（无「个」）、`模块有 N 个功能`、`N 个功能逐行` | 3 处同时过期 |

    第 3 次同时暴露了**文件清单**也是盲区：`module/PARADIGM.md` 从来没被扫过，
    所以它那句"模块有 34 个功能"在加到第 36 个功能后一直没人管。

    ## 为什么不能"凡是 N 个功能都等于总数"

    本仓库有大量**合法**的非总数用法：
      * `这 12 个功能改变行为`（ACTIVITY §二 —— 12 是"只写 logcat"的子集数）
      * `下面 10 个功能钩的是广告视图`（ACTIVITY §七之二 —— 子集）
      * `AdFeatures.kt 的 7 个功能`（PARADIGM —— 单文件）
      * `第 29 个功能 watermark_off`（OPTIMIZATION —— **序数**，不是计数）

    一刀切会让这四类全红，而它们本来就对。**喊狼来了的门禁会被关掉。**
    所以这里只认"声称模块总数"的句式；子集/单文件/序数一律不碰 ——
    宁可少管，不可乱红。序数用 `(?<!第)` 排除。
    """
    errors: list[str] = []
    pats = [
        (re.compile(r'共\s*\*\*(\d+)\s*个功能\*\*'), '共 **N 个功能**'),
        # `**N 个功能**`；`(?<!第)` 让"第 **N** 个功能"这类序数不被当计数。
        (re.compile(r'(?<!第)\*\*(\d+)\s*个功能\*\*'), '**N 个功能**'),
        # `**N 功能**`（无「个」）—— 根 README 的状态节用这个简写。
        (re.compile(r'共?\s*\*\*(\d+)\s*功能\*\*'), '**N 功能**'),
        # `模块有 N 个功能` / `本模块 N 个功能` / `模块共 N 个功能`。
        # 只在"模块"作主语时算总数声明；`AdFeatures.kt 的 7 个功能` 不含"模块"，不匹配。
        (re.compile(r'(?:本)?模块(?:有|共|包含|计)?\s*\*{0,2}(\d+)\s*个功能'),
         '模块（有）N 个功能'),
        # `N 个功能逐行给出` —— VERIFICATION 矩阵行数的声明。
        (re.compile(r'(?<!第)(\d+)\s*个功能逐行'), 'N 个功能逐行给出'),
        (re.compile(r'一致（(\d+)\s*项）'), '一致（N 项）'),
        (re.compile(r'(\d+)\s*项一致'), 'N 项一致'),
    ]
    hot_pat = re.compile(
        r'\*\*(\d+)/(\d+) 个功能是热开关\*\*|(\d+)/(\d+) 个功能是热开关'
        # `**N 个热开关**` —— 根 `README.md` 用的就是这个简写形态。
        # 2026-10-25 抓到：它写着 "34 个功能、32 个热开关"（实际 33），
        # 而上面的正则只认 `N/M 个功能是热开关`，于是这个数字长期没人校验。
        r'|\*\*(\d+) 个热开关\*\*|(?<![\d/])(\d+) 个热开关(?![\d/])'
        # `（N 个热开关）` 括号形态 —— 根 README 的"状态"节用这个写法。
        # 2026-10-26 抓到：它写着"35 功能（33 个热开关）"，而上面两种形态都匹配不到
        # 括号前的数字，于是又一次长期过期。（这是同类问题的第二次。）
        r'|（(\d+) 个热开关）')
    # 文件清单本身也是盲区：`module/PARADIGM.md` 此前从未被扫过（第 3 次失效的原因之一）。
    for rel in ('README.md', 'module/README.md', 'module/OPTIMIZATION.md',
                'module/PARADIGM.md', 'module/ACTIVITY.md', 'module/VERIFICATION.md'):
        f = root_dir / rel
        if not f.exists():
            continue
        text = f.read_text(encoding='utf-8')
        # **反引号与直引号里的内容不算声明。** 那是在*引用*旧值
        # （"它曾经写着 `34 个功能`" / "本文件里那句「模块有 34 个功能」"），
        # 不是在*声称*当前值。不排除的话，一段记录历史的文字会让门禁自己变红 ——
        # 而那正是本轮修这个 bug 时真实发生的事：我把"当时文档写的 34"写进表格，
        # 门禁立刻把这句话当成新声明报了出来。
        #
        # 替换成等长空白，保持偏移不变（将来加行号时仍能对上）。
        def _mask_code(s: str) -> str:
            s = re.sub(r'```.*?```', lambda m: ' ' * len(m.group(0)), s, flags=re.S)
            s = re.sub(r'`[^`\n]*`', lambda m: ' ' * len(m.group(0)), s)
            # 直引号 / 书名号内的"引用语"。只处理**成对且不跨行**的情形，
            # 避免把"共 **36 个功能**"这种真声明（它在引号外）误伤。
            for lq, rq in (('"', '"'), ('“', '”'), ('「', '」'), ('『', '』')):
                s = re.sub(re.escape(lq) + r'[^' + re.escape(lq + rq) + r'\n]{0,120}?'
                           + re.escape(rq), lambda m: ' ' * len(m.group(0)), s)
            return s
        masked = _mask_code(text)
        for pat, human in pats:
            for m in pat.finditer(masked):
                n = int(m.group(1))
                if n != total:
                    errors.append(f'{rel}: 声明"{human}"→{n}，代码里实际 {total} 个功能')
        for m in hot_pat.finditer(masked):
            if m.group(1):                       # `N/M 个功能是热开关`
                a, b = int(m.group(1)), int(m.group(2))
            elif m.group(3):                     # 同上，无 ** 包裹
                a, b = int(m.group(3)), int(m.group(4))
            else:                                # `N 个热开关`（分母视为 total）
                a, b = int(m.group(5) or m.group(6) or m.group(7)), total
            if b != total or a != hot:
                errors.append(f'{rel}: 声明 "{a}/{b} 个功能是热开关"，'
                              f'代码里实际 {hot}/{total}')
    return errors


SUB_OPTION_ALLOWLIST = {
    # 由 kit 脚本写入 / 框架侧内部使用、不需要出现在设置页的键（仍必须有 schema 声明）
    "page_js_script",
}


def check_verification_doc(module_dir: Path, attrs: dict[str, dict]) -> list[str]:
    """`VERIFICATION.md` 必须一行不少地覆盖**每一个**功能，且必须带 `真机` 列。

    两件事都要检查，因为它们的失效方式不同：
      * 少一行 ⇒ 那个功能在"验证矩阵"里不存在，读者会以为它已被证明；
      * 缺 `真机` 列 ⇒ 读者会把"静态钩子全解析 + 编译通过"当成"设备上验过"。
        这一列的值只能是 `未验证` / `见本轮日志`，不许留空。

    **行数不写死。** 这段 docstring 曾经写"覆盖 28 个功能"，而实际早已 36 个 ——
    注释里的数字没有门禁会校验，所以它安静地过期了 8 个功能。
    断言用 `attrs`（注册表真实内容）比，不在文字里复述数量。
    """
    doc = module_dir / 'VERIFICATION.md'
    if not doc.exists():
        return []
    text = doc.read_text(encoding='utf-8')
    errors: list[str] = []
    missing = [fid for fid in attrs if f'`{fid}`' not in text]
    if missing:
        errors.append('VERIFICATION.md 缺少这些功能行：' + ', '.join(f'`{m}`' for m in sorted(missing)))
    header = next((ln for ln in text.splitlines() if ln.startswith('| feature |')), '')
    if '真机' not in header:
        errors.append('VERIFICATION.md 表头缺少 `真机` 列（不写这一列会让静态结论被读成已验证）')
    if '验证等级' not in header:
        errors.append('VERIFICATION.md 表头缺少 `验证等级` 列')
    # 列下标从**表头**算出来，不写死 `cells[8]`。
    # 写死下标的失效方式很隐蔽：插一列之后，这段代码会认真地去校验**另一列**，
    # 而且照样返回空错误列表 —— 与 OPTIMIZATION §40"结论依赖于目标在列表里的位置"同源。
    cols = [c.strip() for c in header.strip().strip('|').split('|')] if header else []
    real_idx = cols.index('真机') if '真机' in cols else None
    if real_idx is None:
        return errors
    for ln in text.splitlines():
        if not ln.startswith('| `'):
            continue
        cells = [c.strip() for c in ln.strip().strip('|').split('|')]
        if len(cells) > real_idx and cells[real_idx] == '':
            errors.append(f'VERIFICATION.md 有一行 `真机` 为空：{cells[0]}')
    return errors


def check_keys(module_dir: Path, sources: dict[str, str], meta: dict[str, tuple[str, str]]) -> list[str]:
    feature_ids = {fid for fid, _ in meta.values()}
    read, declared, origin = collect_keys(sources, meta)
    errors: list[str] = []

    known = feature_ids | declared | SUB_OPTION_ALLOWLIST
    ghosts = sorted(read - known)
    if ghosts:
        errors.append(
            "代码读取了没人声明的配置键（调用 KdConfig.isOn/getString 但既不是 feature id "
            "也没有 KdOption 声明）：" + ", ".join(f"`{g}`({origin['read'][g]})" for g in ghosts)
        )

    dead = sorted(declared - read)
    if dead:
        errors.append(
            "声明了但代码里没人读的子选项（设置页会出现拨了没反应的开关）："
            + ", ".join(f"`{d}`({origin['declared'][d]})" for d in dead)
        )

    return errors


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="FeatureRegistry ↔ README parity check")
    ap.add_argument("--module-dir", default=str(here.parent), help="模块根目录（含 app/src 与 README.md）")
    ap.add_argument("--readme", default=None, help="默认 <module-dir>/README.md")
    ap.add_argument("--no-keys", action="store_true", help="跳过幽灵键检查")
    args = ap.parse_args()

    module_dir = Path(args.module_dir).resolve()
    readme = Path(args.readme).resolve() if args.readme else module_dir / "README.md"
    registry = next(module_dir.glob("app/src/main/java/**/features/FeatureRegistry.kt"), None)

    if registry is None:
        print(f"✗ 找不到 FeatureRegistry.kt（在 {module_dir} 下）")
        return 1
    if not readme.exists():
        print(f"✗ 找不到 README：{readme}")
        return 1

    objects = parse_registry_objects(registry)
    sources = {
        str(p): p.read_text(encoding="utf-8")
        for p in (module_dir / "app/src/main/java").rglob("*.kt")
    }
    meta = parse_feature_ids(sources)

    errors: list[str] = []

    missing_objects = [o for o in objects if o not in meta]
    if missing_objects:
        errors.append(
            "注册表引用了源码里不存在的功能（或对象没写 `id = \"...\"`）：" + ", ".join(missing_objects)
        )

    ids: dict[str, str] = {}
    for name in objects:
        if name not in meta:
            continue
        fid, path = meta[name]
        if fid in ids:
            errors.append(f"功能 id 重复：`{fid}`（{name} 与 {ids[fid]}）")
        ids[fid] = name

    readme_ids = parse_readme_ids(readme)
    code_ids = set(ids)

    errors += check_keys(module_dir, sources, meta)
    attrs = feature_attrs(sources)
    errors += check_readme_columns(module_dir, readme, attrs)
    errors += check_activity_doc(module_dir, attrs)
    hot_n = sum(1 for a in attrs.values() if a['hot'])
    errors += check_declared_counts(module_dir, module_dir.parent, len(attrs), hot_n)
    errors += check_verification_doc(module_dir, attrs)

    missing_in_readme = sorted(code_ids - readme_ids)
    stale_in_readme = sorted(readme_ids - code_ids)
    if missing_in_readme:
        errors.append("README 功能表缺少这些 id：" + ", ".join(f"`{i}`" for i in missing_in_readme))
    if stale_in_readme:
        errors.append("README 功能表有代码里已不存在的 id：" + ", ".join(f"`{i}`" for i in stale_in_readme))

    # 摘要里同时给出**物理行数**与**唯一 id 数**：旧代码只打印 `len(readme_ids)`（一个 set）
    # 却把它标成"行"，于是物理 36 行 / 唯一 35 个 id 的那次重复登记被读成"35 行，正好"。
    # 一个数字只要可能不等于它自称的量，就会在出错时替错误说话。
    n_rows = len(readme_feature_rows(readme))
    print(f"注册表 {len(objects)} 个对象 / 代码 {len(code_ids)} 个唯一 id / "
          f"README {n_rows} 行（{len(readme_ids)} 个唯一 id）")
    if errors:
        for e in errors:
            print(f"✗ {e}")
        return 1

    print("✓ 功能表一致（FeatureRegistry ↔ README）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
