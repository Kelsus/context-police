# context-police

## What this project is

An installable plugin for Claude Code that intercepts automatic context compaction and gives the user control over it before it happens.

Claude Code has a `PreCompact` hook that fires before context compaction. This project uses that hook to:
1. **Block** automatic compaction from happening silently
2. Open an **interactive TUI** on the controlling terminal with five choices: block / allow / abort / view raw transcript / analyze with LLM
3. Optionally send the transcript to a **local LLM** (LM Studio, qwen/qwen3-8b) to get a categorized summary before the user decides
4. Let the user run `/compact focus on X` manually to control what gets preserved

## Background & motivation

Claude Code compacts the conversation automatically when context approaches the limit (200k tokens). The user has no say in when or how this happens, and no view into what's about to be summarized away. The only indirect control is a `## Compact Instructions` section in `CLAUDE.md`, which gets re-read during compaction.

This project adds a real-time intervention point: block the auto-compaction, open a TUI, optionally show the raw transcript or an LLM-generated categorized summary, and let the user decide how to proceed with full information.

## Design evolution

We initially evaluated two options:

**Option A** — Set focus ahead of time, auto-inject into CLAUDE.md on compaction. Clean but passive.

**Option B (original)** — Block compaction + fire desktop notification. User then runs `/compact focus on X` manually.

**Option C (current)** — Block + open an interactive TUI on `/dev/tty` with rich choices including LLM-powered transcript analysis.

We moved from B to C because the assumption that "interactive stdin during a hook subprocess is unreliable" turned out to be wrong: a hook's subprocess inherits the controlling terminal, and opening `/dev/tty` directly for I/O works fine on macOS and Linux. This unlocked the full TUI and, eventually, the LLM feature.

## How it works

```
Context approaches limit
        ↓
Claude Code fires PreCompact hook (matcher: "auto")
        ↓
context-police.py runs, reads PreCompact JSON from stdin
        ↓
If trigger == "manual" → emit {"decision": "allow"} and exit
        ↓
Open /dev/tty, render the TUI menu:
  [1] Block (default)
  [2] Allow compaction
  [3] Abort the agent
  [4] View raw transcript (piped through `less`)
  [5] Analyze with LLM — POST to http://172.21.0.154:1234/v1/chat/completions
        ↓
Options 4/5 loop back to the menu so the user can decide informed
        ↓
Finally emit {"decision": "allow"} or {"decision": "block", "reason": "..."}
        ↓
Claude Code obeys the decision
```

## Implementation

### Files in the repo

```
context-police/
├── CLAUDE.md                        ← this file
├── README.md                        ← user-facing docs
├── install.sh                       ← one-liner installer
└── context-police.py                ← the hook script (Python, stdlib only)
```

### The hook script (`context-police.py`)

Installed to `~/.claude/scripts/context-police.py` with shebang `#!/usr/bin/env python3`. Stdlib only — no pip install required.

Key responsibilities:

