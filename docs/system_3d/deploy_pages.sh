#!/bin/sh
# Triển khai viewer 3D v2 + STL lên GitHub Pages.
# Dọn SẠCH gh-pages (trước đây bị dính .cad_venv/__pycache__/dataset) rồi
# chỉ chép đúng bộ file deploy: index.html + stl/ + print_bambu/ + README + .nojekyll.
# Cách dùng:  1) build lại nếu đã sửa tham số:  ../../.cad_venv/bin/python build_system.py
#             2) chạy script này:               ./deploy_pages.sh
# Link: https://nguyenhuy0426.github.io/PPG_simulator/
set -e
cd "$(dirname "$0")"
SRCDIR="$(pwd)"
OLD_BRANCH=$(git rev-parse --abbrev-ref HEAD)
WT=/tmp/kilo/ppgpages

echo "==> Lấy nhánh gh-pages từ origin..."
git fetch origin gh-pages

echo "==> Dọn worktree cũ tại $WT..."
git worktree remove --force "$WT" 2>/dev/null || true
rm -rf "$WT"
git worktree add -f "$WT" gh-pages || { echo "❌ Không tạo được worktree gh-pages"; exit 1; }

echo "==> Xoá SẠCH mọi file cũ trong gh-pages (giữ lại .git)..."
cd "$WT"
git rm -rq --ignore-unmatch .
# Tàn dư chưa được git quản lý (vd .cad_venv, __pycache__, dataset, .codegraph):
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +

echo "==> Chép đúng bộ file deploy v2 từ $SRCDIR..."
cp "$SRCDIR/viewer.html" "$WT/index.html"
mkdir -p "$WT/stl" "$WT/print_bambu"
cp "$SRCDIR"/out/stl/*.stl "$WT/stl/"
cp "$SRCDIR"/out/print_bambu/*.stl "$WT/print_bambu/"
cp "$SRCDIR/README.md" "$WT/README.md"
touch "$WT/.nojekyll"

git add -A
echo "==> Nội dung gh-pages sau khi dọn:"
git ls-files | sed 's/^/    /'
git commit -m "deploy v2: can truot nam cham + STL downloads ($(date +%Y-%m-%d))" \
    || echo "  (không có thay đổi để commit)"

echo "==> Đẩy lên origin gh-pages..."
git push origin gh-pages

cd "$SRCDIR"
git worktree remove --force "$WT" 2>/dev/null || true
echo "✅ Đã dọn sạch và đẩy bản deploy v2 lên gh-pages."
echo "   Link: https://nguyenhuy0426.github.io/PPG_simulator/"
echo "(đang ở lại branch: $OLD_BRANCH)"
