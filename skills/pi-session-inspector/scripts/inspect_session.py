#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Locate and inspect pi-coding-agent session logs.

pi-coding-agent (`@earendil-works/pi-coding-agent`) persists each session as a
newline-delimited JSON file under ``~/.pi/agent/sessions/<slug>/<iso>_<uuid>.jsonl``.
That raw JSONL is the source of truth. The optional ``recorder`` extension
(aldoborrero/pi-agent-kit) also maintains a derived analytics cache at
``~/.pi/agent/recorder.db`` from live runtime events.

This tool keeps the sibling inspector contract: raw JSONL is the source of truth
and works on its own; ``recorder.db`` is an optional read-only accelerator and the
only source of two metrics the JSONL cannot provide (precise per-turn/per-tool
``duration_ms`` and turn/iteration grouping). The DB is always opened read-only;
this tool never writes to it.

Verbs: locate, list, summary, records, subagents. Global flags: --json, --profile.
Run with ``uv run --python 3.14 scripts/inspect_session.py <verb>``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date as date_cls
from pathlib import Path
from typing import Any, Iterable, Sequence

# --- Constants ----------------------------------------------------------------

# pi message roles (verified against live session JSONL).
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL_RESULT = "toolResult"

# Assistant content block types (verified): text, thinking, toolCall.
BLOCK_TEXT = "text"
BLOCK_THINKING = "thinking"
BLOCK_TOOL_CALL = "toolCall"

# Record types observed across the live corpus.
KNOWN_RECORD_TYPES = (
    "session",
    "message",
    "model_change",
    "thinking_level_change",
    "custom",
    "custom_message",
    "compaction",
)

SUBAGENT_TOOL_NAME = "subagent"
GITHUB_PR_RE = re.compile(r"https?://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
FILENAME_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T[\d-]+Z)_(?P<uuid>[0-9a-fA-F-]+)\.jsonl$")
SCHEMA_VERSION = "session_inspector_v2"
SOURCE = "pi_coding_agent"


# --- Path resolution ----------------------------------------------------------


@dataclass(frozen=True)
class PiPaths:
    pi_home: Path
    sessions_dir: Path
    recorder_db: Path
    agents_dir: Path
    settings_path: Path


def resolve_paths(pi_home: Path | None) -> PiPaths:
    """Resolve pi state locations. Honors --pi-home, then $PI_CODING_AGENT_DIR, then ~/.pi/agent.

    PI_CODING_AGENT_DIR is pi's own override (config.ts `ENV_AGENT_DIR`); the default is
    `~/.pi/agent` (config.ts `getAgentDir`)."""
    if pi_home is not None:
        root = pi_home.expanduser()
    elif os.environ.get("PI_CODING_AGENT_DIR"):
        root = Path(os.environ["PI_CODING_AGENT_DIR"]).expanduser()
    else:
        root = Path.home() / ".pi" / "agent"
    return PiPaths(
        pi_home=root,
        sessions_dir=root / "sessions",
        recorder_db=root / "recorder.db",
        agents_dir=root / "agents",
        settings_path=root / "settings.json",
    )


# --- Session file discovery ---------------------------------------------------


@dataclass(frozen=True)
class SessionFile:
    path: Path
    project_slug: str
    session_id: str
    filename_ts: str | None  # ISO-ish, derived from filename
    day: str | None  # YYYY-MM-DD


def _filename_ts_to_iso(raw: str | None) -> str | None:
    """`2026-06-08T17-02-28-913Z` -> `2026-06-08T17:02:28.913Z`."""
    if not raw:
        return None
    m = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2})-(\d{2})-(\d{2})-(\d{3})Z$", raw)
    if not m:
        return raw
    d, hh, mm, ss, ms = m.groups()
    return f"{d}T{hh}:{mm}:{ss}.{ms}Z"


def parse_session_filename(path: Path) -> tuple[str | None, str | None, str | None]:
    """Return (session_id, iso_timestamp, day) parsed from the filename."""
    m = FILENAME_RE.match(path.name)
    if not m:
        return None, None, None
    raw_ts = m.group("ts")
    return m.group("uuid"), _filename_ts_to_iso(raw_ts), raw_ts[:10]


def iter_session_files(paths: PiPaths) -> list[SessionFile]:
    if not paths.sessions_dir.is_dir():
        return []
    out: list[SessionFile] = []
    for f in paths.sessions_dir.glob("*/*.jsonl"):
        if not f.is_file():
            continue
        sid, iso, day = parse_session_filename(f)
        out.append(
            SessionFile(
                path=f,
                project_slug=f.parent.name,
                session_id=sid or f.stem,
                filename_ts=iso,
                day=day,
            )
        )
    out.sort(key=lambda s: (s.filename_ts or "", s.path.name), reverse=True)
    return out


def project_label(slug: str) -> str:
    """Strip the leading/trailing `--` wrapper from a slug dir for display."""
    return slug.strip("-")


