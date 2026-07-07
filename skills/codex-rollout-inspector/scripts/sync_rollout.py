#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///
"""Codex Stop hook entry point for incremental rollout refresh."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def _load_module(module_name: str, filename: str) -> Any:
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    module_path = SCRIPT_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


DB = _load_module("codex_rollout_inspector_db", "db.py")
IMPORTER = _load_module("codex_rollout_inspector_importer", "importer.py")


def _string_field(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    return value if isinstance(value, str) and value else None


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_after(seconds: float) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=seconds)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_marker_payload(
    payload: dict[str, Any],
    *,
    target: str | None,
    marker_kind: str,
    reason: str,
    retryable: bool,
    error: BaseException | None = None,
    not_before: str | None = None,
) -> dict[str, Any]:
    transcript_path = _string_field(payload, "transcript_path")
    marker = {
        "marker_kind": marker_kind,
        "reason": reason,
        "retryable": retryable,
        "received_at": iso_now(),
        "session_id": _string_field(payload, "session_id"),
        "target": target,
        "cwd": _string_field(payload, "cwd"),
        "transcript_path": transcript_path,
        "transcript_path_exists": Path(transcript_path).expanduser().exists()
        if transcript_path
        else None,
        "turn_id": _string_field(payload, "turn_id"),
        "hook_event_name": _string_field(payload, "hook_event_name"),
        "payload_keys": sorted(str(key) for key in payload.keys()),
    }
    if error is not None:
        marker["error_type"] = type(error).__name__
        marker["error_message"] = str(error)
    if not_before is not None:
        marker["not_before"] = not_before
    return marker


def marker_key(payload: dict[str, Any], target: str | None) -> str:
    return target or _string_field(payload, "session_id") or _string_field(payload, "turn_id") or "unknown"


def write_marker(
    db_path: Path,
    payload: dict[str, Any],
    *,
    target: str | None,
    marker_kind: str,
    reason: str,
    retryable: bool,
    error: BaseException | None = None,
    not_before: str | None = None,
) -> None:
    DB.write_pending_marker(
        db_path,
        marker_key(payload, target),
        build_marker_payload(
            payload,
            target=target,
            marker_kind=marker_kind,
            reason=reason,
            retryable=retryable,
            error=error,
            not_before=not_before,
        ),
    )


def select_refresh_target(codex_home: Path, payload: dict[str, Any]) -> tuple[str | None, str | None]:
    transcript_path = _string_field(payload, "transcript_path")
    if transcript_path is not None:
        candidate_path = Path(transcript_path).expanduser()
        if not candidate_path.exists():
            return None, "missing_transcript_path"
        return str(candidate_path), None

    session_id = _string_field(payload, "session_id")
    if session_id is None:
        return None, "missing_session_id"
    try:
        return str(IMPORTER.resolve_refresh_target(codex_home, session_id)), None
    except Exception:
        return None, "unresolved_hook_session_id"


def main() -> int:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    db_path = IMPORTER.resolve_db_path(codex_home)
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    hook_event_name = _string_field(payload, "hook_event_name")
    if hook_event_name not in {None, "Stop"}:
        print("{}", end="")
        return 0

    try:
        IMPORTER.reconcile_pending(codex_home)
    except Exception:
        pass

    target, reason = select_refresh_target(codex_home, payload)
    if target is None:
        write_marker(
            db_path,
            payload,
            target=_string_field(payload, "transcript_path") or _string_field(payload, "session_id"),
            marker_kind="import_failed",
            reason=reason or "missing_target",
            retryable=reason == "missing_transcript_path",
            not_before=iso_after(2),
        )
        print("{}", end="")
        return 0

    try:
        IMPORTER.refresh_rollouts(codex_home, target=target, reconcile=False)
    except Exception as exc:
        write_marker(
            db_path,
            payload,
            target=target,
            marker_kind="import_failed",
            reason="refresh_failed",
            retryable=True,
            error=exc,
            not_before=iso_after(2),
        )
    else:
        write_marker(
            db_path,
            payload,
            target=target,
            marker_kind="reconcile",
            reason="post_stop_final_flush",
            retryable=True,
            not_before=iso_after(2),
        )
    print("{}", end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
