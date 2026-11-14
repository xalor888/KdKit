#!/usr/bin/env bash
# Build libkdhide.so (arm64) and drop it into the module's jniLibs so the APK ships it.
set -euo pipefail
NDK="${ANDROID_NDK:-$HOME/Library/Android/sdk/ndk/27.2.12479018}"
CC="$(ls "$NDK"/toolchains/llvm/prebuilt/*/bin/aarch64-linux-android21-clang | head -1)"
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$(cd "$HERE/.." && pwd)/app/src/main/jniLibs/arm64-v8a"
mkdir -p "$OUT"
cd "$HERE"
"$CC" -O2 -fPIC -shared -Wall -o "$OUT/libkdhide.so" kdhide.c
ls -la "$OUT/libkdhide.so"