# --- JSONL loading ------------------------------------------------------------


def load_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Read a session JSONL file. Returns (records, parse_errors). Tolerant of bad lines."""
    records: list[dict[str, Any]] = []
    errors = 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise SystemExit(f"ERROR: cannot read {path}: {exc}")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            errors += 1
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            errors += 1
    return records, errors


def extract_text(content: Any) -> str:
    """Join `text` blocks from a content array."""
    if not isinstance(content, list):
        return ""
    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == BLOCK_TEXT]
    return "\n".join(p for p in parts if p)


def _truncate(text: str | None, limit: int = 280) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + " […]"


# --- recorder.db (read-only) --------------------------------------------------


def open_recorder_ro(db_path: Path) -> sqlite3.Connection | None:
    """Open recorder.db strictly read-only. Returns None if absent/unreadable."""
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON;")
        # Touch a table to confirm it is a usable recorder DB.
        conn.execute("SELECT 1 FROM sessions LIMIT 1;")
        return conn
    except sqlite3.Error:
        return None


def db_session_row(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    try:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?;", (session_id,)).fetchone()
    except sqlite3.Error:
        return None
    return dict(row) if row else None


def db_turn_durations(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    try:
        rows = conn.execute(
            "SELECT turn_index, iteration_number, duration_ms, stop_reason, model_id "
            "FROM turns WHERE session_id = ? ORDER BY turn_index, iteration_number;",
            (session_id,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    durations = [r["duration_ms"] for r in rows if r["duration_ms"] is not None]
    return {
        "iterations": len(rows),
        "completed": sum(1 for r in rows if r["duration_ms"] is not None),
        "total_duration_ms": sum(durations) if durations else None,
        "max_duration_ms": max(durations) if durations else None,
        "turns": [dict(r) for r in rows],
    }


def db_tool_durations(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT tool_name, COUNT(*) calls, SUM(is_error) errors, "
            "ROUND(AVG(duration_ms)) avg_ms, MAX(duration_ms) max_ms "
            "FROM tool_calls WHERE session_id = ? GROUP BY tool_name ORDER BY calls DESC;",
            (session_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def db_null_file_sessions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Sessions with NULL session_file are subagent subprocesses (spawned --no-session)."""
    try:
        rows = conn.execute(
            "SELECT id, cwd, started_at, model_id, total_input_tokens, total_output_tokens "
            "FROM sessions WHERE session_file IS NULL ORDER BY started_at;",
        ).fetchall()
    except sqlite3.Error:
        return []
    return [dict(r) for r in rows]


def db_row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in ("sessions", "turns", "tool_calls", "messages", "model_changes"):
        try:
            counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
        except sqlite3.Error:
            counts[table] = -1
    return counts


# --- Session summarization (stateless JSONL parse) ----------------------------


@dataclass
class SessionSummary:
    path: Path
    session_id: str
    project_slug: str
    project: str
    cwd: str | None = None
    format_version: Any = None
    filename_ts: str | None = None
    session_ts: str | None = None
    last_ts: str | None = None
    model_provider: str | None = None
    model_id: str | None = None
    thinking_level: str | None = None
    first_user_message: str | None = None
    record_counts: Counter = field(default_factory=Counter)
    parse_errors: int = 0
    # messages
    user_message_count: int = 0
    assistant_message_count: int = 0
    tool_result_count: int = 0
    thinking_block_count: int = 0
    # tokens (per-message, summable)
    tok_input: int = 0
    tok_output: int = 0
    tok_cache_read: int = 0
    tok_cache_write: int = 0
    tok_total: int = 0
    cost_total: float = 0.0
    # breakdowns
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    model_changes: list[dict[str, Any]] = field(default_factory=list)
    thinking_level_changes: list[dict[str, Any]] = field(default_factory=list)
    stop_reasons: Counter = field(default_factory=Counter)
    tool_calls: Counter = field(default_factory=Counter)
    tool_errors: Counter = field(default_factory=Counter)
    custom_types: Counter = field(default_factory=Counter)
    custom_message_types: Counter = field(default_factory=Counter)
    compactions: list[dict[str, Any]] = field(default_factory=list)
    subagent_invocations: list[dict[str, Any]] = field(default_factory=list)
    pr_links: list[str] = field(default_factory=list)


def _accumulate_model(summary: SessionSummary, model: str | None, usage: dict[str, Any]) -> None:
    key = model or "(unknown)"
    bucket = summary.by_model.setdefault(
        key, {"model": key, "responses": 0, "input": 0, "output": 0, "total": 0, "cost": 0.0}
    )
    bucket["responses"] += 1
    bucket["input"] += int(usage.get("input") or 0)
    bucket["output"] += int(usage.get("output") or 0)
    bucket["total"] += int(usage.get("totalTokens") or 0)
    cost = usage.get("cost")
    if isinstance(cost, dict):
        bucket["cost"] += float(cost.get("total") or 0.0)


