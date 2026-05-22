#!/bin/bash
# Install Proxyman shortcut into /Applications (symlink, not a copy).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="/Applications/Proxyman.app"

bash "$ROOT/scripts/build_app.sh"

if [[ -e "$TARGET" && ! -L "$TARGET" ]]; then
  echo ""
  echo "检测到 /Applications/Proxyman.app 是「复制」进去的副本，无法正常使用。"
  echo "请先把它拖进废纸篓删除，然后重新运行本脚本。"
  echo ""
  exit 1
fi

ln -sf "$ROOT/Proxyman.app" "$TARGET"

echo ""
echo "✓ 已安装到「应用程序」（快捷方式）"
echo "  指向: $ROOT/Proxyman.app"
echo ""
echo "现在可以从启动台或应用程序文件夹打开 Proxyman。"
echo "若首次被拦截: 系统设置 → 隐私与安全性 → 仍要打开"
echo ""

open "$TARGET" 2>/dev/null || true