1. Read PreCompact JSON payload from stdin.
2. Parse `trigger` — if `"manual"`, emit `{"decision": "allow"}` and exit (don't intercept manual `/compact`).
3. Extract `transcript_path`, current/max token counts from the payload.
4. Open `/dev/tty` for TUI I/O. If unavailable (headless) → desktop notification + block.
5. Loop the menu. Options 4/5 load the transcript JSONL and either pipe it to `less` or send it to the LLM.
6. Emit the final decision JSON to stdout and exit.

### Stdout discipline (critical)

The hook's stdout is the decision channel — any stray byte breaks Claude Code's parser and silently lets compaction proceed unblocked. Guardrails:

- Only `emit_decision()` writes to stdout (using a saved reference to `sys.__stdout__`).
- At the start of `main()`, `sys.stdout` is reassigned to `sys.stderr` so any accidental `print()` goes to stderr instead.
- All user-visible output goes through `tui()` → the `/dev/tty` handle.
- All diagnostics go through `log()` → `~/.claude/context-police.log`.

### LLM integration

- **Endpoint**: `{LLM_URL}/v1/chat/completions` (OpenAI-compatible). Default `LLM_URL` is `http://172.21.0.154:1234` (LM Studio).
- **Model**: `qwen/qwen3-8b` by default. Override via `CONTEXT_POLICE_MODEL`.
- **Prompt**: instructs the model to pick 3–7 categories relevant to the specific conversation and return structured JSON `{"categories": [{"name", "summary", "items": [...]}, ...]}`. No fixed taxonomy.
- **Output format**: JSON (not markdown). Reasons:
  - Deterministic rendering in a terminal without a markdown library.
  - Parse failures degrade gracefully — the raw response is shown as fallback, so the feature still produces output.
- **Temperature 0.2**, `max_tokens: 2000`, `stream: false`.
- **Error handling**: `call_llm` catches `URLError`, `HTTPError`, `timeout`, JSON parse errors. Never propagates — returns `(False, human_msg)` and the menu re-renders.

### Transcript reduction strategy

A full transcript at auto-compact time is ~200k tokens; qwen3-8b's serving context is typically 32k. Two-stage reduction:

1. **Structural stripping** (`format_transcript`) — keep user messages and assistant text intact; collapse `tool_use` to `[tool: Name(input…)]` stubs; truncate `tool_result` bodies to `TOOL_RESULT_TRUNC` chars (default 500). Typically cuts 60–80% of volume because tool_result dumps (file contents, grep output) are the bulk.
2. **Head truncation** (`compress_for_llm`) — if still over `MAX_LLM_CHARS` (80000 chars ≈ 20k tokens), drop from the oldest end and prepend a truncation marker. The LLM sees the marker and is instructed to add a "Truncation Notice" category.

Hierarchical/map-reduce summarization was rejected: multiple LLM calls double latency in a blocking hook.

### Settings configuration

Added to `~/.claude/settings.json` by the installer (global, all projects):

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "auto",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/scripts/context-police.py"
          }
        ]
      }
    ]
  }
}
```

`matcher: "auto"` is critical — the hook only fires for automatic compaction, not when the user explicitly runs `/compact`.

### Installer (`install.sh`)

1. Checks for `python3` — errors early if missing.
2. Creates `~/.claude/scripts/`.
3. Downloads `context-police.py` and `chmod +x`.
4. Removes any legacy `context-police.sh` from a previous version.
5. Merges the hook entry into `settings.json` using inline Python (no `jq` dependency). Dedupes any prior entry pointing at the old `.sh` or the `.py` path.

### Edge cases

| Problem | Handling |
|---|---|
| Interactive `/compact` | `trigger == "manual"` → allow and exit (matcher was already `auto` only, but this is belt-and-suspenders) |
| Headless (no `/dev/tty`) | Desktop notification (osascript / notify-send) + block |
| Transcript path missing from payload | Options 4/5 show an error in the TUI and stay in the menu |
| Transcript file unreadable | Same — error in TUI, back to menu |
| LLM unreachable / timeout | Error shown in TUI, menu re-renders; user can still block/allow/abort |
| LLM returns malformed JSON | `parse_llm_json` tolerates code fences and leading prose; if it still fails, raw response is shown |
| Transcript > 200k tokens | Two-stage reduction before sending to LLM |
| Stray `print()` to stdout | `sys.stdout` remapped to stderr at top of `main`; only `emit_decision` uses the real stdout |
| Existing hooks in settings.json | Python merge preserves them; dedupes only entries that reference our command |

### Verification

- **Manual dry-run**: synthesize a `{trigger: "auto", transcript_path: "..."}` payload and pipe it to the script. TUI should render on the attached terminal and stdout should yield exactly one JSON object.
- **LLM connectivity**: `curl` the `/v1/chat/completions` endpoint independently to isolate LLM failures from hook bugs.
- **Settings integrity**: parse `~/.claude/settings.json` after install and confirm the `PreCompact` entry references `.py`, not `.sh`.

## Still to verify

The exact stdin payload schema of the PreCompact hook. The script tolerates multiple possible field names (`transcript_path` / `transcriptPath` / `transcript`; `context_window.current` / `tokens_used` / `context_tokens`). If the hook fires and the transcript-path field is still missing, add a temporary debug log that dumps the full payload on first invocation to confirm the actual field name.

## Distribution

Users install with:

```bash
curl -fsSL https://raw.githubusercontent.com/Kelsus/context-police/main/install.sh | bash
```

No npm or pip needed — just Python 3 (present on every modern macOS/Linux).