def summarize_session(sf: SessionFile, records: list[dict[str, Any]], parse_errors: int) -> SessionSummary:
    s = SessionSummary(
        path=sf.path,
        session_id=sf.session_id,
        project_slug=sf.project_slug,
        project=project_label(sf.project_slug),
        filename_ts=sf.filename_ts,
        parse_errors=parse_errors,
    )
    tool_call_names: dict[str, str] = {}  # toolCallId -> name (from assistant toolCall blocks)

    for rec in records:
        rtype = rec.get("type")
        s.record_counts[rtype or "(none)"] += 1
        ts = rec.get("timestamp")
        if isinstance(ts, str):
            s.last_ts = ts

        if rtype == "session":
            s.cwd = rec.get("cwd")
            s.format_version = rec.get("version")
            s.session_ts = rec.get("timestamp")

        elif rtype == "model_change":
            entry = {
                "provider": rec.get("provider"),
                "modelId": rec.get("modelId"),
                "timestamp": rec.get("timestamp"),
            }
            s.model_changes.append(entry)
            if s.model_provider is None:
                s.model_provider = rec.get("provider")
                s.model_id = rec.get("modelId")

        elif rtype == "thinking_level_change":
            s.thinking_level_changes.append(
                {"thinkingLevel": rec.get("thinkingLevel"), "timestamp": rec.get("timestamp")}
            )
            s.thinking_level = rec.get("thinkingLevel")

        elif rtype == "custom":
            s.custom_types[rec.get("customType") or "(none)"] += 1

        elif rtype == "custom_message":
            s.custom_message_types[rec.get("customType") or "(none)"] += 1

        elif rtype == "compaction":
            s.compactions.append(
                {
                    "timestamp": rec.get("timestamp"),
                    "tokensBefore": rec.get("tokensBefore"),
                    "firstKeptEntryId": rec.get("firstKeptEntryId"),
                    "fromHook": rec.get("fromHook"),
                    "summary": _truncate(rec.get("summary"), 200),
                }
            )

        elif rtype == "message":
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")

            if role == ROLE_USER:
                s.user_message_count += 1
                user_text = extract_text(content)
                if s.first_user_message is None:
                    s.first_user_message = _truncate(user_text, 500)
                _collect_pr_links(s, user_text)

            elif role == ROLE_ASSISTANT:
                s.assistant_message_count += 1
                if msg.get("provider") and s.model_provider is None:
                    s.model_provider = msg.get("provider")
                stop = msg.get("stopReason")
                if stop is not None:
                    s.stop_reasons[stop] += 1
                usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
                s.tok_input += int(usage.get("input") or 0)
                s.tok_output += int(usage.get("output") or 0)
                s.tok_cache_read += int(usage.get("cacheRead") or 0)
                s.tok_cache_write += int(usage.get("cacheWrite") or 0)
                s.tok_total += int(usage.get("totalTokens") or 0)
                cost = usage.get("cost")
                if isinstance(cost, dict):
                    s.cost_total += float(cost.get("total") or 0.0)
                _accumulate_model(s, msg.get("model"), usage)
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == BLOCK_THINKING:
                            s.thinking_block_count += 1
                        elif btype == BLOCK_TOOL_CALL:
                            name = block.get("name") or "(unknown)"
                            s.tool_calls[name] += 1
                            cid = block.get("id")
                            if cid is not None:
                                tool_call_names[str(cid)] = name
                        elif btype == BLOCK_TEXT:
                            _collect_pr_links(s, block.get("text"))

            elif role == ROLE_TOOL_RESULT:
                s.tool_result_count += 1
                tool_name = msg.get("toolName") or tool_call_names.get(str(msg.get("toolCallId"))) or "(unknown)"
                if msg.get("isError"):
                    s.tool_errors[tool_name] += 1
                _collect_pr_links(s, extract_text(content))
                if tool_name == SUBAGENT_TOOL_NAME:
                    _collect_subagents(s, msg)

    return s


def _collect_pr_links(s: SessionSummary, text: str | None) -> None:
    if not text:
        return
    for m in GITHUB_PR_RE.findall(text):
        if m not in s.pr_links:
            s.pr_links.append(m)


