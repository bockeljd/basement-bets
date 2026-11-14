#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$HOME/.basement_bets_kenpom.env"
PLIST_PATH="$HOME/Library/LaunchAgents/com.basementbets.kenpom-sync.plist"
LOG_DIR="$HOME/Library/Logs"
LOG_PATH="$LOG_DIR/basementbets-kenpom-sync.log"
PYTHON_BIN="$REPO_DIR/venv/bin/python"
PIP_BIN="$REPO_DIR/venv/bin/pip"

echo "=== Basement Bets Daily Mac KenPom Sync Installer ==="
echo "Repo: $REPO_DIR"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Error: Python virtualenv not found at $PYTHON_BIN"
  exit 1
fi

if ! "$PYTHON_BIN" -c "import cloudscraper" >/dev/null 2>&1; then
  echo "Installing cloudscraper into ./venv so KenPom login works smoothly..."
  "$PIP_BIN" install cloudscraper
fi

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

if [ ! -f "$ENV_FILE" ]; then
  touch "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

if ! grep -q "^KENPOM_EMAIL=" "$ENV_FILE" || ! grep -q "^KENPOM_PASSWORD=" "$ENV_FILE"; then
  echo ""
  echo "Enter your KenPom subscriber credentials (saved locally with chmod 600 in $ENV_FILE):"
  read -r -p "KenPom Email: " KP_EMAIL
  read -r -s -p "KenPom Password: " KP_PASS
  echo ""
  {
    grep -v -E "^(KENPOM_EMAIL|KENPOM_PASSWORD|BASEMENT_BETS_URL)=" "$ENV_FILE" || true
    printf 'KENPOM_EMAIL="%s"\n' "$KP_EMAIL"
    printf 'KENPOM_PASSWORD="%s"\n' "$KP_PASS"
    printf 'BASEMENT_BETS_URL="https://basement-bets.vercel.app"\n'
  } > "${ENV_FILE}.tmp"
  mv "${ENV_FILE}.tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

if ! grep -q "^BASEMENT_BETS_URL=" "$ENV_FILE"; then
  printf 'BASEMENT_BETS_URL="https://basement-bets.vercel.app"\n' >> "$ENV_FILE"
fi

if ! grep -q "^BASEMENT_PASSWORD=" "$ENV_FILE"; then
  echo ""
  read -r -s -p "Optional Basement Bets Password (press Enter to skip if not enabled): " BB_PW
  echo ""
  if [ -n "$BB_PW" ]; then
    printf 'BASEMENT_PASSWORD="%s"\n' "$BB_PW" >> "$ENV_FILE"
    chmod 600 "$ENV_FILE"
  fi
fi

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.basementbets.kenpom-sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$REPO_DIR/scripts/mac_kenpom_daily_sync.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$REPO_DIR</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key>
      <integer>6</integer>
      <key>Minute</key>
      <integer>30</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>11</integer>
      <key>Minute</key>
      <integer>30</integer>
    </dict>
  </array>
  <key>StandardOutPath</key>
  <string>$LOG_PATH</string>
  <key>StandardErrorPath</key>
  <string>$LOG_PATH</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo ""
echo "✅ Installed macOS daily schedule (6:30 AM & 11:30 AM + on wake/login):"
echo "   Plist: $PLIST_PATH"
echo "   Logs:  $LOG_PATH"
echo ""
echo "Running an immediate test sync now..."
"$PYTHON_BIN" "$REPO_DIR/scripts/mac_kenpom_daily_sync.py"
echo "🎉 Full 7-dataset KenPom sync completed!"
