#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///
"""Cursor stop-hook entry point for incremental session refresh."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
MAX_CAPTURE_FILES = 200
CURSOR_PROFILES = frozenset(("jb", "ks"))
PROFILE_REPO_ROOTS = {
    "jb": ("code/github.com/jb-web-dev",),
    "ks": ("code/github.com/KidStrong",),
}


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


DB = _load_module("cursor_session_inspector_db", "db.py")
IMPORTER = _load_module("cursor_session_inspector_importer", "importer.py")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    cursor_home, app_support = resolve_cursor_paths(payload)
    db_path = IMPORTER.resolve_db_path(cursor_home)

    hook_event_name = _string_field(payload, "hook_event_name")
    if hook_event_name not in {None, "stop", "sessionEnd"}:
        print("{}", end="")
        return 0

    try:
        raw_payload_path = capture_payload_if_enabled(cursor_home, payload)
        persist_hook_token_event(db_path, payload, raw_payload_path=raw_payload_path)
    except Exception:
        raw_payload_path = None

    session_id = _string_field(payload, "session_id")
    transcript_path = _string_field(payload, "transcript_path")
    target = transcript_path or session_id
    if target is None:
        write_marker(
            db_path,
            payload,
            target="unknown",
            marker_kind="import_failed",
            reason="missing_target",
            retryable=False,
        )
        print("{}", end="")
        return 0

    try:
        IMPORTER.refresh_sessions(
            cursor_home,
            app_support=app_support,
            target=target,
            reconcile=False,
            analyze=False,
        )
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


def persist_hook_token_event(
    db_path: Path,
    payload: dict[str, Any],
    *,
    raw_payload_path: Path | None,
) -> None:
    event = DB.hook_token_event_from_payload(
        payload,
        raw_payload_path=str(raw_payload_path) if raw_payload_path is not None else None,
    )
    if event is None:
        return
    with closing(DB.open_db(db_path)) as conn:
        DB.record_hook_token_event(conn, event)
        conn.commit()


def capture_payload_if_enabled(cursor_home: Path, payload: dict[str, Any]) -> Path | None:
    if os.environ.get("CURSOR_INSPECTOR_CAPTURE_HOOK_PAYLOAD") != "1":
        return None
    capture_dir = cursor_home / "inspector" / "payload-captures"
    capture_dir.mkdir(parents=True, exist_ok=True)
    capture_path = capture_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}-{os.getpid()}.json"
    capture_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    prune_payload_captures(capture_dir)
    return capture_path


def prune_payload_captures(capture_dir: Path, *, keep: int = MAX_CAPTURE_FILES) -> None:
    captures = sorted(
        (path for path in capture_dir.glob("*.json") if path.is_file()),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    for old_capture in captures[keep:]:
        old_capture.unlink(missing_ok=True)


def write_marker(
    db_path: Path,
    payload: dict[str, Any],
    *,
    target: str,
    marker_kind: str,
    reason: str,
    retryable: bool,
    error: BaseException | None = None,
    not_before: str | None = None,
) -> None:
    marker = {
        "marker_kind": marker_kind,
        "reason": reason,
        "retryable": retryable,
        "received_at": iso_now(),
        "session_id": _string_field(payload, "session_id"),
        "target": target,
        "cwd": _string_field(payload, "cwd"),
        "transcript_path": _string_field(payload, "transcript_path"),
        "hook_event_name": _string_field(payload, "hook_event_name"),
        "stop_reason": _string_field(payload, "stop_reason"),
        "payload_keys": sorted(str(key) for key in payload.keys()),
    }
    if error is not None:
        marker["error_type"] = type(error).__name__
        marker["error_message"] = str(error)
    if not_before is not None:
        marker["not_before"] = not_before
    DB.write_pending_marker(db_path, target, marker)


def _string_field(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    return value if isinstance(value, str) and value else None


def _optional_path_env(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else None


def resolve_cursor_paths(payload: dict[str, Any]) -> tuple[Path, Path | None]:
    profile = resolve_cursor_profile(payload)
    profile_home: Path | None = None
    profile_app_support: Path | None = None
    if profile is not None:
        profile_home, profile_app_support = cursor_profile_paths(profile)

    cursor_home = (
        _optional_path_env("CURSOR_HOME")
        or profile_home
        or Path.home() / ".cursor"
    ).expanduser()
    app_support = _optional_path_env("CURSOR_APP_SUPPORT") or profile_app_support
    return cursor_home, app_support.expanduser() if app_support is not None else None


def resolve_cursor_profile(payload: dict[str, Any]) -> str | None:
    profile = os.environ.get("CURSOR_PROFILE")
    if profile:
        return _validate_profile(profile)

    cursor_home = os.environ.get("CURSOR_HOME")
    if cursor_home:
        profile = _profile_from_parts(Path(cursor_home).expanduser().parts, ".cursor-homes")
        if profile is not None:
            return profile

    cursor_app_support = os.environ.get("CURSOR_APP_SUPPORT")
    if cursor_app_support:
        profile = _profile_from_parts(Path(cursor_app_support).expanduser().parts, ".cursor-instances")
        if profile is not None:
            return profile

    cwd = _string_field(payload, "cwd")
    return infer_cursor_profile(Path(cwd) if cwd else Path.cwd())


def cursor_profile_paths(profile: str) -> tuple[Path, Path]:
    profile = _validate_profile(profile)
    home = real_home()
    return home / ".cursor-homes" / profile / ".cursor", home / ".cursor-instances" / profile


def infer_cursor_profile(cwd: Path) -> str | None:
    try:
        cwd = cwd.resolve()
    except OSError:
        cwd = cwd.absolute()
    home = real_home().resolve()
    for profile, repo_roots in PROFILE_REPO_ROOTS.items():
        for repo_root in repo_roots:
            if _is_relative_to(cwd, home / repo_root):
                return profile
    return None


def real_home() -> Path:
    return Path(os.environ.get("CURSOR_REAL_HOME", str(Path.home()))).expanduser()


def _validate_profile(profile: str) -> str:
    if profile not in CURSOR_PROFILES:
        raise ValueError(f"unsupported Cursor profile: {profile}")
    return profile


def _profile_from_parts(parts: tuple[str, ...], marker: str) -> str | None:
    try:
        index = parts.index(marker)
    except ValueError:
        return None
    if index + 1 >= len(parts):
        return None
    profile = parts[index + 1]
    return profile if profile in CURSOR_PROFILES else None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def iso_after(seconds: float) -> str:
    return (
        datetime.now(UTC) + timedelta(seconds=seconds)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
