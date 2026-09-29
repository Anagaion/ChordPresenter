#!/usr/bin/env bash
# Download, verify and trim the standalone Python that ships inside
# ChordPresenter.app, so users don't need Python installed.
#
#   scripts/build/bundle_python.sh            # both chips (for a universal build)
#   scripts/build/bundle_python.sh x86_64     # just one
#
# Source: https://github.com/astral-sh/python-build-standalone (release below).
# Output: src-tauri/python-runtime/<arch>/  (git-ignored; README.md stays tracked)
# Re-running is safe: downloads are cached in src-tauri/python-runtime/.cache.
set -euo pipefail

PY_VERSION="3.13.15"
PBS_RELEASE="20260924"
BASE="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}"

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$ROOT/src-tauri/python-runtime"
CACHE="$OUT/.cache"
if [ $# -eq 0 ]; then set -- aarch64 x86_64; fi

mkdir -p "$CACHE"
if [ ! -f "$CACHE/SHA256SUMS-$PBS_RELEASE" ]; then
  curl -fsSL -o "$CACHE/SHA256SUMS-$PBS_RELEASE" "$BASE/SHA256SUMS"
fi

for arch in "$@"; do
  file="cpython-${PY_VERSION}+${PBS_RELEASE}-${arch}-apple-darwin-install_only_stripped.tar.gz"
  if [ ! -f "$CACHE/$file" ]; then
    echo "Downloading $file"
    curl -fsSL -o "$CACHE/$file" "$BASE/$file"
  fi

  # Verify against the release's published checksum list — never ship an
  # unverified interpreter.
  expected="$(grep " ${file}\$" "$CACHE/SHA256SUMS-$PBS_RELEASE" | cut -d' ' -f1)"
  actual="$(shasum -a 256 "$CACHE/$file" | cut -d' ' -f1)"
  if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
    echo "Checksum mismatch for $file (expected '$expected', got '$actual')" >&2
    exit 1
  fi

  dest="$OUT/$arch"
  rm -rf "$dest"
  mkdir -p "$dest"
  tar -xzf "$CACHE/$file" -C "$dest" --strip-components 1   # archive root is "python/"

  lib="$dest/lib/python3.13"
  # ── Trim what ChordPresenter never uses ──────────────────────────────────
  # bin/python3.13 has Python linked in statically; libpython is only for
  # embedding. Tcl/Tk + tkinter/idle/turtle = GUI toolkit. pip/ensurepip =
  # package installer. Headers/config = building C extensions.
  rm -rf "$dest/include" "$dest/share" "$dest/lib/pkgconfig" \
         "$dest/lib/libpython3.13.dylib" "$dest/lib/"libtcl* \
         "$dest/lib/"tcl9* "$dest/lib/"tk9* "$dest/lib/"itcl* "$dest/lib/"thread* \
         "$lib/tkinter" "$lib/idlelib" "$lib/turtledemo" "$lib/turtle.py" \
         "$lib/ensurepip" "$lib/pydoc_data" "$lib/config-3.13-darwin" \
         "$lib/site-packages/"pip* "$lib/lib-dynload/"_tkinter* "$lib/test"
  # Keep only the interpreter itself (no symlinks: they don't survive
  # bundling reliably, and the app calls bin/python3.13 directly).
  find "$dest/bin" -mindepth 1 ! -name 'python3.13' -exec rm -f {} +
  find "$dest" -name '__pycache__' -type d -prune -exec rm -rf {} +

  # Sanity check (only runs for this Mac's own chip).
  if [ "$arch" = "$(uname -m)" ] || { [ "$arch" = "aarch64" ] && [ "$(uname -m)" = "arm64" ]; }; then
    "$dest/bin/python3.13" -c "import ssl, json, re, html.parser, urllib.request, subprocess, tempfile, uuid, struct, argparse; print('  ok:', ssl.OPENSSL_VERSION)"
  fi
  echo "  $arch: $(du -sh "$dest" | cut -f1)"
done
