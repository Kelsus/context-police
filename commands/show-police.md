---
description: Open the ContextPolice inspector — pick analysis, recommendations, or prompt tools
allowed-tools: Bash(~/.claude/scripts/context-police.py:*)
---

Two-step flow. Do NOT skip the menu step.

**Step 1 — show the menu**

Run `~/.claude/scripts/context-police.py --show --menu` using the Bash tool. It prints a boxed menu with 7 choices (1–6, q). Relay its stdout VERBATIM inside a single fenced code block — no preamble, no extra commentary. After the code block, on its own line, print:

`Respondé con 1, 2, 3, 4, 5, 6 o q.`

Then end the turn. Do NOT run any analysis yet.

**Step 2 — on the user's next message, execute the chosen option**

The user's next message will typically be a single character: `1`–`6` or `q`. Interpret it as follows and run the matching command via the Bash tool (timeout 180s), relaying its stdout verbatim inside a fenced code block:

- `1` → `~/.claude/scripts/context-police.py --show --llm --bedrock` (categorized summary + token bars via Bedrock Sonnet 4.5)
- `2` → `~/.claude/scripts/context-police.py --show --llm` (categorized summary + token bars via local LM Studio)
- `3` → `~/.claude/scripts/context-police.py --show --raw` (raw formatted transcript)
- `4` → `~/.claude/scripts/context-police.py --show --recommend --bedrock` (actionable recommendations via Bedrock; drop `--bedrock` if the user asks for local)
- `5` → `~/.claude/scripts/context-police.py --show --edit-prompt` (seed/locate the custom summarization prompt file)
- `6` → `~/.claude/scripts/context-police.py --show --last-summary` (re-print the cached summary, no LLM call)
- `q` (or empty) → do nothing, just acknowledge with "Cancelado."

If the user's next message is not one of those tokens, fall back to normal conversational handling — they changed their mind.

Relay stderr only if stdout is empty.
