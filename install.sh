#!/bin/bash
set -euo pipefail

REPO="https://raw.githubusercontent.com/Kelsus/context-police/main"
SCRIPTS_DIR="$HOME/.claude/scripts"
COMMANDS_DIR="$HOME/.claude/commands"
SETTINGS_FILE="$HOME/.claude/settings.json"
HOOK_PATH="$SCRIPTS_DIR/context-police.py"
LEGACY_PATH="$SCRIPTS_DIR/context-police.sh"
COMMAND_PATH="$COMMANDS_DIR/show-police.md"

echo "Installing context-police..."

if ! command -v python3 &>/dev/null; then
  echo ""
  echo "Error: python3 is required but not found."
  echo "  macOS:  install Xcode Command Line Tools or 'brew install python'"
  echo "  Ubuntu: sudo apt install python3"
  echo "  Fedora: sudo dnf install python3"
  exit 1
fi

mkdir -p "$SCRIPTS_DIR"
mkdir -p "$COMMANDS_DIR"

echo "Downloading hook script..."
curl -fsSL "$REPO/context-police.py" -o "$HOOK_PATH"
chmod +x "$HOOK_PATH"

echo "Downloading /show-police slash command..."
curl -fsSL "$REPO/commands/show-police.md" -o "$COMMAND_PATH"

if [ -f "$LEGACY_PATH" ]; then
  rm "$LEGACY_PATH"
  echo "Removed legacy context-police.sh"
fi

if [ ! -f "$SETTINGS_FILE" ]; then
  echo '{}' > "$SETTINGS_FILE"
fi

echo "Updating ~/.claude/settings.json..."
python3 - "$SETTINGS_FILE" <<'PY'
import json, sys
path = sys.argv[1]
try:
    with open(path) as f:
        data = json.load(f)
except Exception:
    data = {}
if not isinstance(data, dict):
    data = {}

NEW_CMD = "~/.claude/scripts/context-police.py"
OLD_CMD = "~/.claude/scripts/context-police.sh"

hooks = data.setdefault("hooks", {})
pc = hooks.get("PreCompact", [])
if not isinstance(pc, list):
    pc = []

pc = [
    entry for entry in pc
    if isinstance(entry, dict)
    and not any(
        (h or {}).get("command") in (NEW_CMD, OLD_CMD)
        for h in (entry.get("hooks") or [])
    )
]
pc.append({
    "matcher": "auto",
    "hooks": [{"type": "command", "command": NEW_CMD}],
})
hooks["PreCompact"] = pc
data["hooks"] = hooks

with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY

echo ""
echo "context-police installed successfully!"
echo ""
echo "What happens next:"
echo "  - Auto-compaction triggers an interactive TUI"
echo "  - Options: block, compact now, abort, view raw transcript, analyze with local LLM"
echo "  - LLM analysis uses http://172.21.0.154:1234 with model qwen/qwen3-8b by default"
echo "  - Run /show-police at any time to open the inspector for the current session"
echo ""
echo "Configure via env vars (optional):"
echo "  CONTEXT_POLICE_LLM_URL, CONTEXT_POLICE_MODEL, CONTEXT_POLICE_TIMEOUT,"
echo "  CONTEXT_POLICE_MAX_CHARS, CONTEXT_POLICE_TOOL_TRUNC, CONTEXT_POLICE_LOG"
echo ""
echo "Log file: ~/.claude/context-police.log"
