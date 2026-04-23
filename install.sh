#!/bin/bash
set -euo pipefail

REPO="https://raw.githubusercontent.com/Kelsus/context-police/main"
SCRIPTS_DIR="$HOME/.claude/scripts"
SETTINGS_FILE="$HOME/.claude/settings.json"

echo "Installing context-police..."

if ! command -v jq &>/dev/null; then
  echo ""
  echo "Error: jq is required but not installed."
  echo "  macOS:  brew install jq"
  echo "  Ubuntu: sudo apt install jq"
  echo "  Fedora: sudo dnf install jq"
  exit 1
fi

mkdir -p "$SCRIPTS_DIR"

echo "Downloading hook script..."
curl -fsSL "$REPO/context-police.sh" -o "$SCRIPTS_DIR/context-police.sh"
chmod +x "$SCRIPTS_DIR/context-police.sh"

if [ ! -f "$SETTINGS_FILE" ]; then
  echo '{}' > "$SETTINGS_FILE"
fi

echo "Updating ~/.claude/settings.json..."
UPDATED=$(jq '
  .hooks //= {} |
  .hooks.PreCompact //= [] |
  .hooks.PreCompact |= map(select(
    (.hooks // []) | map(.command) | contains(["~/.claude/scripts/context-police.sh"]) | not
  )) |
  .hooks.PreCompact += [{
    "matcher": "auto",
    "hooks": [{
      "type": "command",
      "command": "~/.claude/scripts/context-police.sh"
    }]
  }]
' "$SETTINGS_FILE")
echo "$UPDATED" > "$SETTINGS_FILE"

echo ""
echo "context-police installed successfully!"
echo ""
echo "What happens next:"
echo "  - Auto-compaction is now blocked"
echo "  - You will get a desktop notification when context fills up"
echo "  - Run /compact focus on X to compact with your chosen focus"
echo ""
echo "Log file: ~/.claude/context-police.log"
