# context-police

Intercepts automatic context compaction in Claude Code and gives you control before it happens.

## The problem

Claude Code can compact the conversation automatically when context approaches the limit. Without intervention, this can happen at a bad moment and with default summarization.

## What this does

- Hooks into `PreCompact` with matcher `auto`
- Shows an interactive terminal menu before compaction proceeds
- Lets you choose to block, allow, or abort
- Falls back to desktop notification + block in headless mode

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Kelsus/context-police/main/install.sh | bash
```

Requires: `jq` (used by the installer to merge `~/.claude/settings.json` safely).

- macOS: `brew install jq`
- Ubuntu/Debian: `sudo apt install jq`
- Fedora: `sudo dnf install jq`

## How it works

```
Context approaches limit
        ↓
Claude Code fires PreCompact hook (auto)
        ↓
context-police.sh opens a TUI menu:
  [1] Block for now (default)
  [2] Compact now
  [3] Abort
        ↓
Decision is returned to Claude Code as hook JSON
```

Important: only automatic compaction is intercepted. Manual `/compact` runs are allowed.

## Usage

Once installed, wait for the menu to appear when context is near the limit.

1. Choose `1` to block and then run `/compact focus on <what matters>` manually.
2. Choose `2` to allow default compaction immediately.
3. Choose `3` to abort the agent.

In headless environments (no TTY), the hook sends a desktop notification (when available) and blocks by default.

Examples:
```
/compact focus on the authentication flow we are debugging
/compact focus on the current task and the decisions made so far
/compact focus on the API design discussion
```

## Logs

Actions are logged to `~/.claude/context-police.log`.

## Uninstall

Remove the hook script:
```bash
rm ~/.claude/scripts/context-police.sh
```

Then remove the hook entry from `~/.claude/settings.json` under `hooks.PreCompact`.
