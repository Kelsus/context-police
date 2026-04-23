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

PROVIDER = os.environ.get("CONTEXT_POLICE_PROVIDER", "openai").lower()
LLM_URL = os.environ.get("CONTEXT_POLICE_LLM_URL", "http://172.21.0.154:1234")
AWS_REGION = os.environ.get("CONTEXT_POLICE_REGION", "us-east-1")
_DEFAULT_MODEL = (
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    if PROVIDER == "bedrock"
    else "qwen/qwen3-8b"
)
MODEL_ID = os.environ.get("CONTEXT_POLICE_MODEL", _DEFAULT_MODEL)
LLM_TIMEOUT_S = int(os.environ.get("CONTEXT_POLICE_TIMEOUT", "120"))
_DEFAULT_MAX_CHARS = "400000" if PROVIDER == "bedrock" else "8000"
MAX_LLM_CHARS = int(os.environ.get("CONTEXT_POLICE_MAX_CHARS", _DEFAULT_MAX_CHARS))
TOOL_RESULT_TRUNC = int(os.environ.get("CONTEXT_POLICE_TOOL_TRUNC", "500"))
LOG_FILE = Path(os.environ.get(
    "CONTEXT_POLICE_LOG",
    str(Path.home() / ".claude" / "context-police.log"),
))

STATE_DIR = Path.home() / ".claude" / "context-police"
LAST_SUMMARY_PATH = STATE_DIR / "last-summary.json"
LAST_RECO_PATH = STATE_DIR / "last-recommendations.md"
CUSTOM_PROMPT_PATH = STATE_DIR / "extract-prompt.md"
COMPACT_DRAFT_PATH = STATE_DIR / "compact-instructions.draft.md"

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


class _TTYIO:
    def __init__(self, reader, writer):
        self._r = reader
        self._w = writer
    def write(self, s):
        return self._w.write(s)
    def flush(self):
        self._w.flush()
    def readline(self):
        return self._r.readline()
    def close(self):
        for h in (self._r, self._w):
            try:
                h.close()
            except Exception:
                pass


def open_tty():
    # Open read and write handles separately — text-mode "r+" on /dev/tty
    # fails with "not seekable" on some Python builds (e.g. macOS Python 3.9),
    # because TextIOWrapper over a BufferedRandom requires a seekable stream.
    r = w = None
    try:
        r = open("/dev/tty", "r")
        w = open("/dev/tty", "w", buffering=1)
        return _TTYIO(r, w)
    except OSError:
        for h in (r, w):
            if h is not None:
                try:
                    h.close()
                except Exception:
                    pass
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


def render_standalone_menu() -> None:
    tui("  What do you want to do?")
    tui()
    tui(f"  [1]  {CYAN}View raw transcript{RESET}")
    tui(f"  [2]  {CYAN}Analyze with LLM{RESET}      (categorized summary)")
    tui(f"  [q]  Quit                  {DIM}[default]{RESET}")
    tui()


def find_latest_transcript() -> str | None:
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return None

    cwd = os.getcwd()
    encoded = cwd.replace("/", "-")
    candidate_dir = projects_dir / encoded
    if candidate_dir.exists():
        jsonls = list(candidate_dir.glob("*.jsonl"))
        if jsonls:
            jsonls.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return str(jsonls[0])

    all_jsonls = list(projects_dir.glob("*/*.jsonl"))
    if not all_jsonls:
        return None
    all_jsonls.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(all_jsonls[0])


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
    return tail, True, f"Dropped {dropped} chars from the start to fit LLM window."


_DEFAULT_ANALYSIS_SYSTEM_PROMPT = (
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
    "     \"percent_tokens\": 0,\n"
    "     \"items\": [\"string (concise bullet)\", \"...\"]}\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Order categories by importance (most-critical-to-preserve first).\n"
    "- `percent_tokens` is an integer 0–100 estimating what fraction of the transcript's "
    "context budget this category represents. Estimates don't need to sum to 100 (topics "
    "may overlap) — each value expresses the category's individual weight.\n"
    "- Items concise — one line each, no sub-bullets, no markdown.\n"
    "- Do not invent facts. If unsure, omit."
)