def _collect_subagents(s: SessionSummary, msg: dict[str, Any]) -> None:
    """Parse a `subagent` toolResult's details.results[] (the sole clean subagent source)."""
    details = msg.get("details")
    if not isinstance(details, dict):
        return
    mode = details.get("mode")
    results = details.get("results")
    if not isinstance(results, list):
        return
    for r in results:
        if not isinstance(r, dict):
            continue
        usage = r.get("usage") if isinstance(r.get("usage"), dict) else {}
        # Tool calls made by the subagent itself, recovered from its nested messages.
        child_tools: Counter = Counter()
        for cm in r.get("messages", []) if isinstance(r.get("messages"), list) else []:
            if not isinstance(cm, dict) or cm.get("role") != ROLE_ASSISTANT:
                continue
            for block in cm.get("content", []) if isinstance(cm.get("content"), list) else []:
                if isinstance(block, dict) and block.get("type") == BLOCK_TOOL_CALL:
                    child_tools[block.get("name") or "(unknown)"] += 1
        s.subagent_invocations.append(
            {
                "mode": mode,
                "agent": r.get("agent"),
                "agent_source": r.get("agentSource"),
                "model": r.get("model"),
                "stop_reason": r.get("stopReason"),
                "exit_code": r.get("exitCode"),
                "step": r.get("step"),
                "task": _truncate(r.get("task"), 200),
                "error_message": _truncate(r.get("errorMessage"), 200),
                "usage": {
                    "input": usage.get("input"),
                    "output": usage.get("output"),
                    "cache_read": usage.get("cacheRead"),
                    "cache_write": usage.get("cacheWrite"),
                    "cost": usage.get("cost"),
                    "context_tokens": usage.get("contextTokens"),
                    "turns": usage.get("turns"),
                },
                "tool_calls": dict(child_tools),
            }
        )


# --- Quick scan for `list` (one pass, JSONL is the floor) ---------------------


def quick_scan(sf: SessionFile) -> dict[str, Any]:
    records, errors = load_records(sf.path)
    s = summarize_session(sf, records, errors)
    return {
        "session_id": s.session_id,
        "day": sf.day,
        "timestamp": s.session_ts or s.filename_ts,
        "project": s.project,
        "cwd": s.cwd,
        "model": s.model_id,
        "model_provider": s.model_provider,
        "assistant_responses": s.assistant_message_count,
        "input_tokens": s.tok_input,
        "output_tokens": s.tok_output,
        "total_tokens": s.tok_total,
        "cost": round(s.cost_total, 6),
        "tool_calls": sum(s.tool_calls.values()),
        "tool_errors": sum(s.tool_errors.values()),
        "subagents": len(s.subagent_invocations),
        "path": str(sf.path),
    }


# --- Target resolution --------------------------------------------------------


def resolve_target(
    paths: PiPaths, target: str | None, project: str | None
) -> SessionFile:
    files = iter_session_files(paths)
    if project:
        files = [f for f in files if project.lower() in f.project_slug.lower() or project.lower() in (f.session_id or "").lower()]
    if target:
        # Direct path?
        tp = Path(target).expanduser()
        if tp.is_file():
            sid, iso, day = parse_session_filename(tp)
            return SessionFile(tp, tp.parent.name, sid or tp.stem, iso, day)
        # Session id (full or prefix)?
        matches = [f for f in iter_session_files(paths) if f.session_id == target or f.session_id.startswith(target)]
        if matches:
            return matches[0]
        raise SystemExit(f"ERROR: no session matches target '{target}'")
    if not files:
        raise SystemExit("ERROR: no pi session files found. Try `locate` to confirm paths.")
    return files[0]


# --- Ingestion profile (session_inspector_v2) ---------------------------------


def build_ingestion(s: SessionSummary, db_turns: dict[str, Any] | None, kind: str) -> dict[str, Any]:
    model_entries = [
        {"model": b["model"], "responses": b["responses"], "input": b["input"], "output": b["output"], "total": b["total"], "cost": round(b["cost"], 6)}
        for b in sorted(s.by_model.values(), key=lambda b: b["total"], reverse=True)
    ]
    tool_entries = [
        {"name": name, "calls": calls, "errors": s.tool_errors.get(name, 0)}
        for name, calls in s.tool_calls.most_common()
    ]
    turns_block: dict[str, Any]
    if db_turns:
        turns_block = {
            "source": "recorder.db",
            "iterations": db_turns.get("iterations"),
            "completed": db_turns.get("completed"),
            "total_duration_ms": db_turns.get("total_duration_ms"),
            "max_duration_ms": db_turns.get("max_duration_ms"),
        }
    else:
        turns_block = {
            "source": "jsonl_approx",
            "iterations": s.assistant_message_count,
            "completed": None,
            "total_duration_ms": None,
            "max_duration_ms": None,
            "note": "Precise turn/iteration durations require recorder.db; JSONL has no turn boundaries.",
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "kind": kind,
        "session": {
            "id": s.session_id,
            "path": str(s.path),
            "project": s.project,
            "cwd": s.cwd,
            "timestamp": s.session_ts or s.filename_ts,
            "display_name": s.project,
            "version": s.format_version,
            "model_provider": s.model_provider,
            "model": s.model_id,
            "thinking_level": s.thinking_level,
            "is_subagent": False,
            "parent_session_id": None,
        },
        "content": {
            "first_user_message": s.first_user_message,
        },
        "counts": {
            "records": sum(s.record_counts.values()),
            "parse_errors": s.parse_errors,
            "user_messages": s.user_message_count,
            "assistant_responses": s.assistant_message_count,
            "tool_results": s.tool_result_count,
            "thinking_blocks": s.thinking_block_count,
            "compactions": len(s.compactions),
            "tool_error_count": sum(s.tool_errors.values()),
            "by_record_type": [{"type": k, "count": v} for k, v in s.record_counts.most_common()],
            "stop_reasons": [{"reason": k, "count": v} for k, v in s.stop_reasons.most_common()],
            "custom_types": [{"type": k, "count": v} for k, v in s.custom_types.most_common()],
            "custom_message_types": [{"type": k, "count": v} for k, v in s.custom_message_types.most_common()],
        },
        "usage": {
            "models": model_entries,
            "tokens": {
                "mode": "per_message",
                "input": s.tok_input,
                "output": s.tok_output,
                "cache_read": s.tok_cache_read,
                "cache_write": s.tok_cache_write,
                "total": s.tok_total,
                "cost": round(s.cost_total, 6),
                "api_calls_exact": s.assistant_message_count,
                "note": "Cost is pi-computed (usage.cost.total); 0 for local providers. Cache tokens are JSONL-only (recorder.db drops them).",
            },
            "tools": tool_entries,
        },
        "turns": turns_block,
        "links": {"prs": list(s.pr_links)},
        "subagents": s.subagent_invocations,
    }


