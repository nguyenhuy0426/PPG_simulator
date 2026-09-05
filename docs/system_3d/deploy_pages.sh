#!/bin/sh
# Triển khai viewer 3D v3 + STL lên GitHub Pages.
# Dọn SẠCH gh-pages (trước đây bị dính .cad_venv/__pycache__/dataset) rồi
# chỉ chép đúng bộ file deploy: index.html + stl/ + print_bambu/ + README + .nojekyll.
# Worktree tạm ở thư mục mktemp (tự dọn qua trap), sync theo TIP TRÊN REMOTE
# origin/gh-pages (không đụng nhánh gh-pages local), commit fail-fast.
# Cách dùng:  1) build lại nếu đã sửa tham số:  ../../.cad_venv/bin/python build_system.py
#             2) chạy script này:               ./deploy_pages.sh
# Link: https://nguyenhuy0426.github.io/PPG_simulator/
set -e
cd "$(dirname "$0")"
SRCDIR="$(pwd)"
WT=$(mktemp -d /tmp/ppgpages.XXXXXX)

# Dọn worktree + thư mục tạm kể cả khi script lỗi giữa chừng.
trap 'git worktree remove --force "$WT" 2>/dev/null || true; rm -rf "$WT"' EXIT

echo "==> Lấy nhánh gh-pages từ origin..."
git fetch origin gh-pages
git worktree prune

echo "==> Thêm worktree tạm tại $WT (detached tại tip origin/gh-pages)..."
git worktree add --detach "$WT" origin/gh-pages

echo "==> Xoá SẠCH mọi file cũ trong gh-pages (giữ lại .git)..."
cd "$WT"
git rm -rq --ignore-unmatch .
# Tàn dư chưa được git quản lý (vd .cad_venv, __pycache__, dataset, .codegraph):
find . -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +

echo "==> Chép đúng bộ file deploy v3 từ $SRCDIR..."
cp "$SRCDIR/viewer.html" "$WT/index.html"
mkdir -p "$WT/stl" "$WT/print_bambu"
cp "$SRCDIR"/out/stl/*.stl "$WT/stl/"
cp "$SRCDIR"/out/print_bambu/*.stl "$WT/print_bambu/"
cp "$SRCDIR/README.md" "$WT/README.md"
touch "$WT/.nojekyll"

git add -A
echo "==> Nội dung gh-pages sau khi dọn:"
git ls-files | sed 's/^/    /'
if [ -n "$(git status --porcelain)" ]; then
    # Message chung, luon dung cho moi lan deploy: noi dung cu the nam trong
    # lich su nhanh huynn, khong lap lai (va khong the sai) o day.
    git commit -m "deploy: cap nhat viewer 3D + STL + README ($(date +%Y-%m-%d))" || exit 1
else
    echo "  (không có thay đổi)"
fi

echo "==> Đẩy lên origin gh-pages (detached HEAD -> gh-pages)..."
git push origin HEAD:gh-pages
DEPLOY_SHA=$(git rev-parse --short HEAD)

cd "$SRCDIR"
echo "✅ Đã dọn sạch và đẩy bản deploy v3 lên gh-pages."
echo "   Commit đã đẩy: $DEPLOY_SHA"
echo "   Link: https://nguyenhuy0426.github.io/PPG_simulator/"