def load_custom_system_prompt() -> str | None:
    try:
        if CUSTOM_PROMPT_PATH.exists():
            content = CUSTOM_PROMPT_PATH.read_text().strip()
            return content or None
    except OSError as e:
        log(f"could not read custom prompt at {CUSTOM_PROMPT_PATH}: {e}")
    return None


def build_analysis_messages(transcript_text: str) -> list[dict]:
    system = load_custom_system_prompt() or _DEFAULT_ANALYSIS_SYSTEM_PROMPT
    user = (
        "Analyze the Claude Code session transcript between the markers below. "
        "Produce ONLY the JSON object defined in the system prompt (top-level "
        "\"categories\" array). Do NOT echo any JSON from the transcript. Do NOT "
        "wrap the output in code fences.\n\n"
        "=== TRANSCRIPT START ===\n"
        f"{transcript_text}\n"
        "=== TRANSCRIPT END ===\n\n"
        "Now emit the categorized JSON and nothing else:"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def call_llm(messages: list[dict]) -> tuple[bool, str]:
    if PROVIDER == "bedrock":
        return call_llm_bedrock(messages)
    return call_llm_openai(messages)


def call_llm_openai(messages: list[dict]) -> tuple[bool, str]:
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


def call_llm_bedrock(messages: list[dict]) -> tuple[bool, str]:
    import tempfile

    system_blocks: list[dict] = []
    convo: list[dict] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "system":
            system_blocks.append({"text": content})
        elif role in ("user", "assistant"):
            convo.append({"role": role, "content": [{"text": content}]})

    paths: list[str] = []

    def write_tmp(obj) -> str:
        fd, p = tempfile.mkstemp(suffix=".json", prefix="ctxpolice-")
        os.close(fd)
        with open(p, "w") as f:
            json.dump(obj, f)
        paths.append(p)
        return p

    try:
        msg_path = write_tmp(convo)
        cfg_path = write_tmp({"maxTokens": 2000, "temperature": 0.2})
        cmd = [
            "aws", "bedrock-runtime", "converse",
            "--region", AWS_REGION,
            "--model-id", MODEL_ID,
            "--messages", f"file://{msg_path}",
            "--inference-config", f"file://{cfg_path}",
        ]
        if system_blocks:
            cmd += ["--system", f"file://{write_tmp(system_blocks)}"]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=LLM_TIMEOUT_S,
            )
        except FileNotFoundError:
            return False, "aws CLI not found — install it and configure credentials."
        except subprocess.TimeoutExpired:
            return False, f"Bedrock call timed out after {LLM_TIMEOUT_S}s."
    finally:
        for p in paths:
            try:
                os.unlink(p)
            except Exception:
                pass

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).strip() or "(no stderr)"
        log(f"Bedrock aws CLI exit {proc.returncode}: {err[:500]}")
        return False, f"aws exited {proc.returncode}: {err[:400]}"

    try:
        data = json.loads(proc.stdout)
        blocks = data.get("output", {}).get("message", {}).get("content", [])
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
        if not text:
            return False, f"Empty Bedrock response: {proc.stdout[:400]}"
        return True, text
    except json.JSONDecodeError as e:
        return False, f"Bedrock response not JSON ({e}): {proc.stdout[:400]}"


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

    tui()


def action_view_raw(transcript_path: str | None) -> None:
    if not transcript_path:
        tui(f"  {RED}No transcript available.{RESET}")
        return
    records = load_transcript(transcript_path)
    if not records:
        tui(f"  {RED}Transcript empty or unreadable: {transcript_path}{RESET}")
        return
    show_raw_transcript(format_transcript(records))


