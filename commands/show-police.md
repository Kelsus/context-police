---
description: Open the ContextPolice inspector — view raw transcript or LLM-analyze the current session
allowed-tools: Bash(~/.claude/scripts/context-police.py:*)
---

Run `~/.claude/scripts/context-police.py --show` using the Bash tool.

This opens ContextPolice's interactive menu on the user's terminal. From there they can view the raw transcript of the current session or trigger an LLM-generated categorized summary.

The TUI is rendered directly on `/dev/tty`, so the Bash tool output will be empty or show only the final exit status — that is expected. The command returns when the user quits the menu.

Invoke the command and exit. Do not add any narration or summary of the script's output.
