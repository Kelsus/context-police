---
description: Open the ContextPolice inspector — pick analysis, recommendations, or prompt tools
allowed-tools: Bash(~/.claude/scripts/context-police.py:*)
---

Two-step flow. Do NOT skip the menu step.

**Step 1 — show the menu**

Run `~/.claude/scripts/context-police.py --show --menu` using the Bash tool. It prints a boxed menu with 7 choices (1–6, q) and a note about the follow-up `a`/`e`/`d` replies available after option [4]. Relay its stdout VERBATIM inside a single fenced code block — no preamble, no extra commentary. After the code block, on its own line, print:

`Respondé con 1, 2, 3, 4, 5, 6 o q.`

Then end the turn. Do NOT run any analysis yet.

**Step 2 — on the user's next message, execute the chosen option**

Interpret the user's next reply as a single token and run the matching command via the Bash tool (timeout 180s), relaying stdout verbatim inside a fenced code block:

Menu choices:
- `1` → `~/.claude/scripts/context-police.py --show --llm --bedrock`
- `2` → `~/.claude/scripts/context-police.py --show --llm`
- `3` → `~/.claude/scripts/context-police.py --show --raw`
- `4` → `~/.claude/scripts/context-police.py --show --recommend --bedrock` — prints recommendations + a proposed rewritten extraction prompt (saved as draft). After the output, tell the user (one short line): `Respondé 'a' aplicar / 'e' editar / 'd' descartar / otra para seguir.`
- `5` → `~/.claude/scripts/context-police.py --show --edit-prompt`
- `6` → `~/.claude/scripts/context-police.py --show --last-summary`
- `q` (or empty) → do nothing, acknowledge with "Cancelado."

Draft follow-up (only meaningful after [4] was just run; if not, the script will print a helpful error):
- `a` / `aplicar` / `apply` → `~/.claude/scripts/context-police.py --show --apply-draft`
- `e` / `editar` / `edit` → `~/.claude/scripts/context-police.py --show --edit-draft`
- `d` / `descartar` / `discard` → `~/.claude/scripts/context-police.py --show --discard-draft`

Anything else → fall back to normal conversational handling. The user changed their mind.

Relay stderr only if stdout is empty.