def action_analyze(transcript_path: str | None) -> None:
    if not transcript_path:
        tui(f"  {RED}No transcript available.{RESET}")
        return
    records = load_transcript(transcript_path)
    if not records:
        tui(f"  {RED}Transcript empty or unreadable: {transcript_path}{RESET}")
        return
    text = format_transcript(records)
    compressed, truncated, note = compress_for_llm(text)
    if truncated:
        tui(f"  {YELLOW}Note: {note}{RESET}")
    tui(f"  {DIM}Analyzing with {MODEL_ID}... (up to {LLM_TIMEOUT_S}s){RESET}")
    ok, content = call_llm(build_analysis_messages(compressed))
    if not ok:
        tui(f"  {RED}LLM error: {content}{RESET}")
        return
    try:
        parsed = parse_llm_json(content)
        show_summary(parsed)
    except Exception as e:
        tui(f"  {YELLOW}Could not parse JSON ({e}). Raw response:{RESET}")
        tui(content)


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


def render_bar(pct: int, width: int = 20) -> str:
    pct = max(0, min(100, int(pct)))
    filled = (pct * width + 50) // 100  # rounded
    return "█" * filled + "░" * (width - filled)


def render_summary_plain(parsed: dict) -> None:
    """ANSI-free version of show_summary for non-interactive callers."""
    cats = parsed.get("categories") if isinstance(parsed, dict) else None
    if not cats or not isinstance(cats, list):
        print("LLM returned no categories. Raw payload:")
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        return
    print()
    print("=== Context Analysis ===")
    print()
    for cat in cats:
        if not isinstance(cat, dict):
            continue
        name = cat.get("name", "(unnamed)")
        summary = cat.get("summary", "")
        items = cat.get("items", []) or []
        pct = cat.get("percent_tokens")
        print(f"# {name}")
        if isinstance(pct, (int, float)):
            print(f"  {render_bar(int(pct))}  {int(pct)}% of transcript")
        if summary:
            print(f"  {summary}")
        for item in items:
            print(f"  - {item}")
        print()