# --- Output helpers -----------------------------------------------------------


def emit_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


# --- Commands -----------------------------------------------------------------


def cmd_locate(paths: PiPaths, args: argparse.Namespace) -> int:
    files = iter_session_files(paths)
    conn = open_recorder_ro(paths.recorder_db)
    db_info: dict[str, Any] = {
        "path": str(paths.recorder_db),
        "present": paths.recorder_db.exists(),
        "readable_read_only": conn is not None,
    }
    if conn is not None:
        db_info["row_counts"] = db_row_counts(conn)
        db_info["subagent_subprocess_rows"] = len(db_null_file_sessions(conn))
        conn.close()

    settings: dict[str, Any] = {}
    recorder_enabled: bool | None = None
    if paths.settings_path.is_file():
        try:
            raw = json.loads(paths.settings_path.read_text(encoding="utf-8"))
            settings = {
                "defaultProvider": raw.get("defaultProvider"),
                "defaultModel": raw.get("defaultModel"),
                "defaultThinkingLevel": raw.get("defaultThinkingLevel"),
            }
            recorder_enabled = _recorder_enabled(raw)
        except (json.JSONDecodeError, OSError):
            settings = {"error": "could not parse settings.json"}

    agents: list[str] = []
    if paths.agents_dir.is_dir():
        agents = sorted(p.stem for p in paths.agents_dir.glob("*.md"))

    projects = sorted({project_label(f.project_slug) for f in files})
    payload = {
        "pi_home": str(paths.pi_home),
        "sessions_dir": str(paths.sessions_dir),
        "sessions_dir_exists": paths.sessions_dir.is_dir(),
        "session_file_count": len(files),
        "project_count": len(projects),
        "projects": projects,
        "latest_session": str(files[0].path) if files else None,
        "recorder_db": db_info,
        "recorder_extension_enabled": recorder_enabled,
        "settings": settings,
        "subagent_definitions": agents,
        "agents_dir": str(paths.agents_dir),
    }
    if args.json:
        emit_json(payload)
    else:
        print(f"pi_home:            {payload['pi_home']}")
        print(f"sessions_dir:       {payload['sessions_dir']} (exists={payload['sessions_dir_exists']})")
        print(f"session files:      {payload['session_file_count']} across {payload['project_count']} projects")
        print(f"latest session:     {payload['latest_session']}")
        print(f"recorder.db:        {db_info['path']}")
        print(f"  present:          {db_info['present']}")
        print(f"  read-only ok:     {db_info['readable_read_only']}")
        if "row_counts" in db_info:
            rc = db_info["row_counts"]
            print(f"  rows:             sessions={rc.get('sessions')} turns={rc.get('turns')} tool_calls={rc.get('tool_calls')} messages={rc.get('messages')} model_changes={rc.get('model_changes')}")
            print(f"  subagent rows:    {db_info['subagent_subprocess_rows']} (NULL session_file)")
        print(f"recorder enabled:   {recorder_enabled}")
        print(f"default model:      {settings.get('defaultProvider')}/{settings.get('defaultModel')}")
        print(f"subagent defs:      {', '.join(agents) or '(none)'}")
        print(f"projects:           {', '.join(projects) or '(none)'}")
    return 0


def _recorder_enabled(raw: dict[str, Any]) -> bool | None:
    """Best-effort: is the recorder extension loaded? pi-agent-kit must be present and
    recorder must not be excluded via a `!extensions/recorder/**` glob."""
    packages = raw.get("packages")
    if not isinstance(packages, list):
        return None
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        src = str(pkg.get("source", ""))
        if "pi-agent-kit" not in src:
            continue
        exclusions = pkg.get("extensions")
        if isinstance(exclusions, list):
            for pat in exclusions:
                if isinstance(pat, str) and "recorder" in pat and pat.lstrip().startswith("!"):
                    return False
        return True
    return None


