# context-police

Intercepts automatic context compaction in Claude Code and gives you control over it before it happens — including inspecting or LLM-analyzing the conversation first.

## The problem

Claude Code silently compacts the conversation when context approaches the 200k token limit. You have no say in when or how this happens, and no way to see what's about to be summarized away.

## What this does

When auto-compaction is about to run, context-police intercepts the hook and opens an interactive menu:

- **Block** the compaction and run `/compact focus on X` yourself
- **Compact now** with Claude's default behavior
- **Abort** the agent entirely
- **View the raw transcript** that's about to be compacted
- **Analyze with a local LLM** — get a categorized summary of the conversation so you know what matters before deciding

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Kelsus/context-police/main/install.sh | bash
```

**Requires:** `python3` (preinstalled on macOS 12+ and all modern Linux).

The installer:
1. Checks for `python3`
2. Downloads `context-police.py` to `~/.claude/scripts/`
3. Registers the hook in `~/.claude/settings.json` with `matcher: "auto"`
4. Removes any prior `context-police.sh` from a previous version

## How it works

```
Context approaches limit
        ↓
Claude Code fires PreCompact hook
        ↓
Interactive TUI opens with 5 options
        ↓
   ┌────┴──────────────────────────────────┐
   │                                       │
[1] block       [2] allow    [3] abort    [4] view raw   [5] analyze with LLM
   │               │            │            │                     │
   │               │            │            └──→ pager (less)     │
   │               │            │                                  ↓
   │               │            │                          qwen3-8b @ 172.21.0.154:1234
   │               │            │                                  │
   │               │            │                          categorized summary
   │               │            │                                  │
   │               │            │                          (back to menu)
   │               │            │
   ↓               ↓            ↓
blocked       compaction     agent
(/compact     proceeds       stopped
 focus on X)
```

The hook only intercepts **automatic** compaction. Running `/compact` yourself is never blocked.

## LLM analysis

Option 5 sends the conversation transcript to a local LLM (OpenAI-compatible API, LM Studio by default) and asks it to identify **dynamic categories** relevant to the specific conversation — things like "Current task", "Files touched", "Decisions made", "Open questions", "Next steps". The model picks the categories itself based on what's in the transcript.

The output is structured JSON rendered as a categorized summary in your terminal.

### Transcript size handling

Claude Code transcripts at auto-compact time are ~200k tokens, too large for an 8B local model. The hook reduces size with two strategies before sending:

1. **Structural stripping** — keeps user/assistant messages intact; shows tool calls as compact stubs; truncates long `tool_result` bodies (default 500 chars).
2. **Head truncation** — if still too large, drops oldest messages until under `CONTEXT_POLICE_MAX_CHARS` (default 80000 chars ≈ 20k tokens). Adds a truncation marker so the LLM knows.

## Configuration

Override behavior via env vars (set in the shell that launches Claude Code):

| Env var | Default | Purpose |
|---|---|---|
| `CONTEXT_POLICE_LLM_URL` | `http://172.21.0.154:1234` | Base URL of the OpenAI-compatible LLM server |
| `CONTEXT_POLICE_MODEL` | `qwen/qwen3-8b` | Model ID passed to the LLM |
| `CONTEXT_POLICE_TIMEOUT` | `120` | HTTP timeout in seconds for the LLM call |
| `CONTEXT_POLICE_MAX_CHARS` | `80000` | Max chars of transcript sent to LLM (≈ token budget / 4) |
| `CONTEXT_POLICE_TOOL_TRUNC` | `500` | Chars kept from each `tool_result` body |
| `CONTEXT_POLICE_LOG` | `~/.claude/context-police.log` | Log file path |

## Usage

Once installed, you don't need to do anything until the menu appears. When it fires:

1. Pick [4] or [5] if you want context before deciding
2. Then pick [1] (block) and run `/compact focus on <what matters>`

Examples:
```
/compact focus on the authentication flow we are debugging
/compact focus on the current task and the decisions made so far
/compact focus on the API design discussion
```

## Logs

All hook actions (block, allow, abort, LLM errors) are logged to `~/.claude/context-police.log`.

## Troubleshooting

**LLM option fails with "Cannot reach LLM"** — test the server directly:
```bash
curl -sS -X POST http://172.21.0.154:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen/qwen3-8b","messages":[{"role":"user","content":"reply OK"}],"stream":false}'
```

If that fails, the server isn't running or isn't in OpenAI-compat mode. Override via `CONTEXT_POLICE_LLM_URL`.

**No TUI appears, just a notification** — you're running in a context without a controlling TTY. Hook falls back to desktop notification + block. Expected on headless/remote sessions without a terminal.

## Uninstall

```bash
rm ~/.claude/scripts/context-police.py
```

Then remove the hook entry from `~/.claude/settings.json` under `hooks.PreCompact`.
