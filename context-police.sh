#!/bin/bash
set -euo pipefail

INPUT=$(cat)

if echo "$INPUT" | grep -q '"trigger":"manual"'; then
  echo '{"decision": "allow"}'
  exit 0
fi

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
MESSAGE="Context limit approaching. Run /compact focus on X to control what gets preserved."

if command -v osascript &>/dev/null; then
  osascript -e "display notification \"$MESSAGE\" with title \"context-police\"" 2>/dev/null || true
elif command -v notify-send &>/dev/null; then
  notify-send "context-police" "$MESSAGE" 2>/dev/null || true
else
  echo "context-police: $MESSAGE" >&2
fi

LOG_FILE="$HOME/.claude/context-police.log"
echo "[$TIMESTAMP] Auto-compaction blocked" >> "$LOG_FILE"

echo '{"decision": "block", "reason": "Auto-compaction blocked by context-police. Run /compact focus on X to proceed."}'
