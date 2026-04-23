# context-police

## What this project is

A installable plugin for Claude Code that intercepts automatic context compaction and gives the user control over it before it happens.

Claude Code has a `PreCompact` hook that fires before context compaction. This project uses that hook to:
1. **Block** automatic compaction from happening silently
2. **Notify** the user via desktop notification (macOS / Linux)
3. Let the user run `/compact focus on X` manually to control what gets preserved

## Background & motivation

Claude Code compacts the conversation automatically when context approaches the limit (200k tokens). The user has no say in when or how this happens. The only indirect control is a `## Compact Instructions` section in `CLAUDE.md`, which gets re-read during compaction.

This project adds a real-time intervention point: block the auto-compaction, notify the user, and let them decide how to proceed.

## Design decision: Option B (block + notify)

We evaluated two options:

**Option A** — Set focus ahead of time, auto-inject into CLAUDE.md on compaction. Clean but passive.

**Option B (chosen)** — Block compaction + fire desktop notification. User then runs `/compact focus on X` manually.

Reasons for Option B:
- User has real-time control
- Simpler hook script (no CLAUDE.md mutation needed)
- `/compact focus on X` already exists as a Claude Code command — we just need to surface the moment to use it
- Interactive stdin during a hook subprocess is unreliable, so real-time prompting inside the hook is not feasible

## How it works

```
Context approaches limit
        ↓
Claude Code fires PreCompact hook (matcher: "auto")
        ↓
context-police hook script runs
        ↓
Desktop notification fires → "About to auto-compact. Run /compact focus on X to proceed."
        ↓
Script outputs {"decision": "block"} → compaction is prevented
        ↓
User sees notification, then runs /compact focus on X manually
        ↓
Manual /compact fires → hook does NOT intercept (matcher was "auto" only)
        ↓
Compaction happens with user's chosen focus
```

## Implementation plan

### Files to create

```
context-police/
├── CLAUDE.md                        ← this file
├── README.md                        ← user-facing docs
├── install.sh                       ← one-liner installer
└── context-police.sh                ← the actual hook script
```

### The hook script (`context-police.sh`)

Installed to `~/.claude/scripts/context-police.sh`. Logic:

1. Read PreCompact JSON payload from stdin
2. Parse `trigger` field — if `"manual"`, output `{"decision": "allow"}` and exit (don't intercept manual `/compact` runs)
3. Send desktop notification:
   - macOS: `osascript -e 'display notification ...'`
   - Linux: `notify-send ...`
   - Fallback: write to stderr
4. Append entry to `~/.claude/context-police.log`
5. Output `{"decision": "block", "reason": "..."}` to block compaction

### Settings configuration

Added to `~/.claude/settings.json` (global, all projects):

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "auto",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/scripts/context-police.sh"
          }
        ]
      }
    ]
  }
}
```

`matcher: "auto"` is critical — it means the hook only fires for automatic compaction, not when the user explicitly runs `/compact`.

### Installer (`install.sh`)

Run once by the user. Steps:
1. Check for `jq` (required for settings.json merging) — error with install hint if missing
2. Create `~/.claude/scripts/` directory
3. Download `context-police.sh` from repo and `chmod +x`
4. Create `~/.claude/settings.json` if it doesn't exist
5. Merge hook config using `jq` — preserves any existing hooks the user has

### Edge cases

| Problem | Handling |
|---|---|
| `jq` not installed | Installer errors early with `brew install jq` hint |
| No notification system (headless) | Fallback writes warning to stderr |
| macOS notification permissions | Terminal has auto-grant; user may need System Settings > Notifications |
| Compaction keeps retrying | Each retry re-fires hook and re-notifies — intended behavior |
| User runs `/compact` without focus | Passes through (matcher is `auto` only) |
| Existing hooks in settings.json | jq merge with `*` operator preserves them |

## Still to verify

The exact stdin payload schema of the PreCompact hook. The `trigger` field is documented but should be confirmed by testing with a debug script:

```bash
#!/bin/bash
INPUT=$(cat)
echo "$INPUT" >> ~/.claude/context-police-debug.log
echo '{"decision": "block"}'
```

Install this temporarily, trigger an auto-compact, and inspect the log to confirm field names.

## Distribution

Users install with:
```bash
curl -fsSL https://raw.githubusercontent.com/you/context-police/main/install.sh | bash
```

No npm needed for the initial version — pure shell script.
