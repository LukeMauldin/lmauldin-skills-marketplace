#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///
"""Verbose Cursor hook wrapper for debugging hook coverage and payload shape."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SYNC_SCRIPT = SCRIPT_DIR / "sync_session.py"
MAX_DEBUG_RUNS = 500
SYNC_EVENTS = {None, "stop", "sessionEnd", "agentStop", "Stop"}


def main() -> int:
    started = time.monotonic()
    cursor_home = Path(os.environ.get("CURSOR_HOME", Path.home() / ".cursor")).expanduser()
    debug_root = cursor_home / "inspector" / "hook-debug"
    debug_dir = debug_root / f"{timestamp_for_path()}-{os.getpid()}"
    debug_dir.mkdir(parents=True, exist_ok=True)

    raw_stdin = sys.stdin.buffer.read()
    payload, parse_error = parse_payload(raw_stdin)
    event_name = string_field(payload, "hook_event_name") if isinstance(payload, dict) else None

    raw_path = debug_dir / ("stdin.json" if isinstance(payload, dict) else "stdin.txt")
    raw_path.write_bytes(raw_stdin)

    sync_result: dict[str, Any] | None = None
    if event_name in SYNC_EVENTS:
        sync_result = run_sync(raw_stdin, debug_dir)

    summary = {
        "received_at": iso_now(),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "argv": sys.argv,
        "raw_stdin_path": str(raw_path),
        "raw_stdin_bytes": len(raw_stdin),
        "raw_stdin_sha256": hashlib.sha256(raw_stdin).hexdigest(),
        "json_parse_error": parse_error,
        "payload_summary": summarize_payload(payload),
        "sync": sync_result,
        "env": env_summary(),
    }
    write_json(debug_dir / "summary.json", summary)
    append_jsonl(debug_root / "events.jsonl", summary)
    prune_debug_dirs(debug_root)

    print("{}", end="")
    return 0


def run_sync(raw_stdin: bytes, debug_dir: Path) -> dict[str, Any]:
    started = time.monotonic()
    env = os.environ.copy()
    env["CURSOR_INSPECTOR_CAPTURE_HOOK_PAYLOAD"] = "1"
    try:
        completed = subprocess.run(
            ["uv", "run", "--python", "3.14", str(SYNC_SCRIPT)],
            input=raw_stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
            timeout=25,
        )
    except Exception as exc:
        result = {
            "ran": True,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        write_json(debug_dir / "sync-error.json", result)
        return result

    stdout_path = debug_dir / "sync-stdout.txt"
    stderr_path = debug_dir / "sync-stderr.txt"
    stdout_path.write_bytes(completed.stdout)
    stderr_path.write_bytes(completed.stderr)
    return {
        "ran": True,
        "returncode": completed.returncode,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stdout_bytes": len(completed.stdout),
        "stderr_bytes": len(completed.stderr),
        "stdout_preview": completed.stdout.decode("utf-8", errors="replace")[:500],
        "stderr_preview": completed.stderr.decode("utf-8", errors="replace")[:2000],
    }


def parse_payload(raw_stdin: bytes) -> tuple[Any, str | None]:
    if not raw_stdin:
        return {}, None
    try:
        return json.loads(raw_stdin.decode("utf-8")), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def summarize_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__}
    token_fields = {
        key: payload.get(key)
        for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
        if key in payload
    }
    return {
        "type": "dict",
        "keys": sorted(str(key) for key in payload.keys()),
        "hook_event_name": string_field(payload, "hook_event_name"),
        "session_id": string_field(payload, "session_id"),
        "conversation_id": string_field(payload, "conversation_id"),
        "generation_id": string_field(payload, "generation_id"),
        "status": string_field(payload, "status"),
        "model": string_field(payload, "model"),
        "cursor_version": string_field(payload, "cursor_version"),
        "cwd": string_field(payload, "cwd"),
        "transcript_path": string_field(payload, "transcript_path"),
        "tool_name": string_field(payload, "tool_name"),
        "tool_call_id": string_field(payload, "tool_call_id"),
        "tool_use_id": string_field(payload, "tool_use_id") or string_field(payload, "tool_call_id"),
        "tool_input": summarize_tool_input(payload.get("tool_input")),
        "tool_output": summarize_tool_output(payload.get("tool_output")),
        "token_fields": token_fields,
        "workspace_roots": payload.get("workspace_roots") if isinstance(payload.get("workspace_roots"), list) else None,
    }


def summarize_tool_input(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary: dict[str, Any] = {
        "keys": sorted(str(key) for key in value.keys()),
        "file_path": string_field(value, "file_path") or string_field(value, "path"),
        "command": string_field(value, "command"),
        "description": string_field(value, "description"),
        "subagent_type": string_field(value, "subagent_type"),
        "readonly": value.get("readonly") if isinstance(value.get("readonly"), bool) else None,
    }
    if isinstance(value.get("prompt"), str):
        summary["prompt_chars"] = len(value["prompt"])
        summary["prompt_preview"] = value["prompt"][:240]
    return {key: item for key, item in summary.items() if item is not None}


def summarize_tool_output(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    parsed = parse_possible_json(value)
    if isinstance(parsed, dict):
        summary: dict[str, Any] = {
            "type": "json_dict",
            "keys": sorted(str(key) for key in parsed.keys()),
            "status": string_field(parsed, "status"),
            "agent_id": string_field(parsed, "agentId") or string_field(parsed, "agent_id"),
            "tool_call_count": parsed.get("toolCallCount"),
            "message_count": parsed.get("messageCount"),
            "duration_ms": parsed.get("durationMs"),
            "file_path": string_field(parsed, "file_path") or string_field(parsed, "path"),
            "success": parsed.get("success") if isinstance(parsed.get("success"), bool) else None,
            "content_length": parsed.get("content_length"),
        }
        return {key: item for key, item in summary.items() if item is not None}
    if isinstance(value, str):
        return {"type": "string", "chars": len(value), "preview": value[:240]}
    return {"type": type(value).__name__}


def parse_possible_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def env_summary() -> dict[str, str]:
    prefixes = ("CURSOR", "VSCODE", "TERM_PROGRAM")
    keys = [key for key in os.environ if key.startswith(prefixes)]
    keys.extend(["PWD", "SHELL", "USER", "HOME"])
    return {key: os.environ[key] for key in sorted(set(keys)) if key in os.environ}


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True))
        handle.write("\n")


def prune_debug_dirs(debug_root: Path, *, keep: int = MAX_DEBUG_RUNS) -> None:
    runs = sorted(
        (path for path in debug_root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for old_run in runs[keep:]:
        for child in old_run.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)
        old_run.rmdir()


def string_field(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    return value if isinstance(value, str) and value else None


def iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def timestamp_for_path() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


if __name__ == "__main__":
    raise SystemExit(main())