def cmd_list(paths: PiPaths, args: argparse.Namespace) -> int:
    files = iter_session_files(paths)
    if args.project:
        files = [f for f in files if args.project.lower() in f.project_slug.lower()]
    if args.since:
        files = [f for f in files if f.day and f.day >= args.since]
    if args.until:
        files = [f for f in files if f.day and f.day <= args.until]
    files = files[: args.limit]

    conn = open_recorder_ro(paths.recorder_db)
    rows: list[dict[str, Any]] = []
    for sf in files:
        row = quick_scan(sf)
        if conn is not None:
            dbrow = db_session_row(conn, sf.session_id)
            if dbrow and dbrow.get("ended_at") and dbrow.get("started_at"):
                row["duration_min"] = round((dbrow["ended_at"] - dbrow["started_at"]) / 60000.0, 1)
        rows.append(row)
    if conn is not None:
        conn.close()

    if args.profile == "ingestion":
        payload = [
            {
                "schema_version": SCHEMA_VERSION,
                "source": SOURCE,
                "kind": "session_stub",
                "session": {
                    "id": r["session_id"],
                    "path": r["path"],
                    "project": r["project"],
                    "cwd": r["cwd"],
                    "timestamp": r["timestamp"],
                    "model": r["model"],
                    "model_provider": r["model_provider"],
                    "is_subagent": False,
                },
                "usage": {"tokens": {"total": r["total_tokens"], "cost": r["cost"]}},
                "counts": {"tool_calls": r["tool_calls"], "tool_errors": r["tool_errors"], "subagents": r["subagents"]},
            }
            for r in rows
        ]
        emit_json(payload)
        return 0

    if args.json:
        emit_json(rows)
        return 0

    if not rows:
        print("(no sessions)")
        return 0
    print(f"{'DAY':<11} {'MODEL':<22} {'IN':>8} {'OUT':>7} {'$':>8} {'TOOLS':>6} {'SUB':>4}  PROJECT")
    for r in rows:
        print(
            f"{(r['day'] or '?'):<11} {(r['model'] or '?')[:22]:<22} "
            f"{r['input_tokens']:>8} {r['output_tokens']:>7} {r['cost']:>8.4f} "
            f"{r['tool_calls']:>6} {r['subagents']:>4}  {r['project']}"
        )
    print(f"\n{len(rows)} session(s).")
    return 0


def cmd_summary(paths: PiPaths, args: argparse.Namespace) -> int:
    sf = resolve_target(paths, args.target, args.project)
    records, errors = load_records(sf.path)
    s = summarize_session(sf, records, errors)

    conn = open_recorder_ro(paths.recorder_db)
    db_turns: dict[str, Any] | None = None
    db_tools: list[dict[str, Any]] = []
    db_present_for_session = False
    if conn is not None:
        if db_session_row(conn, s.session_id):
            db_present_for_session = True
            db_turns = db_turn_durations(conn, s.session_id)
            db_tools = db_tool_durations(conn, s.session_id)
        conn.close()

    if args.profile == "ingestion":
        emit_json(build_ingestion(s, db_turns, kind="session_summary"))
        return 0

    payload = {
        "session_id": s.session_id,
        "path": str(s.path),
        "project": s.project,
        "cwd": s.cwd,
        "format_version": s.format_version,
        "timestamp": s.session_ts or s.filename_ts,
        "model": f"{s.model_provider}/{s.model_id}" if s.model_id else None,
        "thinking_level": s.thinking_level,
        "first_user_message": s.first_user_message,
        "record_counts": dict(s.record_counts),
        "parse_errors": s.parse_errors,
        "messages": {
            "user": s.user_message_count,
            "assistant_responses": s.assistant_message_count,
            "tool_results": s.tool_result_count,
            "thinking_blocks": s.thinking_block_count,
        },
        "tokens": {
            "input": s.tok_input,
            "output": s.tok_output,
            "cache_read": s.tok_cache_read,
            "cache_write": s.tok_cache_write,
            "total": s.tok_total,
            "cost": round(s.cost_total, 6),
            "api_calls_exact": s.assistant_message_count,
        },
        "by_model": sorted(s.by_model.values(), key=lambda b: b["total"], reverse=True),
        "model_changes": s.model_changes,
        "stop_reasons": dict(s.stop_reasons),
        "tool_calls": dict(s.tool_calls),
        "tool_errors": dict(s.tool_errors),
        "custom_types": dict(s.custom_types),
        "custom_message_types": dict(s.custom_message_types),
        "compactions": s.compactions,
        "subagents": s.subagent_invocations,
        "pr_links": s.pr_links,
        "recorder_db": {
            "matched": db_present_for_session,
            "turn_durations": db_turns,
            "tool_durations": db_tools,
        },
    }
    if args.json:
        emit_json(payload)
        return 0

    _print_summary_text(payload)
    return 0


