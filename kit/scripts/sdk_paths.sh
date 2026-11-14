#!/usr/bin/env bash
# kuaidui-kit / sdk_paths.sh — **Android SDK 路径的唯一来源**。
#
# 为什么需要：2026-11-03 代码审查 P2“macOS SDK 绝对路径 7 处”。
# 七个脚本各自写死 `$HOME/Library/Android/sdk`，于是：
#   * 换机器 / 用 ANDROID_HOME 装的人，七个地方都要改；
#   * 漏改一处的后果不是报错，而是**那条命令找不到 adb** ——
#     而错误信息是 `adb: command not found`，指向“你没装 SDK”，
#     与“你装在了别处”完全不像。
#
# 优先级：`ANDROID_HOME` → `ANDROID_SDK_ROOT` → `$HOME/Library/Android/sdk`。
# 用一个文件而不是环境变量约定：环境变量要在每个调用点记得 export，
# 而“记得”这件事今天已经出错很多次了。
#
#   source kit/scripts/sdk_paths.sh
#   echo "$SDK_ADB" "$SDK_EMU"

# **不要 set -e**：这是被 source 的片段，调用方的 shell 选项不该被它改掉。

sdk_root() {
  if [ -n "${ANDROID_HOME:-}" ]; then
    printf '%s\n' "$ANDROID_HOME"
  elif [ -n "${ANDROID_SDK_ROOT:-}" ]; then
    printf '%s\n' "$ANDROID_SDK_ROOT"
  else
    printf '%s\n' "$HOME/Library/Android/sdk"
  fi
}

SDK_ROOT="$(sdk_root)"
SDK_ADB="$SDK_ROOT/platform-tools/adb"
SDK_EMU="$SDK_ROOT/emulator/emulator"
export SDK_ROOT SDK_ADB SDK_EMU

# 把 platform-tools 与 emulator 放进 PATH —— 大多数脚本只想要 `adb` 这个名字。
case ":$PATH:" in
  *":$SDK_ROOT/platform-tools:"*) ;;
  *) export PATH="$SDK_ROOT/platform-tools:$SDK_ROOT/emulator:$PATH" ;;
esac
