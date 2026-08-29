#!/usr/bin/env bash
# Cập nhật viewer 3D lên GitHub Pages.
# Cách dùng:  1) build lại nếu đã sửa tham số:  ../../.cad_venv/bin/python build_system.py
#             2) chạy script này:               ./deploy_pages.sh
# Link: https://nguyenhuy0426.github.io/PPG_simulator/   (bật Pages 1 lần trong
# Settings → Pages → Source: gh-pages → root)
set -e
cd "$(dirname "$0")"
SRC="viewer.html"
OLD_BRANCH=$(git rev-parse --abbrev-ref HEAD)
WT=/tmp/kilo/ppgpages

git fetch origin gh-pages
git worktree add -f "$WT" gh-pages 2>/dev/null || true
cp "$SRC" "$WT/index.html"
cd "$WT"
git add -A
git commit -m "update viewer $(date +%F\ %H:%M)" || echo "  (không có thay đổi)"
git push origin gh-pages
cd - >/dev/null
git worktree remove --force "$WT" 2>/dev/null || true
echo "✅ Đã đẩy viewer lên gh-pages."
echo "   Link: https://nguyenhuy0426.github.io/PPG_simulator/"
echo "(đang ở lại branch: $OLD_BRANCH)"