def save_last_summary(parsed: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_SUMMARY_PATH.write_text(
            json.dumps(parsed, indent=2, ensure_ascii=False)
        )
    except OSError as e:
        log(f"could not save last summary: {e}")


def load_last_summary() -> dict | None:
    try:
        if LAST_SUMMARY_PATH.exists():
            return json.loads(LAST_SUMMARY_PATH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log(f"could not load last summary: {e}")
    return None


def build_recommendations_messages(transcript_text: str, current_prompt: str) -> list[dict]:
    system = (
        "You are a Claude Code assistant reviewing a session transcript and improving "
        "the system prompt used to extract categorized summaries from it.\n\n"
        "Produce two things grounded in THIS specific transcript:\n"
        "  (1) 3–7 concrete recommendations to reduce context-window usage\n"
        "  (2) A full replacement for the extraction system prompt that integrates the "
        "recommendations where they affect summarization behavior.\n\n"
        "Output ONLY a single valid JSON object, no markdown fences, matching:\n\n"
        "{\n"
        "  \"recommendations\": [\"imperative one-line bullet\", \"...\"],\n"
        "  \"revised_prompt\": \"standalone replacement for the extraction system prompt\"\n"
        "}\n\n"
        "Rules:\n"
        "- Each recommendation points at something specific in the transcript (a tool "
        "call, file, topic, or pattern). No generic advice.\n"
        "- `revised_prompt` must be self-contained. It MUST keep the JSON schema with "
        "`categories`, each having `name`, `summary`, `percent_tokens`, and `items`. "
        "Fold in applicable recommendations (e.g., category examples, truncation rules, "
        "ordering guidance).\n"
        "- Do not wrap the JSON in code fences."
    )
    user = (
        "Current extraction system prompt (between markers):\n\n"
        "=== CURRENT PROMPT START ===\n"
        f"{current_prompt}\n"
        "=== CURRENT PROMPT END ===\n\n"
        "Session transcript follows (between markers):\n\n"
        "=== TRANSCRIPT START ===\n"
        f"{transcript_text}\n"
        "=== TRANSCRIPT END ===\n\n"
        "Now emit the JSON object:"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def save_last_recommendations(text: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAST_RECO_PATH.write_text(text)
    except OSError as e:
        log(f"could not save last recommendations: {e}")


def render_menu_static() -> None:
    """Print the inspector menu as plain text to stdout, no input loop.
    Intended for display inside Claude Code's chat (Bash tool has no TTY)."""
    transcript_path = find_latest_transcript() or "(none found)"
    custom = "(custom prompt)" if CUSTOM_PROMPT_PATH.exists() else "(default prompt)"
    cached = "yes" if LAST_SUMMARY_PATH.exists() else "no"
    draft = "yes" if PROMPT_DRAFT_PATH.exists() else "no"
    lines = [
        "",
        "  ╔══════════════════════════════════════════╗",
        "  ║      ContextPolice — Inspector           ║",
        "  ╚══════════════════════════════════════════╝",
        "",
        f"  Transcript: {transcript_path}",
        f"  Prompt: {custom}    Cached summary: {cached}    Draft: {draft}",
        "",
        "  What do you want to do?",
        "",
        "  [1]  LLM analysis (Bedrock Sonnet 4.5)    categories + token bars",
        "  [2]  LLM analysis (local LM Studio)       categories + token bars",
        "  [3]  Raw transcript                       dump formatted, as-is",
        "  [4]  Recommendations + prompt rewrite     preview a revised prompt",
        "  [5]  Edit summarization prompt            seed/override the system prompt",
        "  [6]  View last cached summary             no new LLM call",
        "  [q]  Quit",
        "",
        "  After [4] you can reply 'a' apply / 'e' edit / 'd' discard the draft.",
        "",
    ]
    sys.stdout.write("\n".join(lines) + "\n")
    sys.stdout.flush()


def run_view_last_summary() -> None:
    parsed = load_last_summary()
    if parsed is None:
        print(
            "No cached summary found. Run option 1 or 2 first to generate one.",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"(cached summary from {LAST_SUMMARY_PATH})", file=sys.stderr)
    render_summary_plain(parsed)


def run_edit_prompt() -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if not CUSTOM_PROMPT_PATH.exists() or CUSTOM_PROMPT_PATH.read_text().strip() == "":
            CUSTOM_PROMPT_PATH.write_text(_DEFAULT_ANALYSIS_SYSTEM_PROMPT + "\n")
            seeded = True
        else:
            seeded = False
    except OSError as e:
        print(f"ContextPolice: could not prepare prompt file: {e}", file=sys.stderr)
        sys.exit(1)

    action = "Seeded with the default prompt" if seeded else "Existing custom prompt detected"
    print()
    print("=== Custom summarization prompt ===")
    print()
    print(f"  Path: {CUSTOM_PROMPT_PATH}")
    print(f"  {action}.")
    print()
    print("  Edit the file with any editor — its contents REPLACE the default system")
    print("  prompt used by options 1 and 2. Delete the file (or empty it) to restore")
    print("  the built-in prompt.")
    print()
    print("  Quick open:")
    print(f"    code \"{CUSTOM_PROMPT_PATH}\"")
    print(f"    open -a TextEdit \"{CUSTOM_PROMPT_PATH}\"")
    print(f"    $EDITOR \"{CUSTOM_PROMPT_PATH}\"")
    print()


def run_apply_draft() -> None:
    if not PROMPT_DRAFT_PATH.exists():
        print(
            "No draft found. Run option [4] first to generate one.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        content = PROMPT_DRAFT_PATH.read_text()
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CUSTOM_PROMPT_PATH.write_text(content)
        PROMPT_DRAFT_PATH.unlink()
    except OSError as e:
        print(f"ContextPolice: could not apply draft: {e}", file=sys.stderr)
        sys.exit(1)
    print()
    print("=== Draft applied ===")
    print()
    print(f"  Custom prompt: {CUSTOM_PROMPT_PATH}")
    print("  Next analysis (options 1 or 2) will use the revised prompt.")
    print("  Draft file removed.")
    print()


def run_edit_draft() -> None:
    if not PROMPT_DRAFT_PATH.exists():
        print(
            "No draft found. Run option [4] first to generate one.",
            file=sys.stderr,
        )
        sys.exit(1)
    print()
    print("=== Draft edit ===")
    print()
    print(f"  Draft path: {PROMPT_DRAFT_PATH}")
    print()
    print("  Open in your editor, save, then reply 'a' to apply or 'd' to discard.")
    print()
    print("  Quick open:")
    print(f"    code \"{PROMPT_DRAFT_PATH}\"")
    print(f"    open -a TextEdit \"{PROMPT_DRAFT_PATH}\"")
    print(f"    $EDITOR \"{PROMPT_DRAFT_PATH}\"")
    print()


def run_discard_draft() -> None:
    if not PROMPT_DRAFT_PATH.exists():
        print()
        print("=== No draft to discard ===")
        print()
        return
    try:
        PROMPT_DRAFT_PATH.unlink()
    except OSError as e:
        print(f"ContextPolice: could not delete draft: {e}", file=sys.stderr)
        sys.exit(1)
    print()
    print("=== Draft discarded ===")
    print()


def run_standalone_noninteractive(mode: str) -> None:
    """No-TTY fallback: produce plain-text output on stdout so a caller
    (Claude Code's Bash tool, a pipe, CI, etc.) can display it."""
    if mode == "menu":
        render_menu_static()
        return
    if mode == "view-last":
        run_view_last_summary()
        return
    if mode == "edit-prompt":
        run_edit_prompt()
        return
    if mode == "apply-draft":
        run_apply_draft()
        return
    if mode == "edit-draft":
        run_edit_draft()
        return
    if mode == "discard-draft":
        run_discard_draft()
        return

    transcript_path = find_latest_transcript()
    if not transcript_path:
        print("ContextPolice: no transcript found under ~/.claude/projects/.",
              file=sys.stderr)
        sys.exit(1)

    records = load_transcript(transcript_path)
    if not records:
        print(f"ContextPolice: transcript empty or unreadable: {transcript_path}",
              file=sys.stderr)
        sys.exit(1)

    text = format_transcript(records)

    if mode == "raw":
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()
        return

    compressed, truncated, note = compress_for_llm(text)
    if truncated:
        print(f"[note] {note}", file=sys.stderr)

    if mode == "recommend":
        current_prompt = load_custom_system_prompt() or _DEFAULT_ANALYSIS_SYSTEM_PROMPT
        print(
            f"[info] asking {MODEL_ID} for recommendations + prompt rewrite "
            f"(up to {LLM_TIMEOUT_S}s)...",
            file=sys.stderr,
        )
        ok, content = call_llm(
            build_recommendations_messages(compressed, current_prompt)
        )
        if not ok:
            print(f"ContextPolice LLM error: {content}", file=sys.stderr)
            sys.exit(1)

        recs: list[str] = []
        revised: str = ""
        try:
            parsed = parse_llm_json(content)
            r = parsed.get("recommendations", [])
            if isinstance(r, list):
                recs = [str(x).strip() for x in r if str(x).strip()]
            revised = str(parsed.get("revised_prompt", "")).strip()
        except Exception as e:
            print(
                f"[warn] could not parse combined JSON ({e}); raw response follows:",
                file=sys.stderr,
            )
            sys.stdout.write(content)
            if not content.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
            return

        recs_md = "\n".join(f"- {b}" for b in recs) + ("\n" if recs else "")
        save_last_recommendations(recs_md)

        draft_saved = False
        if revised:
            try:
                STATE_DIR.mkdir(parents=True, exist_ok=True)
                PROMPT_DRAFT_PATH.write_text(revised + ("" if revised.endswith("\n") else "\n"))
                draft_saved = True
            except OSError as e:
                log(f"could not write prompt draft: {e}")

        print()
        print("=== Recommendations ===")
        print()
        if recs:
            for b in recs:
                print(f"- {b}")
        else:
            print("(none returned)")
        print()
        print("=== Proposed extraction prompt (preview) ===")
        print()
        if revised:
            for line in revised.splitlines():
                print(f"  │ {line}")
            print()
            if draft_saved:
                print(f"  Draft saved at: {PROMPT_DRAFT_PATH}")
        else:
            print("  (no rewrite returned)")
        print()
        print("  What now?")
        print("    [a]  Apply this draft as your custom extraction prompt")
        print("    [e]  Edit the draft before applying")
        print("    [d]  Discard the draft")
        print("    any other reply: leave the draft in place and continue")
        print()
        return

    print(f"[info] analyzing with {MODEL_ID} (up to {LLM_TIMEOUT_S}s)...",
          file=sys.stderr)
    ok, content = call_llm(build_analysis_messages(compressed))
    if not ok:
        print(f"ContextPolice LLM error: {content}", file=sys.stderr)
        sys.exit(1)
    try:
        parsed = parse_llm_json(content)
        save_last_summary(parsed)
        render_summary_plain(parsed)
    except Exception as e:
        print(f"[warn] could not parse JSON ({e}); raw response follows:",
              file=sys.stderr)
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()


def run_standalone(force_mode: str | None = None) -> None:
    global TTY

    if force_mode in (
        "raw", "llm", "menu", "recommend", "view-last",
        "edit-prompt", "apply-draft", "edit-draft", "discard-draft",
    ):
        run_standalone_noninteractive(force_mode)
        return

    TTY = open_tty()
    if TTY is None:
        # No terminal attached (e.g. invoked from Claude Code's Bash tool):
        # degrade to non-interactive LLM analysis on stdout.
        run_standalone_noninteractive("llm")
        return

    sys.stdout = sys.stderr

    transcript_path = find_latest_transcript()
    if not transcript_path:
        tui(f"  {RED}Could not auto-detect a transcript under ~/.claude/projects/.{RESET}")
        sys.exit(1)

    log(f"standalone mode opened, transcript={transcript_path}")

    while True:
        tui()
        tui(f"  {CYAN}╔══════════════════════════════════════════╗{RESET}")
        tui(f"  {CYAN}║{RESET}      {BOLD}ContextPolice — Inspector{RESET}           {CYAN}║{RESET}")
        tui(f"  {CYAN}╚══════════════════════════════════════════╝{RESET}")
        tui()
        tui(f"  Transcript: {DIM}{transcript_path}{RESET}")
        tui()
        render_standalone_menu()
        choice = tui_input()

        if choice == "1":
            action_view_raw(transcript_path)
            continue
        if choice == "2":
            action_analyze(transcript_path)
            continue
        if choice in ("q", "Q", "0", ""):
            sys.exit(0)
        tui(f"  {YELLOW}Unknown choice: {choice!r}{RESET}")


def run_hook() -> None:
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
            action_view_raw(transcript_path)
            continue
        if choice == "5":
            action_analyze(transcript_path)
            continue

        log("auto-compaction blocked by user")
        emit_decision("block", block_reason)
        return


def _apply_bedrock_override() -> None:
    """Switch PROVIDER to bedrock at runtime and re-pick provider-dependent
    defaults, but only for fields the user didn't pin via env vars."""
    global PROVIDER, MODEL_ID, MAX_LLM_CHARS
    PROVIDER = "bedrock"
    if "CONTEXT_POLICE_MODEL" not in os.environ:
        MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    if "CONTEXT_POLICE_MAX_CHARS" not in os.environ:
        MAX_LLM_CHARS = 400000


def main() -> None:
    args = sys.argv[1:]
    if "--bedrock" in args:
        _apply_bedrock_override()
    if "--show" in args:
        force_mode: str | None = None
        if "--menu" in args:
            force_mode = "menu"
        elif "--raw" in args:
            force_mode = "raw"
        elif "--recommend" in args:
            force_mode = "recommend"
        elif "--last-summary" in args:
            force_mode = "view-last"
        elif "--edit-prompt" in args:
            force_mode = "edit-prompt"
        elif "--apply-draft" in args:
            force_mode = "apply-draft"
        elif "--edit-draft" in args:
            force_mode = "edit-draft"
        elif "--discard-draft" in args:
            force_mode = "discard-draft"
        elif "--llm" in args:
            force_mode = "llm"
        run_standalone(force_mode)
        return
    run_hook()


if __name__ == "__main__":
    main()
