#!/usr/bin/env bash
# Turn on automatic feedback sync: every 5 minutes macOS runs sync-feedback.mjs, which copies new
# reports into ~/PREDICTABLE Feedback and shows a notification.
#   bash install-autosync.sh            install / restart
#   bash install-autosync.sh --remove   turn it off again
set -euo pipefail
LABEL="com.predictable.feedback-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
HERE="$(cd "$(dirname "$0")" && pwd)"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--remove" ]; then
  rm -f "$PLIST"
  echo "Automatic feedback sync turned off."
  exit 0
fi

NODE="$(command -v node)"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$NODE</string><string>$HERE/sync-feedback.mjs</string></array>
  <key>WorkingDirectory</key><string>$HERE</string>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/predictable-feedback-sync.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/predictable-feedback-sync.log</string>
</dict>
</plist>
EOF
plutil -lint "$PLIST" >/dev/null
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 3
echo "Automatic feedback sync is on (every 5 minutes). Last log lines:"
tail -n 3 "$HOME/Library/Logs/predictable-feedback-sync.log" 2>/dev/null || true
