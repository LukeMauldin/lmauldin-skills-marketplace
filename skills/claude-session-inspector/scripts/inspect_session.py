#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///
"""Locate and inspect Claude Code session logs under ~/.claude."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SESSION_JSONL_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$"
)
SUBAGENT_RE = re.compile(r"^agent-(?P<agent_id>[0-9a-f]+)\.jsonl$")
QUICK_METADATA_LINE_LIMIT = 400
TEXT_PREVIEW_LIMIT = 200
COMMAND_PREVIEW_LIMIT = 200
ERROR_PREVIEW_LIMIT = 200
SCRIPT_DIR = Path(__file__).resolve().parent


def _load_support_module(module_name: str, filename: str) -> Any:
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    module_path = SCRIPT_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load support module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


DB = _load_support_module("claude_session_inspector_db", "db.py")
IMPORTER = _load_support_module("claude_session_inspector_importer", "importer.py")


def _dc_dict(obj: Any) -> dict[str, Any]:
    """Convert a slots-only dataclass to a plain dict with Path -> str."""
    return {
        f.name: str(v) if isinstance(v, Path) else v
        for f in obj.__class__.__dataclass_fields__.values()
        if (v := getattr(obj, f.name)) is not None or True
    }


@dataclass(slots=True)
class ClaudePaths:
    claude_home: Path
    projects_dir: Path
    history_path: Path
    sessions_dir: Path


@dataclass(slots=True)
class SessionFile:
    path: Path
    session_id: str
    project: str
    project_cwd: str | None = None
    timestamp: datetime | None = None
    slug: str | None = None
    custom_title: str | None = None
    agent_name: str | None = None


@dataclass(slots=True)
class LoadedSession:
    path: Path
    records: list[dict[str, Any]]
    parse_errors: int


@dataclass(slots=True)
class SubagentInfo:
    agent_id: str
    path: Path
    record_count: int
    model: str | None
    first_task: str | None


@dataclass(slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    # Per-TTL prompt-cache write breakdown from usage.cache_creation.  These are
    # the *labeled* values as reported; they can sum to slightly less than the
    # aggregate cache_creation_input_tokens (observed in real logs), so callers
    # that need pricing buckets must reconcile via reconcile_cache_creation().
    cache_creation_5m_input_tokens: int = 0
    cache_creation_1h_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(slots=True)
class ToolCall:
    tool_use_id: str
    name: str
    file_path: str | None = None
    command: str | None = None
    is_error: bool = False
    error_text: str | None = None


@dataclass(slots=True)
class ServerToolCall:
    tool_use_id: str
    name: str
    call_order: int = 0
    is_aborted: bool = False
    emit_timestamp: datetime | None = None
    result_timestamp: datetime | None = None
    latency_ms: int | None = None
    iteration_type: str | None = None
    iteration_model: str | None = None
    iteration_input_tokens: int = 0
    iteration_output_tokens: int = 0
    iteration_cache_read: int = 0
    iteration_cache_create: int = 0
    iteration_cache_create_5m: int = 0
    iteration_cache_create_1h: int = 0


@dataclass(slots=True)
class ThinkingBlockMetrics:
    block_index: int
    is_redacted: bool = False
    content_length: int = 0
    signature_length: int = 0
    has_signature: bool = False


@dataclass(slots=True)
class UserMessageMetrics:
    message_index: int
    timestamp: datetime | None = None
    is_first: bool = False
    is_interrupt: bool = False
    word_count: int = 0
    char_count: int = 0
    preceding_turn_index: int | None = None


@dataclass(slots=True)
class HookExecution:
    command: str
    duration_ms: int
    is_error: bool = False


@dataclass(slots=True)
class Turn:
    index: int
    message_id: str
    timestamp: datetime | None = None
    request_id: str | None = None
    model: str | None = None
    stop_reason: str | None = None
    # usage.speed from the API response: "standard" or "fast" (Claude Code fast
    # mode).  None when the field is absent (older sessions / non-Opus turns).
    speed: str | None = None
    turn_duration_ms: int | None = None
    user_gap_ms: int | None = None
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    text_block_count: int = 0
    thinking_block_count: int = 0
    tool_use_block_count: int = 0
    reasoning_output_tokens: int = 0
    thinking_blocks: list[ThinkingBlockMetrics] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    _tool_calls_by_id: dict[str, ToolCall] = field(default_factory=dict, repr=False)
    server_tool_calls: list[ServerToolCall] = field(default_factory=list)
    _server_tool_calls_by_id: dict[str, ServerToolCall] = field(default_factory=dict, repr=False)

    @property
    def total_tokens(self) -> int:
        return self.token_usage.total_tokens


@dataclass(slots=True)
class ParsedSession:
    path: Path
    session_id: str
    project: str | None = None
    project_cwd: str | None = None
    parse_errors: int = 0
    record_count: int = 0
    record_counts: Counter[str] = field(default_factory=Counter)
    system_subtypes: Counter[str] = field(default_factory=Counter)
    session_meta: dict[str, Any] = field(default_factory=dict)
    start_timestamp: datetime | None = None
    slug: str | None = None
    custom_title: str | None = None
    agent_name: str | None = None
    first_user_message: str | None = None
    latest_git_branch: str | None = None
    pr_links: list[dict[str, Any]] = field(default_factory=list)
    hooks: list[HookExecution] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    user_messages: list[UserMessageMetrics] = field(default_factory=list)
    api_error_count: int = 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Locate and inspect Claude Code session logs.",
        suggest_on_error=True,
    )
    parser.add_argument(
        "--claude-home",
        type=Path,
        default=None,
        help="Override Claude home. Defaults to ~/.claude.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of plain text.",
    )
    parser.add_argument(
        "--profile",
        choices=("default", "ingestion"),
        default="default",
        help="Output profile. `ingestion` emits a normalized machine-oriented shape.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("locate", help="Print key Claude log locations.")

    list_parser = subparsers.add_parser("list", help="List session files.")
    list_parser.add_argument(
        "--project",
        default=None,
        help="Filter by project name (substring match on project path).",
    )
    list_parser.add_argument(
        "--since",
        type=parse_since_date,
        default=None,
        help="Keep sessions whose first record timestamp is on or after YYYY-MM-DD.",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of results to print.",
    )

    summary_parser = subparsers.add_parser(
        "summary",
        help="Summarize a session file. Defaults to latest session.",
    )
    summary_parser.add_argument(
        "target",
        nargs="?",
        help="Session path, session UUID, or project substring. If omitted, uses the latest session.",
    )
    summary_parser.add_argument(
        "--project",
        default=None,
        help="Filter by project name when target is a session UUID.",
    )

    refresh_parser = subparsers.add_parser(
        "refresh",
        help="Incrementally import session data into SQLite.",
    )
    refresh_parser.add_argument(
        "target",
        nargs="?",
        help="Session path, session UUID, or project substring. If omitted, refreshes matching sessions.",
    )
    refresh_parser.add_argument(
        "--project",
        default=None,
        help="Filter by project name when target is a session UUID.",
    )
    refresh_parser.add_argument(
        "--since",
        type=parse_since_date,
        default=None,
        help="Refresh only sessions on or after YYYY-MM-DD.",
    )
    refresh_parser.add_argument(
        "--pending",
        action="store_true",
        help="Reconcile due pending markers only, without scanning other sessions.",
    )

    rebuild_parser = subparsers.add_parser(
        "rebuild",
        help="Delete and rebuild the SQLite cache from raw logs.",
    )
    rebuild_parser.add_argument(
        "--project",
        default=None,
        help="Filter by project name when rebuilding.",
    )
    rebuild_parser.add_argument(
        "--since",
        type=parse_since_date,
        default=None,
        help="Rebuild only sessions on or after YYYY-MM-DD.",
    )

    records_parser = subparsers.add_parser(
        "records",
        help="Print raw matching session records.",
    )
    records_parser.add_argument(
        "target",
        nargs="?",
        help="Session path or UUID. If omitted, uses the latest session.",
    )
    records_parser.add_argument(
        "--project",
        default=None,
        help="Filter by project name when target is a session UUID.",
    )
    records_parser.add_argument(
        "--record-type",
        default=None,
        help="Filter top-level record type (user, assistant, system, progress, etc.).",
    )
    records_parser.add_argument(
        "--tool-name",
        default=None,
        help="Filter assistant records containing a tool_use with this tool name.",
    )
    records_parser.add_argument(
        "--system-subtype",
        default=None,
        help="Filter system records by subtype (turn_duration, local_command, etc.).",
    )
    records_parser.add_argument(
        "--tail",
        type=int,
        default=20,
        help="Return only the last N matching records.",
    )

    subagents_parser = subparsers.add_parser(
        "subagents",
        help="List or inspect subagent logs for a session.",
    )
    subagents_parser.add_argument(
        "target",
        nargs="?",
        help="Session path or UUID. If omitted, uses the latest session.",
    )
    subagents_parser.add_argument(
        "--project",
        default=None,
        help="Filter by project name when target is a session UUID.",
    )
    subagents_parser.add_argument(
        "--agent-id",
        default=None,
        help="Summarize a specific subagent by its agent ID.",
    )

    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    paths = resolve_paths(args.claude_home)
    db_path = DB.default_db_path(paths.claude_home)

    match args.command:
        case "locate":
            emit(args.json, locate_payload(paths, db_path=db_path))
            return 0
        case "refresh":
            if args.pending:
                reconciled = IMPORTER.reconcile_pending(paths.claude_home)
                result = {
                    "reconciled_pending": reconciled,
                    "reconciled_pending_count": len(reconciled),
                    "pending_markers": DB.pending_marker_stats(db_path),
                    "db_path": str(db_path),
                }
            else:
                result = IMPORTER.refresh_sessions(
                    paths.claude_home,
                    target=args.target,
                    project=args.project,
                    since=args.since,
                )
            emit(args.json, result)
            return 0
        case "rebuild":
            result = IMPORTER.rebuild_sessions(
                paths.claude_home,
                project=args.project,
                since=args.since,
            )
            emit(args.json, result)
            return 0
        case "list":
            if db_path.exists():
                raw_sessions = collect_sessions(paths, project=args.project, since=args.since)
                IMPORTER.refresh_sessions(
                    paths.claude_home,
                    session_paths=[session.path for session in raw_sessions],
                )
                emit(
                    args.json,
                    IMPORTER.list_payload(
                        paths.claude_home,
                        project=args.project,
                        since=args.since,
                        limit=args.limit,
                        profile=args.profile,
                    ),
                )
                return 0
            print(
                "SQLite cache not found; using stateless session scan. Run `refresh` to create it.",
                file=sys.stderr,
            )
            sessions = collect_sessions(paths, project=args.project, since=args.since)
            selected = sessions[-args.limit :][::-1]
            payload = (
                [ingestion_stub_from_session_file(session) for session in selected]
                if args.profile == "ingestion"
                else [session_descriptor(session) for session in selected]
            )
            emit(args.json, payload)
            return 0
        case "summary":
            session_path = resolve_target(paths, args.target, project=args.project)
            if db_path.exists():
                IMPORTER.refresh_sessions(paths.claude_home, session_paths=[session_path])
                payload = IMPORTER.summary_payload(
                    paths.claude_home,
                    IMPORTER.session_id_for_path(session_path),
                    profile=args.profile,
                )
                if payload is not None:
                    emit(args.json, payload)
                    return 0
            else:
                print(
                    "SQLite cache not found; using stateless session summary. Run `refresh` to create it.",
                    file=sys.stderr,
                )
            loaded = load_session(session_path)
            summary = summarize_session(loaded, paths)
            emit(args.json, summarize_session_ingestion(summary) if args.profile == "ingestion" else summary)
            return 0
        case "records":
            session_path = resolve_target(paths, args.target, project=args.project)
            loaded = load_session(session_path)
            matches = filter_records(
                loaded.records,
                record_type=args.record_type,
                tool_name=args.tool_name,
                system_subtype=args.system_subtype,
            )
            emit(args.json, matches[-args.tail :])
            return 0
        case "subagents":
            session_path = resolve_target(paths, args.target, project=args.project)
            parent_session_path = (
                IMPORTER.parent_session_path_for_subagent(session_path) or session_path
                if IMPORTER.is_subagent_path(session_path)
                else session_path
            )
            if db_path.exists():
                IMPORTER.refresh_sessions(paths.claude_home, session_paths=[parent_session_path])
                payload = IMPORTER.subagents_payload(
                    paths.claude_home,
                    parent_session_path.stem,
                    profile=args.profile,
                    agent_id=args.agent_id,
                )
                if payload is not None:
                    emit(args.json, payload)
                    return 0
            else:
                print(
                    "SQLite cache not found; using stateless subagent scan. Run `refresh` to create it.",
                    file=sys.stderr,
                )
            if args.agent_id:
                info = inspect_subagent(session_path, args.agent_id)
                emit(
                    args.json,
                    build_subagent_ingestion_summary(session_path, info)
                    if args.profile == "ingestion"
                    else info,
                )
                return 0

            subagents = list_subagents(session_path)
            if args.profile == "ingestion":
                payload = [
                    build_subagent_ingestion_summary(session_path, inspect_subagent(session_path, item.agent_id))
                    for item in subagents
                ]
            else:
                payload = [inspect_subagent(session_path, item.agent_id) for item in subagents]
            emit(args.json, payload)
            return 0
        case _:
            raise ValueError(f"unsupported command: {args.command}")


def resolve_paths(override: Path | None) -> ClaudePaths:
    claude_home = (
        override.expanduser()
        if override is not None
        else Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude")).expanduser()
    )
    return ClaudePaths(
        claude_home=claude_home,
        projects_dir=claude_home / "projects",
        history_path=claude_home / "history.jsonl",
        sessions_dir=claude_home / "sessions",
    )


def find_hook_config_path() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "hooks" / "hooks.json"
        if candidate.exists():
            return candidate
        manifest_candidate = parent / ".claude-plugin" / "plugin.json"
        if manifest_candidate.exists():
            return parent / "hooks" / "hooks.json"
    return current.parent.parent / "hooks" / "hooks.json"


def locate_payload(paths: ClaudePaths, *, db_path: Path) -> dict[str, Any]:
    projects = list_project_dirs(paths)
    total_sessions = sum(
        1
        for project_dir in projects
        for path in project_dir.iterdir()
        if path.is_file() and SESSION_JSONL_RE.match(path.name)
    )
    db_info = DB.database_stats(db_path)
    pending_stats = DB.pending_marker_stats(db_path)
    hook_config_path = find_hook_config_path()
    return {
        "claude_home": str(paths.claude_home),
        "projects_dir": str(paths.projects_dir),
        "history_path": str(paths.history_path),
        "sessions_dir": str(paths.sessions_dir),
        "db_path": str(db_path),
        "db_exists": db_info["exists"],
        "db_session_count": db_info["session_count"],
        "db_subagent_count": db_info["subagent_count"],
        "db_last_import_at": db_info["last_import_at"],
        "pending_dir": str(DB.pending_dir(db_path)),
        "pending_markers": pending_stats,
        "hook_config_path": str(hook_config_path),
        "hook_configured": hook_config_path.exists(),
        "hook_runtime_env_present": bool(os.environ.get("CLAUDE_PLUGIN_ROOT")),
        "project_count": len(projects),
        "total_session_files": total_sessions,
        "projects": [project_dir.name for project_dir in projects],
    }


def list_project_dirs(paths: ClaudePaths) -> list[Path]:
    if not paths.projects_dir.exists():
        return []
    return sorted(
        path for path in paths.projects_dir.iterdir() if path.is_dir() and not path.name.startswith(".")
    )


def collect_sessions(
    paths: ClaudePaths,
    *,
    project: str | None,
    since: date | None,
) -> list[SessionFile]:
    sessions: list[SessionFile] = []
    for project_dir in list_project_dirs(paths):
        project_name = project_dir.name
        project_cwd = decode_project_dir_name(project_name)
        if project and not project_matches(project_name, project_cwd, project):
            continue

        for path in project_dir.iterdir():
            if not path.is_file() or not SESSION_JSONL_RE.match(path.name):
                continue
            meta = extract_quick_metadata(path)
            timestamp = meta.get("timestamp")
            if since and isinstance(timestamp, datetime) and timestamp.date() < since:
                continue
            sessions.append(
                SessionFile(
                    path=path,
                    session_id=path.stem,
                    project=project_name,
                    project_cwd=project_cwd,
                    timestamp=timestamp if isinstance(timestamp, datetime) else None,
                    slug=meta.get("slug"),
                    custom_title=meta.get("custom_title"),
                    agent_name=meta.get("agent_name"),
                )
            )

    sessions.sort(key=lambda session: session.timestamp or datetime.min.replace(tzinfo=timezone.utc))
    return sessions


def extract_quick_metadata(path: Path) -> dict[str, Any]:
    """Read enough of a session file to discover lightweight list metadata."""
    meta: dict[str, Any] = {}
    try:
        with path.open(encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if line_number > QUICK_METADATA_LINE_LIMIT:
                    break
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue

                record_type = obj.get("type")
                if record_type == "user" and "timestamp" not in meta:
                    timestamp = parse_timestamp_safe(obj.get("timestamp"))
                    if timestamp is not None:
                        meta["timestamp"] = timestamp
                if "slug" not in meta and isinstance(obj.get("slug"), str) and obj["slug"]:
                    meta["slug"] = obj["slug"]
                if record_type == "custom-title" and "custom_title" not in meta:
                    custom_title = obj.get("customTitle")
                    if isinstance(custom_title, str) and custom_title:
                        meta["custom_title"] = custom_title
                if record_type == "agent-name" and "agent_name" not in meta:
                    agent_name = obj.get("agentName")
                    if isinstance(agent_name, str) and agent_name:
                        meta["agent_name"] = agent_name

                if all(key in meta for key in ("timestamp", "slug", "custom_title", "agent_name")):
                    break
    except OSError:
        return meta
    return meta


def parse_timestamp(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def parse_timestamp_safe(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_timestamp(value)
    except ValueError:
        return None


def parse_since_date(value: str) -> date:
    return date.fromisoformat(value)


def decode_project_dir_name(name: str) -> str | None:
    if not name.startswith("-"):
        return None
    return "/" + name.lstrip("-").replace("-", "/")


def normalize_project_hint(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def project_matches(project_name: str, project_cwd: str | None, query: str) -> bool:
    query_lower = query.lower()
    if query_lower in project_name.lower():
        return True
    if project_cwd is not None and query_lower in project_cwd.lower():
        return True

    normalized_query = normalize_project_hint(query)
    if not normalized_query:
        return False
    if normalized_query in normalize_project_hint(project_name):
        return True
    return project_cwd is not None and normalized_query in normalize_project_hint(project_cwd)


def session_descriptor(session: SessionFile) -> dict[str, Any]:
    title = display_name_for_session(
        custom_title=session.custom_title,
        agent_name=session.agent_name,
        slug=session.slug,
        first_user_message=None,
    )
    return {
        "path": str(session.path),
        "session_id": session.session_id,
        "project": session.project,
        "project_cwd": session.project_cwd,
        "timestamp": isoformat_utc(session.timestamp),
        "slug": session.slug,
        "custom_title": session.custom_title,
        "agent_name": session.agent_name,
        "display_name": title,
        "size_bytes": session.path.stat().st_size if session.path.exists() else None,
    }


def ingestion_stub_from_session_file(session: SessionFile) -> dict[str, Any]:
    title = display_name_for_session(
        custom_title=session.custom_title,
        agent_name=session.agent_name,
        slug=session.slug,
        first_user_message=None,
    )
    return {
        "schema_version": "session_inspector_v2",
        "source": "claude_code",
        "kind": "session_stub",
        "session": {
            "id": session.session_id,
            "path": str(session.path),
            "project": session.project,
            "cwd": session.project_cwd,
            "timestamp": isoformat_utc(session.timestamp),
            "title": title,
            "display_name": title,
            "archived": None,
            "version": None,
            "model_provider": None,
            "model": None,
            "git_branch": None,
            "git_commit": None,
            "session_origin": None,
            "is_subagent": False,
            "parent_session_id": None,
            "forked_from_session_id": None,
            "agent": {
                "nickname": session.agent_name,
                "role": None,
                "path": None,
                "depth": None,
            }
            if session.agent_name
            else None,
        },
    }


def resolve_target(paths: ClaudePaths, target: str | None, *, project: str | None) -> Path:
    if target is None:
        sessions = collect_sessions(paths, project=project, since=None)
        if not sessions:
            raise FileNotFoundError("no session files found")
        return sessions[-1].path

    candidate = Path(target).expanduser()
    if candidate.exists() and candidate.is_file():
        return candidate

    if UUID_RE.match(target):
        sessions = collect_sessions(paths, project=project, since=None)
        matches = [session for session in sessions if session.session_id == target]
        if not matches and project is not None:
            sessions = collect_sessions(paths, project=None, since=None)
            matches = [session for session in sessions if session.session_id == target]
        if matches:
            return matches[-1].path

    sessions = collect_sessions(paths, project=target, since=None)
    if sessions:
        return sessions[-1].path

    raise FileNotFoundError(f"could not resolve session target: {target}")


def load_session(path: Path) -> LoadedSession:
    records: list[dict[str, Any]] = []
    parse_errors = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            parse_errors += 1
    return LoadedSession(path=path, records=records, parse_errors=parse_errors)


def summarize_session(loaded: LoadedSession, paths: ClaudePaths) -> dict[str, Any]:
    project = project_dir_name_for_path(loaded.path)
    project_cwd = decode_project_dir_name(project) if project else None
    parsed = parse_loaded_session(
        loaded,
        session_id_override=loaded.path.stem,
        project=project,
        project_cwd=project_cwd,
    )
    return build_session_summary(parsed, subagents=list_subagents(loaded.path))


def parse_loaded_session(
    loaded: LoadedSession,
    *,
    session_id_override: str | None = None,
    project: str | None = None,
    project_cwd: str | None = None,
) -> ParsedSession:
    parsed = ParsedSession(
        path=loaded.path,
        session_id=session_id_override or loaded.path.stem,
        project=project,
        project_cwd=project_cwd,
        parse_errors=loaded.parse_errors,
        record_count=len(loaded.records),
    )

    current_turn: Turn | None = None
    last_completed_turn_timestamp: datetime | None = None

    for obj in loaded.records:
        record_type = str(obj.get("type", "unknown"))
        parsed.record_counts[record_type] += 1

        if not parsed.slug and isinstance(obj.get("slug"), str) and obj["slug"]:
            parsed.slug = obj["slug"]
        if isinstance(obj.get("gitBranch"), str) and obj["gitBranch"]:
            parsed.latest_git_branch = obj["gitBranch"]
        if record_type == "custom-title" and not parsed.custom_title:
            custom_title = obj.get("customTitle")
            if isinstance(custom_title, str) and custom_title:
                parsed.custom_title = custom_title
        if record_type == "agent-name" and not parsed.agent_name:
            agent_name = obj.get("agentName")
            if isinstance(agent_name, str) and agent_name:
                parsed.agent_name = agent_name
        if record_type == "pr-link":
            parsed.pr_links.append(
                {
                    "prNumber": obj.get("prNumber"),
                    "prUrl": obj.get("prUrl"),
                    "prRepository": obj.get("prRepository"),
                }
            )

        if record_type == "user":
            timestamp = parse_timestamp_safe(obj.get("timestamp"))
            message = obj.get("message")
            message_text = content_to_text(message.get("content")) if isinstance(message, dict) else None
            is_real_prompt = _is_real_user_prompt(obj)

            if not parsed.session_meta and obj.get("parentUuid") is None:
                parsed.session_meta = {
                    "sessionId": obj.get("sessionId"),
                    "cwd": obj.get("cwd"),
                    "version": obj.get("version"),
                    "gitBranch": obj.get("gitBranch"),
                    "permissionMode": obj.get("permissionMode"),
                    "entrypoint": obj.get("entrypoint"),
                    "userType": obj.get("userType"),
                }
                parsed.start_timestamp = timestamp
                parsed.first_user_message = extract_message_text(message)
                if is_real_prompt:
                    parsed.user_messages.append(
                        UserMessageMetrics(
                            message_index=len(parsed.user_messages) + 1,
                            timestamp=timestamp,
                            is_first=True,
                            word_count=count_words(message_text),
                            char_count=len(message_text or ""),
                            preceding_turn_index=current_turn.index if current_turn is not None else None,
                        )
                    )
            elif is_real_prompt:
                parsed.user_messages.append(
                    UserMessageMetrics(
                        message_index=len(parsed.user_messages) + 1,
                        timestamp=timestamp,
                        is_first=not parsed.user_messages,
                        is_interrupt=current_turn is not None and current_turn.turn_duration_ms is None,
                        word_count=count_words(message_text),
                        char_count=len(message_text or ""),
                        preceding_turn_index=current_turn.index if current_turn is not None else None,
                    )
                )

            if current_turn is not None:
                process_tool_results(current_turn, message)
            continue

        if record_type == "assistant":
            message = obj.get("message")
            if not isinstance(message, dict):
                continue
            message_id = message.get("id")
            if not isinstance(message_id, str) or not message_id:
                continue

            if current_turn is None or current_turn.message_id != message_id:
                if current_turn is not None:
                    parsed.turns.append(current_turn)
                turn_timestamp = parse_timestamp_safe(obj.get("timestamp"))
                user_gap_ms = None
                if turn_timestamp is not None and last_completed_turn_timestamp is not None:
                    user_gap_ms = int((turn_timestamp - last_completed_turn_timestamp).total_seconds() * 1000)
                current_turn = Turn(
                    index=len(parsed.turns) + 1,
                    message_id=message_id,
                    timestamp=turn_timestamp,
                    user_gap_ms=user_gap_ms,
                )

            update_turn_from_assistant_record(current_turn, obj)
            continue

        if record_type == "system":
            subtype = str(obj.get("subtype", "unknown"))
            parsed.system_subtypes[subtype] += 1
            if subtype == "turn_duration":
                duration_ms = obj.get("durationMs")
                if isinstance(duration_ms, int) and current_turn is not None:
                    current_turn.turn_duration_ms = duration_ms
                completed_timestamp = parse_timestamp_safe(obj.get("timestamp"))
                if completed_timestamp is not None:
                    last_completed_turn_timestamp = completed_timestamp
            elif subtype in ("hook_summary", "stop_hook_summary"):
                parsed.hooks.extend(parse_hook_executions(obj))
            elif subtype == "api_error":
                parsed.api_error_count += 1

    if current_turn is not None:
        parsed.turns.append(current_turn)

    # Mark server tool calls with no result as aborted.
    for turn in parsed.turns:
        for stc in turn.server_tool_calls:
            if stc.result_timestamp is None:
                stc.is_aborted = True

    if parsed.start_timestamp is None and parsed.turns:
        parsed.start_timestamp = parsed.turns[0].timestamp

    return parsed


def update_turn_from_assistant_record(turn: Turn, record: dict[str, Any]) -> None:
    message = record.get("message")
    if not isinstance(message, dict):
        return

    request_id = record.get("requestId")
    if isinstance(request_id, str) and request_id:
        turn.request_id = request_id

    model = message.get("model")
    if isinstance(model, str) and model:
        turn.model = model

    stop_reason = message.get("stop_reason")
    if isinstance(stop_reason, str) and stop_reason:
        turn.stop_reason = stop_reason

    usage = message.get("usage")
    if isinstance(usage, dict):
        speed = usage.get("speed")
        if isinstance(speed, str) and speed:
            turn.speed = speed

    apply_usage(turn.token_usage, usage)

    record_timestamp = parse_timestamp_safe(record.get("timestamp"))

    content = message.get("content")
    if not isinstance(content, list):
        return
    previous_tool_calls = turn._tool_calls_by_id
    previous_server_tool_calls = turn._server_tool_calls_by_id
    turn.text_block_count = 0
    turn.thinking_block_count = 0
    turn.tool_use_block_count = 0
    turn.thinking_blocks = []
    turn.tool_calls = []
    turn._tool_calls_by_id = {}
    turn.server_tool_calls = []
    turn._server_tool_calls_by_id = {}

    for block_index, block in enumerate(content):
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            turn.text_block_count += 1
            continue
        if block_type == "thinking":
            turn.thinking_block_count += 1
            thinking = block.get("thinking")
            signature = block.get("signature")
            turn.thinking_blocks.append(
                ThinkingBlockMetrics(
                    block_index=block_index,
                    is_redacted=not isinstance(thinking, str) or not thinking.strip(),
                    content_length=len(thinking) if isinstance(thinking, str) else 0,
                    signature_length=len(signature) if isinstance(signature, str) else 0,
                    has_signature=isinstance(signature, str) and bool(signature),
                )
            )
            continue
        if block_type == "server_tool_use":
            stc_id = block.get("id")
            stc_name = block.get("name")
            if isinstance(stc_id, str) and stc_id and isinstance(stc_name, str) and stc_name:
                existing = previous_server_tool_calls.get(stc_id)
                if existing is not None:
                    existing.emit_timestamp = existing.emit_timestamp or record_timestamp
                    turn.server_tool_calls.append(existing)
                    turn._server_tool_calls_by_id[stc_id] = existing
                elif stc_id not in turn._server_tool_calls_by_id:
                    stc = ServerToolCall(
                        tool_use_id=stc_id,
                        name=stc_name,
                        emit_timestamp=record_timestamp,
                    )
                    turn.server_tool_calls.append(stc)
                    turn._server_tool_calls_by_id[stc_id] = stc
            continue
        if isinstance(block_type, str) and block_type.endswith("_tool_result"):
            result_tool_use_id = block.get("tool_use_id")
            if isinstance(result_tool_use_id, str) and result_tool_use_id:
                stc = turn._server_tool_calls_by_id.get(result_tool_use_id)
                if stc is None:
                    stc = previous_server_tool_calls.get(result_tool_use_id)
                if stc is not None:
                    stc.result_timestamp = record_timestamp
                    if stc.emit_timestamp is not None and record_timestamp is not None:
                        stc.latency_ms = int(
                            (record_timestamp - stc.emit_timestamp).total_seconds() * 1000
                        )
                    if result_tool_use_id not in turn._server_tool_calls_by_id:
                        turn.server_tool_calls.append(stc)
                        turn._server_tool_calls_by_id[result_tool_use_id] = stc
            continue
        if block_type != "tool_use":
            continue

        turn.tool_use_block_count += 1
        tool_call = build_tool_call(block)
        if tool_call is None:
            continue
        existing_tool_call = (
            previous_tool_calls.get(tool_call.tool_use_id)
            if tool_call.tool_use_id
            else None
        )
        if existing_tool_call is not None:
            merge_tool_call(tool_call, existing_tool_call)
        if tool_call.tool_use_id and tool_call.tool_use_id in turn._tool_calls_by_id:
            merge_tool_call(turn._tool_calls_by_id[tool_call.tool_use_id], tool_call)
            continue
        turn.tool_calls.append(tool_call)
        if tool_call.tool_use_id:
            turn._tool_calls_by_id[tool_call.tool_use_id] = tool_call

    for tool_use_id, tool_call in previous_tool_calls.items():
        if tool_use_id not in turn._tool_calls_by_id:
            turn.tool_calls.append(tool_call)
            turn._tool_calls_by_id[tool_use_id] = tool_call

    for stc_id, stc in previous_server_tool_calls.items():
        if stc_id not in turn._server_tool_calls_by_id:
            turn.server_tool_calls.append(stc)
            turn._server_tool_calls_by_id[stc_id] = stc

    # Parse usage.iterations[] to attribute tokens to server tool calls.
    usage = message.get("usage")
    if isinstance(usage, dict):
        iterations = usage.get("iterations")
        if isinstance(iterations, list) and turn.server_tool_calls:
            server_iterations = [
                it for it in iterations
                if isinstance(it, dict) and it.get("type", "").endswith("_message")
                and it.get("type") != "message"
            ]
            for idx, stc in enumerate(turn.server_tool_calls):
                if idx < len(server_iterations):
                    it = server_iterations[idx]
                    stc.iteration_type = it.get("type")
                    stc.iteration_model = it.get("model")
                    stc.iteration_input_tokens = int_or_zero(it.get("input_tokens"))
                    stc.iteration_output_tokens = int_or_zero(it.get("output_tokens"))
                    stc.iteration_cache_read = int_or_zero(it.get("cache_read_input_tokens"))
                    stc.iteration_cache_create = int_or_zero(it.get("cache_creation_input_tokens"))
                    five, one = cache_creation_split(it.get("cache_creation"))
                    stc.iteration_cache_create_5m = five
                    stc.iteration_cache_create_1h = one


def build_tool_call(block: dict[str, Any]) -> ToolCall | None:
    name = block.get("name")
    if not isinstance(name, str) or not name:
        return None
    tool_use_id = block.get("id")
    tool_input = block.get("input")
    input_dict = tool_input if isinstance(tool_input, dict) else {}
    command = input_dict.get("command")
    if not isinstance(command, str) or not command:
        description = input_dict.get("description")
        command = description if isinstance(description, str) else None
    file_path = first_str(
        input_dict.get("file_path"),
        input_dict.get("path"),
        input_dict.get("file"),
    )
    return ToolCall(
        tool_use_id=tool_use_id if isinstance(tool_use_id, str) else "",
        name=name,
        file_path=truncate_text(file_path, COMMAND_PREVIEW_LIMIT),
        command=truncate_text(command, COMMAND_PREVIEW_LIMIT),
    )


def merge_tool_call(target: ToolCall, source: ToolCall) -> None:
    if not target.file_path and source.file_path:
        target.file_path = source.file_path
    if not target.command and source.command:
        target.command = source.command
    if source.is_error:
        target.is_error = True
    if not target.error_text and source.error_text:
        target.error_text = source.error_text


def process_tool_results(turn: Turn, message: Any) -> None:
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tool_use_id = block.get("tool_use_id")
        if not isinstance(tool_use_id, str) or not tool_use_id:
            continue
        tool_call = turn._tool_calls_by_id.get(tool_use_id)
        if tool_call is None:
            continue
        tool_call.is_error = bool(block.get("is_error"))
        if tool_call.is_error:
            tool_call.error_text = truncate_text(content_to_text(block.get("content")), ERROR_PREVIEW_LIMIT)


def parse_hook_executions(obj: dict[str, Any]) -> list[HookExecution]:
    hook_infos = obj.get("hookInfos")
    hook_errors = obj.get("hookErrors")
    if not isinstance(hook_infos, list):
        return []

    error_commands = {
        str(command)
        for entry in hook_errors or []
        if isinstance(entry, dict)
        and (command := entry.get("command") or entry.get("hook_command"))
    }
    hooks: list[HookExecution] = []
    for info in hook_infos:
        if not isinstance(info, dict):
            continue
        command = info.get("command") or info.get("hook_command") or "unknown"
        duration = info.get("durationMs", 0)
        hooks.append(
            HookExecution(
                command=truncate_text(str(command), COMMAND_PREVIEW_LIMIT) or "unknown",
                duration_ms=duration if isinstance(duration, int) else 0,
                is_error=str(command) in error_commands,
            )
        )
    return hooks


def apply_usage(target: TokenUsage, usage: Any) -> None:
    if not isinstance(usage, dict):
        return
    target.input_tokens = int_or_zero(usage.get("input_tokens"))
    target.output_tokens = int_or_zero(usage.get("output_tokens"))
    target.cache_creation_input_tokens = int_or_zero(usage.get("cache_creation_input_tokens"))
    target.cache_read_input_tokens = int_or_zero(usage.get("cache_read_input_tokens"))
    five, one = cache_creation_split(usage.get("cache_creation"))
    target.cache_creation_5m_input_tokens = five
    target.cache_creation_1h_input_tokens = one


def cache_creation_split(cache_creation: Any) -> tuple[int, int]:
    """Return (ephemeral_5m, ephemeral_1h) from a usage.cache_creation object.

    Current Claude Code logs break prompt-cache writes down by TTL under
    ``usage.cache_creation``.  Older logs omit the object entirely; callers fall
    back to treating all cache writes as 5-minute TTL in that case.
    """
    if not isinstance(cache_creation, dict):
        return 0, 0
    return (
        int_or_zero(cache_creation.get("ephemeral_5m_input_tokens")),
        int_or_zero(cache_creation.get("ephemeral_1h_input_tokens")),
    )


def reconcile_cache_creation(
    aggregate: int,
    ephemeral_5m: int,
    ephemeral_1h: int,
) -> tuple[int, int]:
    """Reconcile the aggregate cache-write total with the per-TTL split.

    Returns ``(cache_create_5m, cache_create_1h)`` *pricing buckets* that always
    sum to ``max(aggregate, ephemeral_5m + ephemeral_1h)`` so no labeled token is
    ever dropped:

    * The 1-hour bucket is the labeled ``ephemeral_1h`` (billed at 2x base input).
    * The 5-minute bucket is everything else — the labeled 5m plus any unlabeled
      remainder when the aggregate exceeds the split (observed in real logs).
      This is the conservative default (1.25x base input) and matches the prior
      "all cache writes are 5-minute" behavior when the split is absent.
    """
    agg = max(aggregate, 0)
    five = max(ephemeral_5m, 0)
    one = max(ephemeral_1h, 0)
    total = max(agg, five + one)
    return total - one, one


def int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) else 0


def first_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return None


def extract_message_text(message: Any) -> str | None:
    if not isinstance(message, dict):
        return None
    return truncate_text(content_to_text(message.get("content")), TEXT_PREVIEW_LIMIT * 2)


def _is_real_user_prompt(obj: dict[str, Any]) -> bool:
    """True if the user record is a genuine prompt, not just tool results."""
    message = obj.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    return any(
        (isinstance(block, dict) and block.get("type") != "tool_result")
        or (isinstance(block, str) and block.strip())
        for block in content
    )


def content_to_text(content: Any) -> str | None:
    if isinstance(content, str):
        text = " ".join(content.split())
        return text or None
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            collapsed = " ".join(item.split())
            if collapsed:
                parts.append(collapsed)
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            collapsed = " ".join(text.split())
            if collapsed:
                parts.append(collapsed)
            continue
        thinking = item.get("thinking")
        if isinstance(thinking, str):
            collapsed = " ".join(thinking.split())
            if collapsed:
                parts.append(collapsed)
    joined = " ".join(parts)
    return joined or None


def count_words(text: str | None) -> int:
    return len(text.split()) if text else 0


def build_session_summary(parsed: ParsedSession, *, subagents: Sequence[SubagentInfo]) -> dict[str, Any]:
    tool_usage = Counter[str]()
    tool_errors_by_name = Counter[str]()
    model_counts = Counter[str]()
    request_ids: set[str] = set()
    token_totals = TokenUsage()
    max_tokens_stop_count = 0
    completed_turn_count = 0
    turn_durations: list[int] = []

    server_tool_usage = Counter[str]()
    server_tool_call_count = 0
    server_tool_aborted_count = 0
    server_tool_input_tokens = 0
    server_tool_output_tokens = 0
    server_tool_total_latency_ms = 0

    for turn in parsed.turns:
        if turn.model:
            model_counts[turn.model] += 1
        if turn.request_id:
            request_ids.add(turn.request_id)
        token_totals.input_tokens += turn.token_usage.input_tokens
        token_totals.output_tokens += turn.token_usage.output_tokens
        token_totals.cache_creation_input_tokens += turn.token_usage.cache_creation_input_tokens
        token_totals.cache_read_input_tokens += turn.token_usage.cache_read_input_tokens
        if turn.stop_reason == "max_tokens":
            max_tokens_stop_count += 1
        if turn.turn_duration_ms is not None:
            completed_turn_count += 1
            turn_durations.append(turn.turn_duration_ms)
        for tool_call in turn.tool_calls:
            tool_usage[tool_call.name] += 1
            if tool_call.is_error:
                tool_errors_by_name[tool_call.name] += 1
        for stc in turn.server_tool_calls:
            server_tool_call_count += 1
            server_tool_usage[stc.name] += 1
            if stc.is_aborted:
                server_tool_aborted_count += 1
            server_tool_input_tokens += stc.iteration_input_tokens
            server_tool_output_tokens += stc.iteration_output_tokens
            if stc.latency_ms is not None:
                server_tool_total_latency_ms += stc.latency_ms

    return {
        "path": str(parsed.path),
        "session_id": parsed.session_id,
        "project": parsed.project,
        "project_cwd": parsed.project_cwd,
        "timestamp": isoformat_utc(parsed.start_timestamp),
        "slug": parsed.slug,
        "custom_title": parsed.custom_title,
        "agent_name": parsed.agent_name,
        "latest_git_branch": parsed.latest_git_branch,
        "parse_errors": parsed.parse_errors,
        "record_count": parsed.record_count,
        "record_counts": dict(parsed.record_counts),
        "session_meta": parsed.session_meta or None,
        "first_user_message": parsed.first_user_message,
        "models": dict(model_counts),
        "models_used": list(model_counts),
        "token_usage": {
            "input_tokens": token_totals.input_tokens,
            "output_tokens": token_totals.output_tokens,
            "cache_creation_input_tokens": token_totals.cache_creation_input_tokens,
            "cache_read_input_tokens": token_totals.cache_read_input_tokens,
            "total_tokens": token_totals.total_tokens,
            "api_calls": len(request_ids),
        },
        "tool_usage": dict(tool_usage.most_common()),
        "tool_error_count": sum(tool_errors_by_name.values()),
        "tool_errors_by_name": dict(tool_errors_by_name.most_common()),
        "system_subtypes": dict(parsed.system_subtypes),
        "turn_count": len(parsed.turns),
        "completed_turn_count": completed_turn_count,
        "incomplete_turn_count": len(parsed.turns) - completed_turn_count,
        "max_tokens_stop_count": max_tokens_stop_count,
        "turn_durations_ms": turn_durations,
        "total_turn_duration_ms": sum(turn_durations) if turn_durations else None,
        "api_error_count": parsed.api_error_count,
        "hook_summary": build_hook_summary(parsed.hooks),
        "server_tool_call_count": server_tool_call_count,
        "server_tool_aborted_count": server_tool_aborted_count,
        "server_tool_usage": dict(server_tool_usage.most_common()),
        "server_tool_input_tokens": server_tool_input_tokens,
        "server_tool_output_tokens": server_tool_output_tokens,
        "server_tool_total_latency_ms": server_tool_total_latency_ms,
        "turns": [turn_to_summary(turn) for turn in parsed.turns],
        "pr_links": parsed.pr_links or None,
        "subagents": [_dc_dict(subagent) for subagent in subagents] or None,
    }


def build_hook_summary(hooks: Sequence[HookExecution]) -> dict[str, Any]:
    by_command: dict[str, dict[str, int | str]] = {}
    total_duration_ms = 0
    total_errors = 0
    for hook in hooks:
        total_duration_ms += hook.duration_ms
        if hook.is_error:
            total_errors += 1
        stats = by_command.setdefault(
            hook.command,
            {"command": hook.command, "count": 0, "total_duration_ms": 0, "errors": 0},
        )
        stats["count"] += 1
        stats["total_duration_ms"] += hook.duration_ms
        if hook.is_error:
            stats["errors"] += 1

    ordered = sorted(
        by_command.values(),
        key=lambda item: (-int(item["total_duration_ms"]), -int(item["count"]), str(item["command"])),
    )
    return {
        "count": len(hooks),
        "total_duration_ms": total_duration_ms,
        "errors": total_errors,
        "by_command": ordered,
    }


def turn_to_summary(turn: Turn) -> dict[str, Any]:
    return {
        "index": turn.index,
        "message_id": turn.message_id,
        "timestamp": isoformat_utc(turn.timestamp),
        "model": turn.model,
        "stop_reason": turn.stop_reason,
        "speed": turn.speed,
        "duration_ms": turn.turn_duration_ms,
        "user_gap_ms": turn.user_gap_ms,
        "token_usage": {
            "input_tokens": turn.token_usage.input_tokens,
            "output_tokens": turn.token_usage.output_tokens,
            "cache_creation_input_tokens": turn.token_usage.cache_creation_input_tokens,
            "cache_read_input_tokens": turn.token_usage.cache_read_input_tokens,
            "total_tokens": turn.total_tokens,
        },
        "tool_calls": [
            {
                "id": tool_call.tool_use_id or None,
                "name": tool_call.name,
                "file_path": tool_call.file_path,
                "command": tool_call.command,
                "is_error": tool_call.is_error,
                "error_text": tool_call.error_text,
            }
            for tool_call in turn.tool_calls
        ],
        "server_tool_calls": [
            {
                "id": stc.tool_use_id,
                "name": stc.name,
                "is_aborted": stc.is_aborted,
                "latency_ms": stc.latency_ms,
                "iteration_type": stc.iteration_type,
                "iteration_model": stc.iteration_model,
                "iteration_input_tokens": stc.iteration_input_tokens,
                "iteration_output_tokens": stc.iteration_output_tokens,
            }
            for stc in turn.server_tool_calls
        ],
    }


def summarize_session_ingestion(summary: dict[str, Any]) -> dict[str, Any]:
    return build_ingestion_summary(summary, kind="session_summary")


def build_ingestion_summary(summary: dict[str, Any], *, kind: str) -> dict[str, Any]:
    session_meta = summary.get("session_meta") or {}
    token_usage = summary.get("token_usage") or {}
    title = display_name_for_session(
        custom_title=summary.get("custom_title"),
        agent_name=summary.get("agent_name"),
        slug=summary.get("slug"),
        first_user_message=summary.get("first_user_message"),
    )
    pr_entries = [
        {
            "url": link.get("prUrl"),
            "number": link.get("prNumber"),
            "repository": link.get("prRepository"),
        }
        for link in (summary.get("pr_links") or [])
        if isinstance(link, dict)
    ]
    subagents = [
        ingestion_subagent_entry(summary.get("session_id"), summary.get("project"), item)
        for item in (summary.get("subagents") or [])
        if isinstance(item, dict)
    ]
    dominant_model = dominant_model_from_counts(summary.get("models"))

    return {
        "schema_version": "session_inspector_v2",
        "source": "claude_code",
        "kind": kind,
        "session": {
            "id": summary.get("session_id"),
            "path": summary.get("path"),
            "project": summary.get("project"),
            "cwd": session_meta.get("cwd") or summary.get("project_cwd"),
            "timestamp": session_timestamp_from_summary(summary),
            "title": title,
            "display_name": title,
            "archived": None,
            "version": session_meta.get("version"),
            "model_provider": None,
            "model": dominant_model,
            "git_branch": session_meta.get("gitBranch"),
            "git_commit": None,
            "session_origin": session_meta.get("entrypoint"),
            "is_subagent": False,
            "parent_session_id": None,
            "forked_from_session_id": None,
            "agent": {
                "nickname": summary.get("agent_name"),
                "role": None,
                "path": None,
                "depth": None,
            }
            if summary.get("agent_name")
            else None,
        },
        "content": {
            "first_user_message": summary.get("first_user_message"),
        },
        "counts": {
            "records": summary.get("record_count"),
            "parse_errors": summary.get("parse_errors"),
            "completed_turns": summary.get("completed_turn_count"),
            "incomplete_turns": summary.get("incomplete_turn_count"),
            "tool_error_count": summary.get("tool_error_count"),
            "api_error_count": summary.get("api_error_count"),
            "max_tokens_stop_count": summary.get("max_tokens_stop_count"),
            "server_tool_call_count": summary.get("server_tool_call_count"),
            "server_tool_aborted_count": summary.get("server_tool_aborted_count"),
            "by_record_type": counter_dict_to_rows(summary.get("record_counts")),
            "by_event_type": counter_dict_to_rows(summary.get("system_subtypes"), key_name="event"),
            "by_item_type": [],
        },
        "usage": {
            "models": counter_dict_to_rows(summary.get("models"), key_name="model"),
            "tokens": {
                "mode": "request_deduped",
                "input": token_usage.get("input_tokens"),
                "output": token_usage.get("output_tokens"),
                "cache_create": token_usage.get("cache_creation_input_tokens"),
                "cache_read": token_usage.get("cache_read_input_tokens"),
                "reasoning_output": None,
                "total": token_usage.get("total_tokens"),
                "api_calls_exact": token_usage.get("api_calls"),
                "api_calls_approx": None,
                "note": None,
            },
            "tools": ingestion_tool_entries(
                summary.get("tool_usage"),
                tool_errors_by_name=summary.get("tool_errors_by_name"),
            ),
            "server_tools": ingestion_server_tool_entries(summary.get("server_tool_usage")),
        },
        "turns": {
            "completed": summary.get("completed_turn_count"),
            "incomplete": summary.get("incomplete_turn_count"),
            "total_duration_ms": summary.get("total_turn_duration_ms"),
            "durations": [
                {"duration_ms": duration}
                for duration in (summary.get("turn_durations_ms") or [])
            ],
        },
        "links": {
            "prs": pr_entries,
        },
        "subagents": subagents,
    }


def session_timestamp_from_summary(summary: dict[str, Any]) -> str | None:
    timestamp = summary.get("timestamp")
    return timestamp if isinstance(timestamp, str) else None


def display_name_for_session(
    *,
    custom_title: str | None,
    agent_name: str | None,
    slug: str | None,
    first_user_message: str | None,
) -> str | None:
    if custom_title:
        return custom_title
    if agent_name:
        return agent_name
    if slug:
        return slug
    if first_user_message:
        return preview_text(first_user_message)
    return None


def preview_text(value: str | None, *, limit: int = 120) -> str | None:
    if not value:
        return None
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 1]}…"


def truncate_text(value: str | None, limit: int) -> str | None:
    if not value:
        return None
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 1]}…"


def isoformat_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def counter_dict_to_rows(value: dict[str, int] | None, *, key_name: str = "type") -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    return [
        {key_name: key, "count": count}
        for key, count in sorted(value.items(), key=lambda item: (-item[1], item[0]))
    ]


def ingestion_tool_entries(
    tool_usage: dict[str, int] | None,
    *,
    tool_errors_by_name: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(tool_usage, dict):
        return []
    errors = tool_errors_by_name if isinstance(tool_errors_by_name, dict) else {}
    return [
        {
            "name": name,
            "count": count,
            "errors": errors.get(name, 0),
            "kind": "tool_use",
        }
        for name, count in sorted(tool_usage.items(), key=lambda item: (-item[1], item[0]))
    ]


def ingestion_server_tool_entries(
    server_tool_usage: dict[str, int] | None,
) -> list[dict[str, Any]]:
    if not isinstance(server_tool_usage, dict):
        return []
    return [
        {
            "name": name,
            "count": count,
            "kind": "server_tool_use",
        }
        for name, count in sorted(server_tool_usage.items(), key=lambda item: (-item[1], item[0]))
    ]


def ingestion_subagent_entry(
    parent_session_id: str | None,
    project: str | None,
    subagent: dict[str, Any],
) -> dict[str, Any]:
    token_usage = subagent.get("token_usage") or {}
    title = preview_text(subagent.get("first_task"))
    return {
        "id": subagent.get("agent_id"),
        "path": subagent.get("path"),
        "title": title,
        "display_name": title,
        "project": project,
        "cwd": subagent.get("project_cwd"),
        "model": subagent.get("model"),
        "token_total": token_usage.get("total_tokens"),
        "agent": {
            "nickname": None,
            "role": None,
            "path": None,
            "depth": None,
        },
        "parent_session_id": parent_session_id,
    }


def filter_records(
    records: Iterable[dict[str, Any]],
    *,
    record_type: str | None,
    tool_name: str | None,
    system_subtype: str | None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for obj in records:
        if record_type is not None and obj.get("type") != record_type:
            continue
        if system_subtype is not None:
            if obj.get("type") != "system" or obj.get("subtype") != system_subtype:
                continue
        if tool_name is not None and not _has_tool_use(obj, tool_name):
            continue
        matches.append(obj)
    return matches


def _has_tool_use(obj: dict[str, Any], tool_name: str) -> bool:
    if obj.get("type") != "assistant":
        return False
    message = obj.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(block, dict)
        and block.get("type") == "tool_use"
        and block.get("name") == tool_name
        for block in content
    )


def list_subagents(session_path: Path) -> list[SubagentInfo]:
    session_id = session_path.stem
    subagents_dir = session_path.parent / session_id / "subagents"
    if not subagents_dir.exists():
        return []

    infos: list[SubagentInfo] = []
    # Recurse so nested workflow subagents under subagents/workflows/<wf>/ are
    # discovered, not just direct children.  ``workflows/.../journal.jsonl`` and
    # ``agent-*.meta.json`` sidecars are excluded by the ``agent-*.jsonl`` glob
    # plus the SUBAGENT_RE filename check.
    for path in sorted(subagents_dir.rglob("agent-*.jsonl")):
        if not path.is_file() or not SUBAGENT_RE.match(path.name):
            continue
        agent_id = IMPORTER.subagent_agent_id(path)
        if agent_id is None:
            continue
        infos.append(_parse_subagent_summary(path, agent_id))
    return infos


def _resolve_subagent_path(subagents_dir: Path, agent_id: str) -> Path | None:
    """Resolve a (possibly path-qualified) agent id back to its transcript.

    Direct subagents use a bare hex id; nested workflow subagents use a
    ``<reldir>/<hex>`` id.  Bare ids keep the historical prefix-match tolerance.
    """
    if not subagents_dir.exists():
        return None
    if "/" in agent_id:
        rel_dir, hex_id = agent_id.rsplit("/", 1)
        candidate = subagents_dir / rel_dir / f"agent-{hex_id}.jsonl"
        return candidate if candidate.is_file() else None
    candidate = subagents_dir / f"agent-{agent_id}.jsonl"
    if candidate.is_file():
        return candidate
    matches = sorted(subagents_dir.glob(f"agent-{agent_id}*.jsonl"))
    return matches[0] if matches else None


def inspect_subagent(session_path: Path, agent_id: str) -> dict[str, Any]:
    subagents_dir = session_path.parent / session_path.stem / "subagents"
    agent_path = _resolve_subagent_path(subagents_dir, agent_id)
    if agent_path is None:
        raise FileNotFoundError(f"no subagent file found for agent_id: {agent_id}")

    loaded = load_session(agent_path)
    project = project_dir_name_for_path(agent_path)
    project_cwd = decode_project_dir_name(project) if project else None
    parsed = parse_loaded_session(
        loaded,
        session_id_override=agent_path.stem,
        project=project,
        project_cwd=project_cwd,
    )
    return build_subagent_summary(
        parsed,
        parent_session_id=session_path.stem,
        agent_id=agent_id,
    )


def build_subagent_summary(
    parsed: ParsedSession,
    *,
    parent_session_id: str,
    agent_id: str | None = None,
) -> dict[str, Any]:
    session_summary = build_session_summary(parsed, subagents=[])
    return {
        "agent_id": agent_id if agent_id is not None else parsed.session_id.removeprefix("agent-"),
        "path": session_summary["path"],
        "project": session_summary["project"],
        "project_cwd": session_summary["project_cwd"],
        "parent_session_id": parent_session_id,
        "record_count": session_summary["record_count"],
        "record_counts": session_summary["record_counts"],
        "model": dominant_model_from_counts(session_summary["models"]),
        "first_task": session_summary["first_user_message"],
        "tool_usage": session_summary["tool_usage"],
        "tool_error_count": session_summary["tool_error_count"],
        "tool_errors_by_name": session_summary["tool_errors_by_name"],
        "token_usage": session_summary["token_usage"],
        "system_subtypes": session_summary["system_subtypes"],
        "turn_count": session_summary["turn_count"],
        "completed_turn_count": session_summary["completed_turn_count"],
        "incomplete_turn_count": session_summary["incomplete_turn_count"],
        "max_tokens_stop_count": session_summary["max_tokens_stop_count"],
        "api_error_count": session_summary["api_error_count"],
        "hook_summary": session_summary["hook_summary"],
        "server_tool_call_count": session_summary["server_tool_call_count"],
        "server_tool_aborted_count": session_summary["server_tool_aborted_count"],
        "server_tool_usage": session_summary["server_tool_usage"],
        "server_tool_input_tokens": session_summary["server_tool_input_tokens"],
        "server_tool_output_tokens": session_summary["server_tool_output_tokens"],
        "server_tool_total_latency_ms": session_summary["server_tool_total_latency_ms"],
        "turns": session_summary["turns"],
        "session_meta": session_summary["session_meta"],
        "parse_errors": session_summary["parse_errors"],
    }


def build_subagent_ingestion_summary(session_path: Path, info: dict[str, Any]) -> dict[str, Any]:
    token_usage = info.get("token_usage") or {}
    title = preview_text(info.get("first_task"))
    return {
        "schema_version": "session_inspector_v2",
        "source": "claude_code",
        "kind": "subagent_summary",
        "session": {
            "id": info.get("agent_id"),
            "path": info.get("path"),
            "project": info.get("project"),
            "cwd": info.get("project_cwd"),
            "timestamp": None,
            "title": title,
            "display_name": title,
            "archived": None,
            "version": None,
            "model_provider": None,
            "model": info.get("model"),
            "git_branch": None,
            "git_commit": None,
            "session_origin": "subagent",
            "is_subagent": True,
            "parent_session_id": session_path.stem,
            "forked_from_session_id": None,
            "agent": {
                "nickname": None,
                "role": None,
                "path": None,
                "depth": None,
            },
        },
        "content": {
            "first_user_message": info.get("first_task"),
        },
        "counts": {
            "records": info.get("record_count"),
            "parse_errors": info.get("parse_errors"),
            "completed_turns": info.get("completed_turn_count"),
            "incomplete_turns": info.get("incomplete_turn_count"),
            "tool_error_count": info.get("tool_error_count"),
            "api_error_count": info.get("api_error_count"),
            "max_tokens_stop_count": info.get("max_tokens_stop_count"),
            "by_record_type": counter_dict_to_rows(info.get("record_counts")),
            "by_event_type": counter_dict_to_rows(info.get("system_subtypes"), key_name="event"),
            "by_item_type": [],
        },
        "usage": {
            "models": (
                [{"model": info["model"], "count": 1}]
                if info.get("model")
                else []
            ),
            "tokens": {
                "mode": "request_deduped",
                "input": token_usage.get("input_tokens"),
                "output": token_usage.get("output_tokens"),
                "cache_create": token_usage.get("cache_creation_input_tokens"),
                "cache_read": token_usage.get("cache_read_input_tokens"),
                "reasoning_output": None,
                "total": token_usage.get("total_tokens"),
                "api_calls_exact": token_usage.get("api_calls"),
                "api_calls_approx": None,
                "note": None,
            },
            "tools": ingestion_tool_entries(
                info.get("tool_usage"),
                tool_errors_by_name=info.get("tool_errors_by_name"),
            ),
        },
        "turns": {
            "completed": info.get("completed_turn_count"),
            "incomplete": info.get("incomplete_turn_count"),
            "total_duration_ms": None,
            "durations": [],
        },
        "links": {
            "prs": [],
        },
        "subagents": [],
    }


def _parse_subagent_summary(path: Path, agent_id: str) -> SubagentInfo:
    record_count = 0
    model: str | None = None
    first_task: str | None = None
    try:
        with path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                record_count += 1
                record_type = obj.get("type")
                if record_type == "user" and first_task is None:
                    first_task = extract_message_text(obj.get("message"))
                if record_type == "assistant" and model is None:
                    message = obj.get("message")
                    if isinstance(message, dict):
                        candidate = message.get("model")
                        if isinstance(candidate, str) and candidate:
                            model = candidate
    except OSError:
        pass
    return SubagentInfo(
        agent_id=agent_id,
        path=path,
        record_count=record_count,
        model=model,
        first_task=first_task,
    )


def project_dir_name_for_path(path: Path) -> str | None:
    # For a subagent transcript (direct or nested under subagents/workflows/...),
    # the project dir is the grandparent of the `subagents` dir:
    # projects/<project>/<session_id>/subagents/[workflows/<wf>/]agent-*.jsonl
    for ancestor in path.parents:
        if ancestor.name == "subagents":
            return ancestor.parent.parent.name or None
    return path.parent.name if path.parent.name else None


def dominant_model_from_counts(models: dict[str, int] | None) -> str | None:
    if not isinstance(models, dict) or not models:
        return None
    return max(models.items(), key=lambda item: (item[1], item[0]))[0]


def emit(as_json: bool, payload: Any) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return
    match payload:
        case dict():
            for key, value in payload.items():
                if isinstance(value, (dict, list)):
                    print(f"{key}: {json.dumps(value, default=str)}")
                else:
                    print(f"{key}: {value}")
        case list():
            for item in payload:
                print(json.dumps(item, default=str))
        case _:
            print(payload)


if __name__ == "__main__":
    sys.exit(main())
