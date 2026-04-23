<!--
Two-slide pitch for ContextPalice. Render with Marp / Slides / any
Markdown-to-slides tool (slides separated by `---` on its own line).
-->

---
marp: true
theme: default
paginate: false
---

# ContextPolice
### Take back control of Claude Code's auto-compaction

**The problem** — Claude Code silently summarizes your conversation when it
hits ~200 k tokens. No preview. No choice. No undo. Decisions, debugging
steps, half-written plans vanish into a summary Claude wrote to itself.

**The fix** — a `PreCompact` hook that intercepts auto-compaction and opens
an **interactive inspector** so *you* decide what survives.

```
  ╔══════════════════════════════════════════╗
  ║      ContextPolice — Inspector           ║
  ╚══════════════════════════════════════════╝

  [1] LLM analysis (Bedrock Sonnet 4.5)   categories + token bars
  [2] LLM analysis (local LM Studio)      categories + token bars
  [3] Raw transcript                      dump formatted, as-is
  [4] Recommendations                     actionable tips
  [5] Edit summarization prompt           override system prompt
  [6] View last cached summary            zero-cost re-read
  [q] Quit
```

- Dual provider: **AWS Bedrock** (Claude Sonnet 4.5) or **local LM Studio**
- Stdlib-only Python · one-liner installer · works inside Claude Code *and* standalone TUI
- Cached summaries + custom extraction prompts

---

# Live output — grounded in the actual conversation

### Categorized analysis with token bars

```
# Core Problem Solved
  ███████░░░░░░░░░░░░░  35% of transcript
  Fixed Python TTY bug and implemented AWS Bedrock LLM integration.

# Files Modified
  ███░░░░░░░░░░░░░░░░░  15% of transcript
  context-police.py + commands/show-police.md

# New Features
  ████░░░░░░░░░░░░░░░░  20% of transcript
  Token bars, recommendations, custom prompts, cached summaries.

# LLM Configuration
  ██░░░░░░░░░░░░░░░░░░  12% of transcript
  Dual provider (LM Studio / Bedrock), MAX_CHARS tuning.
```

### Recommendations the LLM generated about *this* session

- **Stop re-running `/show-police`** — each call adds ~1500 tokens of tool
  overhead and duplicates the transcript. Use `[6]` to re-read for free.
- **Remove the redundant `allowed-tools:` line** from the slash command —
  bloats every turn.
- **Replace menu → choice ping-pong with a single-turn `--option=N`** —
  halves message count.
- **Drop `[Image #N]` placeholders** in `format_transcript()` — 200 tokens
  of noise each.
- **Raise `CONTEXT_POLICE_MAX_CHARS` to 16 000+** for Bedrock — the
  8 000-char cap currently drops 60 k of relevant history.

*Notice* — none of these are generic advice. The model **saw** the actual
transcript and pointed at the specific bloat. That's the pitch.

```bash
curl -fsSL https://raw.githubusercontent.com/Kelsus/context-police/main/install.sh | bash
```
