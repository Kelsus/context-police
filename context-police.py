#!/usr/bin/env python3
"""ContextPolice — PreCompact hook with LLM-powered context analysis."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

LLM_URL = os.environ.get("CONTEXT_POLICE_LLM_URL", "http://172.21.0.154:1234")
MODEL_ID = os.environ.get("CONTEXT_POLICE_MODEL", "qwen/qwen3-8b")
LLM_TIMEOUT_S = int(os.environ.get("CONTEXT_POLICE_TIMEOUT", "120"))
MAX_LLM_CHARS = int(os.environ.get("CONTEXT_POLICE_MAX_CHARS", "80000"))
TOOL_RESULT_TRUNC = int(os.environ.get("CONTEXT_POLICE_TOOL_TRUNC", "500"))
LOG_FILE = Path(os.environ.get(
    "CONTEXT_POLICE_LOG",
    str(Path.home() / ".claude" / "context-police.log"),
))

_REAL_STDOUT = sys.__stdout__
TTY = None

BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
GREEN = "\033[32m"
RESET = "\033[0m"


def log(msg: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_FILE.open("a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def tui(msg: str = "", end: str = "\n") -> None:
    if TTY is None:
        return
    try:
        TTY.write(msg + end)
        TTY.flush()
    except Exception:
        pass


def tui_input(prompt: str = "  > ") -> str:
    if TTY is None:
        return ""
    try:
        TTY.write(prompt)
        TTY.flush()
        line = TTY.readline()
        return line.strip() if line else ""
    except Exception:
        return ""


def emit_decision(decision: str, reason: str | None = None) -> None:
    payload = {"decision": decision}
    if reason:
        payload["reason"] = reason
    try:
        _REAL_STDOUT.write(json.dumps(payload))
        _REAL_STDOUT.flush()
    except Exception:
        pass
    sys.exit(0)


def read_payload() -> dict:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except Exception as e:
        log(f"failed to parse stdin payload: {e}")
        return {}


def extract_metrics(p: dict) -> tuple[str, str | None, int | None, int]:
    trigger = p.get("trigger") or "auto"

    transcript_path = (
        p.get("transcript_path")
        or p.get("transcriptPath")
        or p.get("transcript")
    )

    cur = None
    cw = p.get("context_window") or {}
    if isinstance(cw, dict):
        cur = cw.get("current")
    if cur is None:
        cur = p.get("tokens_used") or p.get("context_tokens")
    try:
        cur = int(cur) if cur is not None else None
    except (TypeError, ValueError):
        cur = None

    maxt = None
    if isinstance(cw, dict):
        maxt = cw.get("max")
    try:
        maxt = int(maxt) if maxt is not None else 200000
    except (TypeError, ValueError):
        maxt = 200000

    return trigger, transcript_path, cur, maxt


def open_tty():
    try:
        return open("/dev/tty", "r+", buffering=1)
    except OSError:
        return None


def render_header(cur: int | None, maxt: int) -> None:
    bar_width = 32
    if cur is not None and maxt > 0:
        pct = (cur * 100) // maxt
        filled = (bar_width * pct) // 100
        filled = max(0, min(bar_width, filled))
        empty = bar_width - filled
        bar = "█" * filled + "░" * empty
        usage = f"  [{bar}] {pct}%  ({cur} / {maxt} tokens)"
    else:
        bar = "░" * bar_width
        usage = f"  [{bar}] Context window approaching limit"

    tui()
    tui(f"  {CYAN}╔══════════════════════════════════════════╗{RESET}")
    tui(f"  {CYAN}║{RESET}          {BOLD}ContextPolice — Alert{RESET}           {CYAN}║{RESET}")
    tui(f"  {CYAN}╚══════════════════════════════════════════╝{RESET}")
    tui()
    tui("  Context window usage:")
    tui(usage)
    tui()
    tui("  Compaction is about to run.")
    tui()


def render_menu() -> None:
    tui("  What do you want to do?")
    tui()
    tui(f"  [1]  {BOLD}Block for now{RESET}         (run /compact focus on X manually)   {DIM}[default]{RESET}")
    tui(f"  [2]  Compact now           (use Claude's default summarization)")
    tui(f"  [3]  Abort                 (stop the agent)")
    tui(f"  [4]  {CYAN}View raw transcript{RESET}")
    tui(f"  [5]  {CYAN}Analyze with LLM{RESET}      (categorized summary)")
    tui()


def load_transcript(path: str) -> list[dict]:
    p = Path(path).expanduser()
    if not p.exists():
        log(f"transcript not found: {path}")
        return []
    records = []
    try:
        with p.open("r", errors="replace") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    log(f"skipping malformed transcript line {i}: {e}")
    except Exception as e:
        log(f"failed to read transcript: {e}")
    return records


def _collect_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {})
                inp_str = json.dumps(inp, ensure_ascii=False) if isinstance(inp, (dict, list)) else str(inp)
                if len(inp_str) > 200:
                    inp_str = inp_str[:200] + f"... [+{len(inp_str) - 200} chars]"
                parts.append(f"[tool_use: {name}({inp_str})]")
            elif btype == "tool_result":
                body = block.get("content", "")
                body_str = _collect_text(body) if not isinstance(body, str) else body
                if len(body_str) > TOOL_RESULT_TRUNC:
                    body_str = body_str[:TOOL_RESULT_TRUNC] + f"... [truncated {len(body_str) - TOOL_RESULT_TRUNC} chars]"
                parts.append(f"[tool_result: {body_str}]")
        return "\n".join(p for p in parts if p)
    return ""


def format_transcript(records: list[dict]) -> str:
    lines = []
    for rec in records:
        rtype = rec.get("type")
        msg = rec.get("message") or rec
        role = msg.get("role") if isinstance(msg, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None

        if rtype == "user" or role == "user":
            text = _collect_text(content) if content is not None else ""
            if text.strip():
                lines.append(f"\n── USER ──\n{text}")
        elif rtype == "assistant" or role == "assistant":
            text = _collect_text(content) if content is not None else ""
            if text.strip():
                lines.append(f"\n── ASSISTANT ──\n{text}")
        elif rtype == "system":
            text = _collect_text(content) if content is not None else ""
            if text.strip() and len(text) < 500:
                lines.append(f"\n── SYSTEM ──\n{text}")
    return "\n".join(lines).strip()


def compress_for_llm(text: str) -> tuple[str, bool, str]:
    if len(text) <= MAX_LLM_CHARS:
        return text, False, ""
    dropped = len(text) - MAX_LLM_CHARS
    tail = text[-MAX_LLM_CHARS:]
    nl = tail.find("\n")
    if nl != -1 and nl < 500:
        tail = tail[nl + 1:]
    note = f"[transcript truncated: {dropped} chars from the beginning omitted]"
    return f"{note}\n\n{tail}", True, f"Dropped {dropped} chars from the start to fit LLM window."


def build_analysis_messages(transcript_text: str) -> list[dict]:
    system = (
        "You are analyzing a Claude Code CLI conversation transcript. The user is a "
        "developer deciding whether to let Claude Code auto-compact (summarize) this "
        "conversation. Your job is to help them decide by producing a structured summary.\n\n"
        "Identify the most useful categories FOR THIS SPECIFIC CONVERSATION. Do not use a "
        "fixed taxonomy. Examples that might apply: \"Current task\", \"Files touched\", "
        "\"Decisions made\", \"Open questions\", \"Errors encountered\", \"Next steps\", "
        "\"Context that must survive compaction\". Pick 3 to 7 categories that actually help.\n\n"
        "Output ONLY valid JSON matching this schema — no prose, no markdown fences:\n\n"
        "{\n"
        "  \"categories\": [\n"
        "    {\"name\": \"string (Title Case)\",\n"
        "     \"summary\": \"string (1-2 sentences)\",\n"
        "     \"items\": [\"string (concise bullet)\", \"...\"]}\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Order categories by importance (most-critical-to-preserve first).\n"
        "- Items concise — one line each, no sub-bullets, no markdown.\n"
        "- Do not invent facts. If unsure, omit.\n"
        "- If you see a \"[transcript truncated]\" marker, add a \"Truncation Notice\" category."
    )
    user = (
        "Transcript follows. Analyze it and produce the JSON described.\n\n"
        "---\n"
        f"{transcript_text}\n"
        "---"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def call_llm(messages: list[dict]) -> tuple[bool, str]:
    body = json.dumps({
        "model": MODEL_ID,
        "messages": messages,
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 2000,
    }).encode()
    url = f"{LLM_URL.rstrip('/')}/v1/chat/completions"
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as r:
            raw = r.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
        return True, content
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        log(f"LLM HTTPError {e.code}: {detail}")
        return False, f"HTTP {e.code} from LLM. {detail[:200]}"
    except urllib.error.URLError as e:
        log(f"LLM URLError: {e}")
        return False, f"Cannot reach LLM at {url}: {e.reason}"
    except (socket.timeout, TimeoutError):
        log(f"LLM timeout after {LLM_TIMEOUT_S}s")
        return False, f"LLM timed out after {LLM_TIMEOUT_S}s."
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        log(f"LLM response parse error: {e}")
        return False, f"Could not parse LLM response: {e}"
    except Exception as e:
        log(f"LLM unexpected error: {e}")
        return False, f"Unexpected LLM error: {e}"


def parse_llm_json(raw: str) -> dict:
    s = raw.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(s[start:end + 1])
    raise ValueError("no JSON object found in LLM response")


def show_raw_transcript(text: str) -> None:
    if not text.strip():
        tui("  (transcript is empty)")
        return
    try:
        subprocess.run(
            ["less", "-R"],
            input=text,
            text=True,
            check=False,
            stdin=subprocess.PIPE,
        )
    except FileNotFoundError:
        for i, line in enumerate(text.splitlines()):
            tui(line)
            if (i + 1) % 40 == 0:
                tui_input("  --More-- (press Enter) ")


def show_summary(parsed: dict) -> None:
    cats = parsed.get("categories") if isinstance(parsed, dict) else None
    if not cats or not isinstance(cats, list):
        tui(f"  {YELLOW}LLM returned no categories. Raw:{RESET}")
        tui(json.dumps(parsed, indent=2, ensure_ascii=False))
        return

    tui()
    tui(f"  {BOLD}{GREEN}═══ Analysis Summary ═══{RESET}")
    tui()
    for cat in cats:
        if not isinstance(cat, dict):
            continue
        name = cat.get("name", "(unnamed)")
        summary = cat.get("summary", "")
        items = cat.get("items", []) or []

        tui(f"  {BOLD}{CYAN}▸ {name}{RESET}")
        if summary:
            tui(f"    {DIM}{summary}{RESET}")
        for item in items:
            tui(f"      • {item}")
        tui()

    tui(f"  {DIM}Pick 1/2/3 now that you've seen the summary.{RESET}")
    tui()


def headless_notify(msg: str) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{msg}" with title "ContextPolice"'],
                check=False, capture_output=True, timeout=5,
            )
        elif sys.platform.startswith("linux"):
            subprocess.run(
                ["notify-send", "ContextPolice", msg],
                check=False, capture_output=True, timeout=5,
            )
    except Exception:
        pass


def main() -> None:
    global TTY

    payload = read_payload()
    trigger, transcript_path, cur, maxt = extract_metrics(payload)

    if trigger == "manual":
        emit_decision("allow")
        return

    TTY = open_tty()

    sys.stdout = sys.stderr

    if TTY is None:
        headless_notify("Context limit approaching. Run /compact focus on X.")
        log("auto-compaction blocked (headless)")
        emit_decision(
            "block",
            "Auto-compaction blocked by ContextPolice. Run /compact focus on X to proceed.",
        )
        return

    block_reason = "Auto-compaction blocked by ContextPolice. Run /compact focus on X to proceed."

    while True:
        render_header(cur, maxt)
        render_menu()
        choice = tui_input()

        if choice == "2":
            log("user allowed compaction")
            emit_decision("allow")
            return
        if choice == "3":
            log("user aborted")
            emit_decision("block", "Aborted by user via ContextPolice.")
            return
        if choice == "4":
            if not transcript_path:
                tui(f"  {RED}No transcript_path in hook payload — can't show raw.{RESET}")
                continue
            records = load_transcript(transcript_path)
            if not records:
                tui(f"  {RED}Transcript empty or unreadable: {transcript_path}{RESET}")
                continue
            text = format_transcript(records)
            show_raw_transcript(text)
            continue
        if choice == "5":
            if not transcript_path:
                tui(f"  {RED}No transcript_path in hook payload — can't analyze.{RESET}")
                continue
            records = load_transcript(transcript_path)
            if not records:
                tui(f"  {RED}Transcript empty or unreadable: {transcript_path}{RESET}")
                continue
            text = format_transcript(records)
            compressed, truncated, note = compress_for_llm(text)
            if truncated:
                tui(f"  {YELLOW}Note: {note}{RESET}")
            tui(f"  {DIM}Analyzing with {MODEL_ID}... (up to {LLM_TIMEOUT_S}s){RESET}")
            ok, content = call_llm(build_analysis_messages(compressed))
            if not ok:
                tui(f"  {RED}LLM error: {content}{RESET}")
                continue
            try:
                parsed = parse_llm_json(content)
                show_summary(parsed)
            except Exception as e:
                tui(f"  {YELLOW}Could not parse JSON ({e}). Raw response:{RESET}")
                tui(content)
            continue

        log("auto-compaction blocked by user")
        emit_decision("block", block_reason)
        return


if __name__ == "__main__":
    main()
