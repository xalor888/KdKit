#!/usr/bin/env python3
"""
kuaidui-kit / check_hook_result_types.py — "在 before 钩里直接写 `param.result`" 的那些目标，
**返回值类型必须与被写入的值相容**。

### 为什么需要这条门禁

Xposed 的 `param.result = X` 语义是"跳过原方法实现，用 X 当返回值"。所以：

* 目标方法 `V`（void）⇒ 写什么都行（返回值被丢弃），常见写法是 `result = null`；
* 目标方法 `Z`（boolean）⇒ 必须写 boolean，写 `null` 会在返回时拆箱 NPE；
* 目标方法有其它返回值 ⇒ 写不匹配的类型，调用方拿到错值或直接崩。

这类错误的**症状与功能本身毫无关系**（宿主在别处崩），是最难查的一类。
而 `hookAll` 会钩**同名全部重载**，所以判据是"每一个重载都相容"，不是"至少一个"。

### 现状

| feature | 类 | 方法 | 写的值 | 期望返回 |
|---|---|---|---|---|
| `bridge_guard` | `…HybridWebView` | `dispatchAction`, `dispatchActionToListeners` | `null`（跳过实现） | 全部 `V` |
| `anti_detect` | `dj/f` | `a`, `d` | `false` | 全部 `Z` |

两个功能在 **7.9.0 上都是相容的**。这条门禁的价值在**下个版本**：
R8 重排经常顺手改签名，那时这里会立刻变红，而不是等宿主随机崩溃。

    python3 kit/scripts/check_hook_result_types.py
退出码：0 = 全部相容；1 = 有不相容的重载 / 找不到类。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APK = os.path.join(ROOT, 'work', 'apktool_out')

#: (功能, smali 类路径, {方法名: (回调写的是什么, 允许的返回描述符)})
#:
#: 覆盖 2026-11-02 全仓扫描出的**所有**会写 `param.result` 的模块侧钩点（12 个方法）。
#: `android.os.Debug#isDebuggerConnected` 不在表里：它是**框架类**（`cl = null`），
#: 不在 APK 的解码树里，无从静态校验 —— 但它签名稳定（`()Z`），且写的是 `false`。
SPECS = [
    ('bridge_guard', 'com/baidu/homework/common/ui/widget/HybridWebView', {
        'dispatchAction': ('null（跳过原实现）', {'V'}),
        'dispatchActionToListeners': ('null（跳过原实现）', {'V'}),
    }),
    ('anti_detect', 'dj/f', {
        'a': ('false', {'Z'}),
        'd': ('false', {'Z'}),
        'c': ('false', {'Z'}),
    }),
    ('rm_splash', 'dj/a', {
        'j': ('null', {'V'}),
        'k': ('false', {'Z'}),
        'g': ('false', {'Z'}),
    }),
    ('rm_adconfig', 'di/a', {
        # 返回的是 `InitAdConfig$ListItem$AdlistItem`；写 null 的语义是"这个宿位没有配置"
        'd': ('null（无配置）', {'L', 'V'}),
        'j': ('false', {'Z'}),
    }),
    ('vip_unlock', 'aj/a', {
        'p': ('true', {'Z'}),
        'n': ('true', {'Z'}),
    }),
    ('skip_update', 'hh/y', {
        'L': ('null', {'V'}),
    }),
    ('web_picture_watermark',
     'com/kuaiduizuoye/scan/activity/common/CommonWebPictureBrowseActivity', {
         'o2': ('原图 Bitmap', {'L'}),
     }),
]

METHOD_RE = re.compile(
    r'^\.method\s+(?P<flags>[^\n(]*?)(?P<name>[A-Za-z_$][\w$]*)\('
    r'(?P<params>[^)]*)\)(?P<ret>\S+)', re.M)


def smali_dirs():
    if not os.path.isdir(APK):
        return []
    return [d for d in sorted(os.listdir(APK))
            if d == 'smali' or re.fullmatch(r'smali_classes\d+', d)]


def find_class(class_path):
    for d in smali_dirs():
        p = os.path.join(APK, d, class_path + '.smali')
        if os.path.isfile(p):
            return p
    return None


def main(argv):
    if not os.path.isdir(APK):
        print('[result-types] SKIP：work/apktool_out 不存在（未解码 APK）')
        return 0

    problems, total = [], 0
    for feature, cls, methods in SPECS:
        path = find_class(cls)
        if not path:
            problems.append((feature, cls, f'找不到类 `{cls}` —— 类名漂移，不是"没解码"', None))
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            src = f.read()
        print(f'[{feature}] {cls}')
        for name, (writes, allowed) in methods.items():
            # `hookAll` 会钩同名**全部重载**，所以逐个重载校验
            hits = [(m.group('params'), m.group('ret'))
                    for m in METHOD_RE.finditer(src) if m.group('name') == name]
            if not hits:
                problems.append((feature, cls, f'里找不到 `{name}` —— 方法名漂移', None))
                continue
            for params, ret in hits:
                total += 1
                # `L…;` 这类"对象"统一按 `L` 归类：判据是"写 null / 写对象"是否说得通
                kind = ret if len(ret) == 1 else ('L' if ret.startswith(('L', '[')) else ret)
                mark = 'ok ' if kind in allowed else 'BAD'
                print(f'  {mark} {ret[:28]:28s} {name}({params[:40]})  写 `{writes}`')
                if kind not in allowed:
                    problems.append((feature, cls,
                                     f'{name}({params[:40]}) 返回 `{ret}`，但回调写的是 `{writes}`', ret))

    if problems:
        print(f'\n[result-types] **{len(problems)} 处不相容** —— '
              '`param.result` 的类型与目标方法返回值不匹配，调用方会拿到错值或崩溃：')
        for feature, cls, why, _ in problems:
            print(f'  {feature} @ {cls}: {why}')
        print('  处置：要么改成 after 钩 + 返回合适的默认值，要么把这个目标移出该功能的钩子清单。')
        return 1

    print(f'[result-types] {total} 个重载全部相容 ✓')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
