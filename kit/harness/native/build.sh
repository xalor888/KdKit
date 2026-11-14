#!/usr/bin/env bash
# Build the native token-decode oracle for arm64 Android (runs on the emulator/device).
set -euo pipefail
NDK="${ANDROID_NDK:-$HOME/Library/Android/sdk/ndk/27.2.12479018}"
CC="$(ls "$NDK"/toolchains/llvm/prebuilt/*/bin/aarch64-linux-android21-clang | head -1)"
echo "[build] $CC"
"$CC" -O1 -Wall -o decode_token decode_token.c -ldl
file decode_token 2>/dev/null || true
ls -la decode_token
