#!/bin/bash
set -euo pipefail

INPUT=$(cat)

TRIGGER=$(echo "$INPUT" | jq -r '.trigger // "auto"' 2>/dev/null || echo "auto")
if [ "$TRIGGER" = "manual" ]; then
  echo '{"decision": "allow"}'
  exit 0
fi

CONTEXT_TOKENS=$(echo "$INPUT" | jq -r '.context_window.current // .tokens_used // .context_tokens // empty' 2>/dev/null || true)
MAX_TOKENS=$(echo "$INPUT" | jq -r '.context_window.max // 200000' 2>/dev/null || echo "200000")
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_FILE="$HOME/.claude/context-police.log"

show_tui() {
  local bar_width=32
  local bar_str=""
  local usage_line=""

  if [ -n "$CONTEXT_TOKENS" ] && [ "$CONTEXT_TOKENS" != "null" ]; then
    local percent=$(( CONTEXT_TOKENS * 100 / MAX_TOKENS ))
    local filled=$(( bar_width * percent / 100 ))
    local empty=$(( bar_width - filled ))
    bar_str+=$(printf '%*s' "$filled" '' | tr ' ' '█')
    bar_str+=$(printf '%*s' "$empty" '' | tr ' ' '░')
    usage_line="  [${bar_str}] ${percent}%  (${CONTEXT_TOKENS} / ${MAX_TOKENS} tokens)"
  else
    bar_str=$(printf '%*s' "$bar_width" '' | tr ' ' '░')
    usage_line="  [${bar_str}] Context window approaching limit"
  fi

  printf '\n'
  printf '  ╔══════════════════════════════════════════╗\n'
  printf '  ║          ContextPolice — Alert           ║\n'
  printf '  ╚══════════════════════════════════════════╝\n'
  printf '\n'
  printf '  Context window usage:\n'
  printf '%s\n' "$usage_line"
  printf '\n'
  printf '  Compaction is about to run...\n'
  printf '\n'
  printf '  What do you want to do?\n'
  printf '\n'
  printf '  [1]  Block for now     (run /compact focus on X manually)\n'
  printf '  [2]  Compact now       (use Claude'"'"'s default summarization)\n'
  printf '  [3]  Abort             (stop the agent)\n'
  printf '\n'
  printf '  > '
}

if [ -e /dev/tty ]; then
  show_tui >/dev/tty
  read -r CHOICE </dev/tty
else
  # Headless fallback: notify and block
  if command -v osascript &>/dev/null; then
    osascript -e 'display notification "Context limit approaching. Run /compact focus on X." with title "ContextPolice"' 2>/dev/null || true
  elif command -v notify-send &>/dev/null; then
    notify-send "ContextPolice" "Context limit approaching. Run /compact focus on X." 2>/dev/null || true
  fi
  echo "[$TIMESTAMP] Auto-compaction blocked (headless)" >> "$LOG_FILE"
  echo '{"decision": "block", "reason": "Auto-compaction blocked by ContextPolice. Run /compact focus on X to proceed."}'
  exit 0
fi

case "$CHOICE" in
  2)
    echo "[$TIMESTAMP] User allowed compaction via ContextPolice" >> "$LOG_FILE"
    echo '{"decision": "allow"}'
    ;;
  3)
    echo "[$TIMESTAMP] User aborted via ContextPolice" >> "$LOG_FILE"
    echo '{"decision": "block", "reason": "Aborted by user via ContextPolice."}'
    ;;
  *)
    echo "[$TIMESTAMP] Auto-compaction blocked by user — will run /compact manually" >> "$LOG_FILE"
    echo '{"decision": "block", "reason": "Auto-compaction blocked by ContextPolice. Run /compact focus on X to proceed."}'
    ;;
esac
