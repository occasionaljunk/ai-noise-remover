#!/usr/bin/env bash
# Rebuilds "Noise Remover.app" from NoiseRemover.applescript + AppIcon.icns.
set -euo pipefail
cd "$(dirname "$0")"
APP="../Noise Remover.app"
rm -rf "$APP"
osacompile -s -o "$APP" NoiseRemover.applescript
cp AppIcon.icns "$APP/Contents/Resources/applet.icns"
# Drop the compiled default icon so ours is used.
rm -f "$APP/Contents/Resources/Assets.car"
PL="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Delete :CFBundleIconName" "$PL" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.internal.noiseremover" "$PL" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.internal.noiseremover" "$PL"
/usr/libexec/PlistBuddy -c "Add :CFBundleName string 'Noise Remover'" "$PL" 2>/dev/null || true
codesign --force --deep -s - "$APP"
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP"
echo "Built $APP"