def _print_summary_text(p: dict[str, Any]) -> None:
    print(f"session:   {p['session_id']}")
    print(f"project:   {p['project']}  ({p['cwd']})")
    print(f"format:    version {p['format_version']}   model {p['model']}   thinking {p['thinking_level']}")
    print(f"started:   {p['timestamp']}")
    print(f"path:      {p['path']}")
    if p["parse_errors"]:
        print(f"parse errors: {p['parse_errors']}")
    print()
    print(f"first user message:\n  {p['first_user_message']}")
    print()
    m = p["messages"]
    print(f"messages:  user={m['user']} assistant_responses={m['assistant_responses']} tool_results={m['tool_results']} thinking_blocks={m['thinking_blocks']}")
    print(f"records:   " + ", ".join(f"{k}={v}" for k, v in p["record_counts"].items()))
    t = p["tokens"]
    print(f"tokens:    in={t['input']} out={t['output']} cacheR={t['cache_read']} cacheW={t['cache_write']} total={t['total']} cost=${t['cost']:.4f} api_calls={t['api_calls_exact']}")
    if p["by_model"]:
        print("models:")
        for b in p["by_model"]:
            print(f"  {b['model']:<28} responses={b['responses']:>3} in={b['input']:>8} out={b['output']:>7} cost=${b['cost']:.4f}")
    if p["stop_reasons"]:
        print(f"stop reasons: " + ", ".join(f"{k}={v}" for k, v in p["stop_reasons"].items()))
    if p["tool_calls"]:
        print("tools:")
        for name, calls in sorted(p["tool_calls"].items(), key=lambda kv: kv[1], reverse=True):
            err = p["tool_errors"].get(name, 0)
            errs = f"  ({err} errors)" if err else ""
            print(f"  {name:<26} {calls:>4}{errs}")
    if p["custom_types"] or p["custom_message_types"]:
        print(f"context:   custom={p['custom_types']}  custom_message={p['custom_message_types']}")
    if p["compactions"]:
        print(f"compactions: {len(p['compactions'])}")
        for c in p["compactions"]:
            print(f"  @ {c['timestamp']}  tokensBefore={c['tokensBefore']}")
    if p["subagents"]:
        print(f"subagents: {len(p['subagents'])}")
        for sa in p["subagents"]:
            u = sa["usage"]
            print(f"  [{sa['mode']}] {sa['agent']} ({sa['model']}) stop={sa['stop_reason']} "
                  f"in={u['input']} out={u['output']} turns={u['turns']} tools={sa['tool_calls']}")
            if sa.get("task"):
                print(f"      task: {sa['task']}")
    if p["pr_links"]:
        print(f"pr links:  {', '.join(p['pr_links'])}")
    rdb = p["recorder_db"]
    if rdb["matched"] and rdb["turn_durations"]:
        td = rdb["turn_durations"]
        print(f"\nrecorder.db (precise durations):")
        print(f"  iterations={td.get('iterations')} completed={td.get('completed')} "
              f"total_duration={td.get('total_duration_ms')}ms max={td.get('max_duration_ms')}ms")
        if rdb["tool_durations"]:
            print("  tool durations (avg/max ms):")
            for tdr in rdb["tool_durations"][:10]:
                print(f"    {tdr['tool_name']:<24} calls={tdr['calls']:>3} avg={tdr['avg_ms']} max={tdr['max_ms']}")
    elif not rdb["matched"]:
        print("\nrecorder.db: no matching row (durations unavailable; JSONL has no turn boundaries).")


def cmd_records(paths: PiPaths, args: argparse.Namespace) -> int:
    sf = resolve_target(paths, args.target, args.project)
    records, _ = load_records(sf.path)
    out = []
    for rec in records:
        if args.record_type and rec.get("type") != args.record_type:
            continue
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else None
        if args.role:
            if not msg or msg.get("role") != args.role:
                continue
        if args.tool_name:
            name = None
            if msg and msg.get("role") == ROLE_TOOL_RESULT:
                name = msg.get("toolName")
            elif msg and msg.get("role") == ROLE_ASSISTANT and isinstance(msg.get("content"), list):
                names = [b.get("name") for b in msg["content"] if isinstance(b, dict) and b.get("type") == BLOCK_TOOL_CALL]
                name = ",".join(n for n in names if n) or None
            if not name or args.tool_name not in name:
                continue
        out.append(rec)
    if args.tail and args.tail > 0:
        out = out[-args.tail :]
    for rec in out:
        print(json.dumps(rec, default=str))
    return 0


