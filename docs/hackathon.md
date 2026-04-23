# ContextPolice — Hackathon presentation

## The problem

Claude Code silently **auto-compacts** your conversation when the context
window approaches 200 k tokens. It happens in the background: no preview,
no interactive prompt, no recovery. Critical context — decisions,
debugging steps, half-written plans — can disappear into a generic
summary that Claude wrote to itself, and you only notice when something
goes wrong two turns later.

Today the only indirect control is a `## Compact Instructions` section in
`CLAUDE.md`, re-read during compaction. That's a static guess; it can't
react to *this specific* conversation.

## What ContextPolice does

A Claude Code plugin that hooks into `PreCompact` and hands control back
to the user **at the moment it matters**:

1. **Blocks** automatic compaction before it runs.
2. Opens an **interactive inspector** (TUI in the terminal, or text mode
   inside Claude Code itself) with rich options.
3. Optionally sends the transcript to a **local LLM** (LM Studio) or to
   **AWS Bedrock (Claude Sonnet 4.5)** to get a categorized summary,
   token-usage bars, or actionable recommendations — *before* you decide.
4. Lets you edit a **custom summarization prompt** so the analysis fits
   your workflow, not a generic taxonomy.
5. Caches the last summary so you can re-read it without spending tokens
   again.

## Architecture at a glance

```
Context approaches limit
        ↓
Claude Code fires PreCompact hook
        ↓
context-police.py runs, reads PreCompact JSON from stdin
        ↓
    /show-police inspector (text menu inside Claude Code)
        ├── [1] LLM analysis (Bedrock Sonnet 4.5)    categories + token bars
        ├── [2] LLM analysis (local LM Studio)       categories + token bars
        ├── [3] Raw transcript                       dump formatted, as-is
        ├── [4] Recommendations                      actionable tips
        ├── [5] Edit summarization prompt            seed/override system prompt
        ├── [6] View last cached summary             no new LLM call
        └── [q] Quit
        ↓
Emit {"decision":"allow"} or {"decision":"block", ...} to stdout
        ↓
Claude Code obeys.
```

Stdlib-only Python. No pip install. One-liner bash installer.

## Key engineering decisions

| Decision | Why |
|---|---|
| `PreCompact` hook with `matcher:"auto"` | Only intercept automatic compaction, never user-triggered `/compact` |
| Text menu via stdout (Bash tool) + TUI via `/dev/tty` (real terminal) | Works both inside Claude Code and in a terminal — we auto-detect |
| Multi-provider LLM: local OpenAI-compat *or* AWS Bedrock Converse | Local for privacy + offline; Bedrock for quality + large context |
| Token %-bars per category requested from the LLM itself | No token-counting library; the LLM already has a holistic view |
| Cached last summary + last recommendations in `~/.claude/context-police/` | Re-reading should be free — `[6]` never re-spends tokens |
| Custom `extract-prompt.md` overrides system prompt | Different projects need different summarization lenses |

## What's new vs. a plain PreCompact hook

A typical `PreCompact` hook is a binary "allow / block" decision. ContextPolice
turns that decision point into a **diagnostic station**:

- You see the transcript, categorized, with relative weights.
- You see recommendations targeted at *this conversation* ("your `tool_result`
  bodies take 40% — truncate them more").
- You carry the summary forward across sessions.

## Live demo — output samples

### 1. Categorized analysis with token bars

```
=== Context Analysis ===

# Core Problem Solved
  ███████░░░░░░░░░░░░░  35% of transcript
  Fixed Python TTY opening bug on macOS and implemented AWS Bedrock LLM
  integration with token visualization.
  - Python 3.9 'not seekable' error when opening /dev/tty in r+ mode —
    fixed by splitting into separate read/write handles (_TTYIO class)
  - Bash tool has no TTY — implemented non-interactive fallback that runs
    LLM analysis and prints to stdout
  - Added AWS Bedrock provider support via subprocess calls to aws CLI
    (--bedrock flag)
  - Fixed LLM prompt to prevent Sonnet from echoing tool call JSON
    instead of producing categories
  - Implemented token percentage bars per category with visual
    representation

# Files Modified
  ███░░░░░░░░░░░░░░░░░  15% of transcript
  Two main files updated in repo and synced to ~/.claude/.
  - context-police.py: open_tty() rewrite, run_standalone_noninteractive(),
    call_llm_bedrock(), --bedrock/--menu/--recommend/--edit-prompt/
    --last-summary flags
  - commands/show-police.md: slash command now shows TUI menu first with
    7 options, then runs chosen analysis mode

# LLM Configuration
  ██░░░░░░░░░░░░░░░░░░  12% of transcript
  Script supports two providers with environment variable overrides and
  custom prompt support.
  - Default: local LM Studio at http://172.21.0.154:1234 with qwen/qwen3-8b
  - Bedrock: us.anthropic.claude-sonnet-4-5-20250929-v1:0 in us-east-1
  - MAX_LLM_CHARS lowered from 80000 to 8000 to fit smaller context windows
  - Custom prompt support via ~/.claude/context-police/extract-prompt.md

# New Features Implemented
  ████░░░░░░░░░░░░░░░░  20% of transcript
  Added token visualization, recommendations, custom prompts, and cached
  summary viewing.
  - Token percentage bars: LLM estimates percent_tokens (0-100) per
    category, rendered as ███░░░ 42%
  - Recommendations mode (--recommend): separate LLM call for actionable
    context reduction tips
  - Custom prompt editing (--edit-prompt): opens
    ~/.claude/context-police/extract-prompt.md
  - Cached summary viewing (--last-summary): re-prints last analysis
    without new LLM call

# Slash Command Behavior
  ██░░░░░░░░░░░░░░░░░░  10% of transcript
  /show-police now works inside Claude Code with expanded 7-option menu.

# Testing Status
  ██░░░░░░░░░░░░░░░░░░   8% of transcript
  Local LLM and Bedrock integration both working, new features
  smoke-tested.
```

### 2. Targeted, conversation-specific recommendations

```
=== Recommendations ===

- Stop repeatedly calling `/show-police` to test the same session — each
  invocation adds ~1500 tokens of tool-call overhead and duplicates the
  entire transcript in context; run it once, cache the summary, and use
  option `[6]` to review without re-analyzing.

- Remove the `allowed-tools: Bash(...)` line from `show-police.md` — it's
  redundant (the command body already instructs Bash usage) and bloats
  the slash-command definition that gets injected into every turn.

- Consolidate the repeated "Files Modified" explanations across turns —
  the script and slash-command changes are now stable; summarize them
  once instead of re-listing edits in every analysis.

- Replace the multi-step "show menu → wait → run choice" flow with a
  single-turn `--option=N` interface so the slash command executes in
  one Bash call, halving message count.

- Drop `[Image #2]` / `[Image #3]` placeholders — they occupy ~200 tokens
  each with no semantic value; strip them in `format_transcript()`.

- Raise `CONTEXT_POLICE_MAX_CHARS` to 16000+ for Bedrock's larger
  context window — current 8000-char cap forces truncation of 60k+ chars
  and loses early debugging context.

- Remove defensive boilerplate from the slash-command instruction block
  ("Relay stderr only if stdout is empty", "Notes:" section) — has never
  triggered and adds ~150 tokens per invocation.
```

Notice what the LLM does that a static rule can't: it *saw* the recent
tool calls in the transcript, identified the redundancy, and suggested a
single-turn `--option=N` redesign. This is analysis grounded in the
specific conversation, not advice from a book.

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/Kelsus/context-police/main/install.sh | bash
```

Requires Python 3, AWS CLI (optional, for Bedrock), and a local
OpenAI-compatible LLM endpoint (optional, for local mode).

## What we shipped in one day

- `PreCompact` interception with a 7-option inspector.
- Dual LLM providers (LM Studio / Bedrock).
- Token %-bars per category from the model itself.
- Actionable recommendations grounded in the current transcript.
- Customizable extraction prompt.
- Cached summary + recommendations for zero-cost re-reads.
- Works both as a standalone TUI and as a Claude Code slash command.

## Roadmap

- Single-turn `--option=N` slash command flow (eliminates ping-pong).
- Richer token accounting (per-tool-result char contribution, not just
  LLM estimate).
- `[4]` → `[5]`: ask the LLM to *rewrite* your `CLAUDE.md` Compact
  Instructions based on its own recommendations, one-click apply.
- Session-cross correlation: "this category has grown 30% since your
  last summary".
