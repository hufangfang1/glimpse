#!/bin/bash
# Build Glimpse.app — double-click launcher for macOS (Dock / Launchpad).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="Glimpse"
APP_DIR="$ROOT/$APP_NAME.app"
ICON_SRC="$ROOT/assets/AppIcon.png"
ICONSET="$ROOT/assets/AppIcon.iconset"

echo "→ Building $APP_NAME.app ..."

rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

# --- App icon (.icns) ---
# We previously used `sips` + `iconutil`, but macOS sandboxing stamps
# `com.apple.provenance` on sips' output, which iconutil rejects with
# "Invalid Iconset". Pillow can emit a valid .icns directly and is already
# a project dependency.
if [[ -f "$ICON_SRC" ]]; then
  PYTHON_BUILD="$ROOT/.venv/bin/python"
  if [[ ! -x "$PYTHON_BUILD" ]]; then
    PYTHON_BUILD="$(command -v python3 || command -v python)"
  fi
  "$PYTHON_BUILD" - "$ICON_SRC" "$APP_DIR/Contents/Resources/AppIcon.icns" <<'PY'
import sys
from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
img = Image.open(src).convert("RGBA")
img.save(
    dst,
    format="ICNS",
    sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)],
)
PY
else
  echo "  (warning: $ICON_SRC not found, skipping icon)"
fi

# --- Launcher ---
cat > "$APP_DIR/Contents/MacOS/$APP_NAME" << LAUNCHER
#!/bin/bash
PROJECT_DIR="$ROOT"
LOG_FILE="\$HOME/Library/Logs/Glimpse.log"
PYTHON="\$PROJECT_DIR/.venv/bin/python"

mkdir -p "\$HOME/Library/Logs"

if [[ ! -f "\$PROJECT_DIR/main.py" ]]; then
  osascript -e 'display alert "Glimpse" message "找不到项目目录。\n\n请勿把 Glimpse.app 复制到「应用程序」。\n请在项目里运行:\n\nbash scripts/install_app.sh" as critical' 2>/dev/null
  exit 1
fi

if [[ ! -x "\$PYTHON" ]]; then
  osascript -e 'display alert "Glimpse" message "未找到虚拟环境。\n\n请在项目目录执行:\n\npython3 -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt" as critical' 2>/dev/null
  exit 1
fi

cd "\$PROJECT_DIR" || exit 1
export QT_LOGGING_RULES="qt.qpa.fonts=false"

# hw.optional.arm64=1 on Apple Silicon even when this script runs under Rosetta (x86_64).
if [[ "\$(sysctl -n hw.optional.arm64 2>/dev/null)" == "1" ]]; then
  RUNNER=(arch -arm64)
else
  RUNNER=()
fi

"\${RUNNER[@]}" "\$PYTHON" "\$PROJECT_DIR/main.py" 2>>"\$LOG_FILE"
code=\$?
if [[ \$code -ne 0 ]]; then
  osascript -e 'display alert "Glimpse" message "启动失败，详见日志:\n~/Library/Logs/Glimpse.log" as critical' 2>/dev/null
fi
exit \$code
LAUNCHER
chmod +x "$APP_DIR/Contents/MacOS/$APP_NAME"

# --- Info.plist ---
cat > "$APP_DIR/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>zh-Hans</string>
    <key>CFBundleExecutable</key>
    <string>Glimpse</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.glimpse.app</string>
    <key>CFBundleName</key>
    <string>Glimpse</string>
    <key>CFBundleDisplayName</key>
    <string>Glimpse</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSArchitecturePriority</key>
    <array>
        <string>arm64</string>
    </array>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
PLIST

echo "✓ Created: $APP_DIR"
echo ""
echo "使用方法:"
echo "  1. 双击 $APP_NAME.app 启动"
echo "  2. 固定到 Dock: 拖项目内的 $APP_NAME.app 到 Dock"
echo "  3. 固定到「应用程序」: bash scripts/install_app.sh  （不要用 Finder 复制 .app）"
echo "  4. 首次启动若被拦截: 系统设置 → 隐私与安全性 → 仍要打开"
echo ""
echo "注意: 不要只复制 .app 到「应用程序」，请用 install_app.sh 创建快捷方式。"
