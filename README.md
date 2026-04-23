# context-police

Intercepts automatic context compaction in Claude Code and gives you control over it before it happens.

## The problem

Claude Code silently compacts the conversation when context approaches the 200k token limit. You have no say in when or how this happens.

## What this does

- **Blocks** automatic compaction from happening silently
- **Notifies** you via desktop notification (macOS / Linux)
- Lets you run `/compact focus on X` manually to control what gets preserved

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Kelsus/context-police/main/install.sh | bash
```

**Requires:** `jq` — install with `brew install jq` (macOS) or `sudo apt install jq` (Linux)

## How it works

```
Context approaches limit
        ↓
Claude Code fires PreCompact hook
        ↓
Desktop notification fires → "Context limit approaching. Run /compact focus on X"
        ↓
Auto-compaction is blocked
        ↓
You run /compact focus on X manually
        ↓
Compaction happens with your chosen focus
```

The hook only intercepts **automatic** compaction. Running `/compact` yourself is never blocked.

## Usage

Once installed, you don't need to do anything until you get the notification. When it fires:

1. Switch to your Claude Code terminal
2. Run `/compact focus on <what matters to you>`

Examples:
```
/compact focus on the authentication flow we are debugging
/compact focus on the current task and the decisions made so far
/compact focus on the API design discussion
```

## Logs

Blocked compaction attempts are logged to `~/.claude/context-police.log`.

## Uninstall

Remove the hook script:
```bash
rm ~/.claude/scripts/context-police.sh
```

Then remove the hook entry from `~/.claude/settings.json` under `hooks.PreCompact`.