def cmd_subagents(paths: PiPaths, args: argparse.Namespace) -> int:
    sf = resolve_target(paths, args.target, args.project)
    records, errors = load_records(sf.path)
    s = summarize_session(sf, records, errors)

    conn = open_recorder_ro(paths.recorder_db)
    null_rows: list[dict[str, Any]] = []
    if conn is not None:
        null_rows = db_null_file_sessions(conn)
        conn.close()

    payload = {
        "session_id": s.session_id,
        "path": str(s.path),
        "subagent_invocations": s.subagent_invocations,
        "count": len(s.subagent_invocations),
        "recorder_db_subprocess_rows": null_rows,
        "note": (
            "Subagents run as separate `pi --no-session` subprocesses and write no child JSONL. "
            "The per-invocation breakdown above is parsed from the parent session's `subagent` "
            "toolResult details.results[] (the sole clean source). recorder.db NULL-session_file "
            "rows corroborate subprocess token usage but are not a reliable parent link "
            "(parallel mode runs concurrent subprocesses). Parallel/chain `results[]` shape is "
            "inferred from the extension source; only single-mode runs were observed live."
        ),
    }
    if args.json or args.profile == "ingestion":
        emit_json(payload)
        return 0

    print(f"session: {s.session_id}")
    print(f"subagent invocations: {payload['count']}")
    for i, sa in enumerate(s.subagent_invocations, 1):
        u = sa["usage"]
        print(f"\n[{i}] mode={sa['mode']} agent={sa['agent']} ({sa['agent_source']}) model={sa['model']}")
        print(f"    stop={sa['stop_reason']} exit={sa['exit_code']} step={sa['step']}")
        print(f"    tokens: in={u['input']} out={u['output']} cost={u['cost']} ctx={u['context_tokens']} turns={u['turns']}")
        if sa["tool_calls"]:
            print(f"    tools: {sa['tool_calls']}")
        if sa.get("task"):
            print(f"    task: {sa['task']}")
        if sa.get("error_message"):
            print(f"    error: {sa['error_message']}")
    if null_rows:
        print(f"\nrecorder.db subprocess rows (NULL session_file, corroboration only): {len(null_rows)}")
    print(f"\n{payload['note']}")
    return 0


# --- CLI ----------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    # Global flags precede the subcommand (matches the sibling inspectors' convention,
    # e.g. `inspect_session.py --json --profile ingestion summary <id>`).
    parser = argparse.ArgumentParser(description="Locate and inspect pi-coding-agent session logs.")
    parser.add_argument("--pi-home", type=Path, default=None,
                        help="Override pi state root. Defaults to $PI_CODING_AGENT_DIR or ~/.pi/agent.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of plain text.")
    parser.add_argument("--profile", choices=("default", "ingestion"), default="default",
                        help="Output profile. `ingestion` emits the normalized session_inspector_v2 shape.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("locate", help="Print pi log locations, recorder.db state, and subagent definitions.")

    lp = sub.add_parser("list", help="List sessions (newest first).")
    lp.add_argument("--since", default=None, help="Keep sessions on or after YYYY-MM-DD.")
    lp.add_argument("--until", default=None, help="Keep sessions on or before YYYY-MM-DD.")
    lp.add_argument("--project", default=None, help="Filter by project/slug substring.")
    lp.add_argument("--limit", type=int, default=20, help="Maximum results.")

    spp = sub.add_parser("summary", help="Summarize a session by path or id. Defaults to the latest.")
    spp.add_argument("target", nargs="?", help="Session path or id. Latest matching if omitted.")
    spp.add_argument("--project", default=None, help="Filter when selecting the default session.")

    rp = sub.add_parser("records", help="Print raw matching JSONL records (stateless, JSONL-only).")
    rp.add_argument("target", nargs="?", help="Session path or id. Latest matching if omitted.")
    rp.add_argument("--project", default=None, help="Filter when selecting the default session.")
    rp.add_argument("--record-type", dest="record_type", default=None, help="Filter by top-level type (message, model_change, compaction, …).")
    rp.add_argument("--role", default=None, help="Filter message records by role (user, assistant, toolResult).")
    rp.add_argument("--tool-name", dest="tool_name", default=None, help="Filter by tool name (toolCall/toolResult).")
    rp.add_argument("--tail", type=int, default=20, help="Return only the last N matching records.")

    sap = sub.add_parser("subagents", help="Inspect subagent invocations parsed from the parent session.")
    sap.add_argument("target", nargs="?", help="Session path or id. Latest matching if omitted.")
    sap.add_argument("--project", default=None, help="Filter when selecting the default session.")

    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    paths = resolve_paths(args.pi_home)
    match args.command:
        case "locate":
            return cmd_locate(paths, args)
        case "list":
            return cmd_list(paths, args)
        case "summary":
            return cmd_summary(paths, args)
        case "records":
            return cmd_records(paths, args)
        case "subagents":
            return cmd_subagents(paths, args)
        case _:
            print("ERROR: unknown command", file=sys.stderr)
            return 2


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        return 130
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - top-level guard
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
