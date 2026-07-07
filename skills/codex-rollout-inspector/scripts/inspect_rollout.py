#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///
"""Locate and inspect Codex rollout logs under CODEX_HOME or ~/.codex."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import sys
import tomllib
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROLLOUT_RE = re.compile(
    r"^rollout-(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-(?P<thread_id>[^/]+)\.jsonl$"
)
THREAD_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
GITHUB_PR_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+")

FUNCTION_CALL_TYPE = "function_call"
CUSTOM_TOOL_CALL_TYPE = "custom_tool_call"
FUNCTION_CALL_OUTPUT_TYPE = "function_call_output"
CUSTOM_TOOL_CALL_OUTPUT_TYPE = "custom_tool_call_output"
TOOL_SEARCH_CALL_TYPE = "tool_search_call"
TOOL_SEARCH_OUTPUT_TYPE = "tool_search_output"
LOCAL_SHELL_CALL_TYPE = "local_shell_call"
WEB_SEARCH_CALL_TYPE = "web_search_call"
IMAGE_GENERATION_CALL_TYPE = "image_generation_call"
SCRIPT_DIR = Path(__file__).resolve().parent
_QUICK_CACHE_BY_KEY: dict[tuple[str, str, str, int, int], "QuickRolloutCache"] = {}


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


DB = _load_support_module("codex_rollout_inspector_db", "db.py")
IMPORTER = _load_support_module("codex_rollout_inspector_importer", "importer.py")

OUTPUT_BACKED_TOOL_CALL_TYPES = {
    FUNCTION_CALL_TYPE,
    CUSTOM_TOOL_CALL_TYPE,
    TOOL_SEARCH_CALL_TYPE,
}
DIRECT_STATUS_TOOL_CALL_TYPES = {
    LOCAL_SHELL_CALL_TYPE,
    WEB_SEARCH_CALL_TYPE,
    IMAGE_GENERATION_CALL_TYPE,
}
NATIVE_TOOL_CALL_TYPES = {
    LOCAL_SHELL_CALL_TYPE,
    TOOL_SEARCH_CALL_TYPE,
    WEB_SEARCH_CALL_TYPE,
    IMAGE_GENERATION_CALL_TYPE,
}
ALL_TOOL_CALL_TYPES = OUTPUT_BACKED_TOOL_CALL_TYPES | DIRECT_STATUS_TOOL_CALL_TYPES


def _dc_dict(obj: Any) -> dict[str, Any]:
    return {
        field.name: _normalize_json_value(getattr(obj, field.name))
        for field in obj.__class__.__dataclass_fields__.values()
    }


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


@dataclass(slots=True)
class RolloutPaths:
    codex_home: Path
    sessions_dir: Path
    archived_sessions_dir: Path
    history_path: Path
    session_index_path: Path
    log_dir: Path


@dataclass(slots=True)
class LoadedRollout:
    path: Path
    records: list[dict[str, Any]]
    parse_errors: int


@dataclass(slots=True)
class QuickRollout:
    path: Path
    archived: bool
    thread_id: str
    filename_timestamp: str | None
    thread_name: str | None
    title: str | None
    cwd: str | None
    project: str | None
    first_user_message: str | None
    model: str | None
    forked_from_id: str | None
    parent_thread_id: str | None
    agent_nickname: str | None
    agent_role: str | None
    agent_path: str | None

    @property
    def is_subagent(self) -> bool:
        return any(
            value
            for value in (
                self.agent_nickname,
                self.agent_role,
                self.agent_path,
                self.parent_thread_id,
                self.forked_from_id,
            )
        )


class QuickRolloutCache:
    """Pre-built index over all rollout files for O(1) lookups.

    Eliminates the O(n^2) cost of repeatedly calling collect_quick_rollouts
    inside resolve_target during bulk import / tree-root resolution.
    """

    def __init__(
        self,
        paths: "RolloutPaths",
        thread_names: dict[str, str],
    ) -> None:
        self._paths = paths
        self._thread_names = thread_names
        self._by_path: dict[str, QuickRollout] = {}
        self._by_thread_id: dict[str, list[QuickRollout]] = {}
        self._children_by_parent_id: dict[str, list[QuickRollout]] = {}
        self._populated = False

    def _ensure_populated(self) -> None:
        if self._populated:
            return
        for archived_mode in (False, True):
            for path in collect_rollouts(self._paths, archived=archived_mode, since=None):
                qi = quick_rollout_info(path, self._thread_names)
                self._by_path[str(path)] = qi
                self._by_thread_id.setdefault(qi.thread_id, []).append(qi)
                parent_thread_id = qi.parent_thread_id or qi.forked_from_id
                if parent_thread_id:
                    self._children_by_parent_id.setdefault(parent_thread_id, []).append(qi)
        for children in self._children_by_parent_id.values():
            children.sort(key=lambda item: item.filename_timestamp or "")
        self._populated = True

    def get_quick_info(self, path: Path) -> QuickRollout:
        self._ensure_populated()
        key = str(path)
        cached = self._by_path.get(key)
        if cached is not None:
            return cached
        qi = quick_rollout_info(path, self._thread_names)
        self._by_path[key] = qi
        self._by_thread_id.setdefault(qi.thread_id, []).append(qi)
        parent_thread_id = qi.parent_thread_id or qi.forked_from_id
        if parent_thread_id:
            children = self._children_by_parent_id.setdefault(parent_thread_id, [])
            children.append(qi)
            children.sort(key=lambda item: item.filename_timestamp or "")
        return qi

    def resolve_thread_id(self, thread_id: str) -> Path:
        self._ensure_populated()
        matches = self._by_thread_id.get(thread_id)
        if not matches:
            raise FileNotFoundError(f"could not resolve rollout target: {thread_id}")
        return matches[-1].path

    def children_for_parent(self, parent_thread_id: str) -> list[QuickRollout]:
        self._ensure_populated()
        return list(self._children_by_parent_id.get(parent_thread_id, ()))

    def collect(
        self,
        *,
        archived: bool,
        since: date | None,
        project: str | None,
        include_subagents: bool = True,
    ) -> list[QuickRollout]:
        self._ensure_populated()
        result: list[QuickRollout] = []
        for qi in self._by_path.values():
            is_archived = "archived_sessions" in qi.path.parts
            if is_archived != archived:
                continue
            if since is not None:
                rd = rollout_date(qi.path)
                if rd is None or rd < since:
                    continue
            if project is not None and not matches_project(qi, project):
                continue
            if not include_subagents and qi.is_subagent:
                continue
            result.append(qi)
        return result


def get_quick_rollout_cache(
    paths: RolloutPaths,
    thread_names: dict[str, str],
) -> QuickRolloutCache:
    try:
        session_index_stat = paths.session_index_path.stat()
        session_index_mtime_ns = session_index_stat.st_mtime_ns
        session_index_size = session_index_stat.st_size
    except OSError:
        session_index_mtime_ns = -1
        session_index_size = -1
    key = (
        str(paths.sessions_dir),
        str(paths.archived_sessions_dir),
        str(paths.session_index_path),
        session_index_mtime_ns,
        session_index_size,
    )
    cache = _QUICK_CACHE_BY_KEY.get(key)
    if cache is None:
        cache = QuickRolloutCache(paths, thread_names)
        _QUICK_CACHE_BY_KEY[key] = cache
    return cache


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
        description="Locate and inspect Codex rollout logs.",
        suggest_on_error=True,
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=None,
        help="Override CODEX_HOME. Defaults to $CODEX_HOME or ~/.codex.",
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

    subparsers.add_parser("locate", help="Print key Codex log locations.")

    list_parser = subparsers.add_parser("list", help="List rollout files.")
    list_parser.add_argument(
        "--archived",
        action="store_true",
        help="List archived rollout files instead of active session files.",
    )
    list_parser.add_argument(
        "--since",
        type=parse_since_date,
        default=None,
        help="Keep rollout files whose filename date is on or after YYYY-MM-DD.",
    )
    list_parser.add_argument(
        "--project",
        default=None,
        help="Filter by cwd/project substring.",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of results to print.",
    )

    summary_parser = subparsers.add_parser(
        "summary",
        help="Summarize a rollout file by path or thread id. Defaults to latest active rollout.",
    )
    summary_parser.add_argument(
        "target",
        nargs="?",
        help="Rollout path or thread id. If omitted, uses the latest matching rollout.",
    )
    summary_parser.add_argument(
        "--archived",
        action="store_true",
        help="When target is omitted, summarize the latest archived rollout.",
    )
    summary_parser.add_argument(
        "--project",
        default=None,
        help="Filter by cwd/project substring when selecting a rollout.",
    )

    refresh_parser = subparsers.add_parser(
        "refresh",
        help="Incrementally import rollout data into SQLite.",
    )
    refresh_parser.add_argument(
        "target",
        nargs="?",
        help="Rollout path or thread id. If omitted, refreshes matching rollouts.",
    )
    refresh_parser.add_argument(
        "--archived",
        action="store_true",
        help="Refresh archived rollouts only when target is omitted.",
    )
    refresh_parser.add_argument(
        "--project",
        default=None,
        help="Filter by cwd/project substring.",
    )
    refresh_parser.add_argument(
        "--since",
        type=parse_since_date,
        default=None,
        help="Refresh only rollouts on or after YYYY-MM-DD.",
    )
    refresh_parser.add_argument(
        "--pending",
        action="store_true",
        help="Reconcile due pending markers only, without scanning other rollouts.",
    )

    rebuild_parser = subparsers.add_parser(
        "rebuild",
        help="Delete and rebuild the SQLite cache from raw rollouts.",
    )
    rebuild_parser.add_argument(
        "--archived",
        action="store_true",
        help="Rebuild archived rollouts only.",
    )
    rebuild_parser.add_argument(
        "--project",
        default=None,
        help="Filter by cwd/project substring.",
    )
    rebuild_parser.add_argument(
        "--since",
        type=parse_since_date,
        default=None,
        help="Rebuild only rollouts on or after YYYY-MM-DD.",
    )

    records_parser = subparsers.add_parser(
        "records",
        help="Print raw matching rollout records by path or thread id.",
    )
    records_parser.add_argument(
        "target",
        nargs="?",
        help="Rollout path or thread id. If omitted, uses the latest matching rollout.",
    )
    records_parser.add_argument(
        "--archived",
        action="store_true",
        help="When target is omitted, inspect the latest archived rollout.",
    )
    records_parser.add_argument(
        "--project",
        default=None,
        help="Filter by cwd/project substring when selecting a rollout.",
    )
    records_parser.add_argument(
        "--record-type",
        default=None,
        help="Filter top-level record type such as session_meta, turn_context, event_msg, response_item.",
    )
    records_parser.add_argument(
        "--payload-type",
        default=None,
        help="Filter nested payload.type when present.",
    )
    records_parser.add_argument(
        "--tool-name",
        default=None,
        help="Filter response_item tool calls by derived tool name, such as exec_command or local_shell_call.",
    )
    records_parser.add_argument(
        "--tail",
        type=int,
        default=20,
        help="Return only the last N matching records.",
    )

    subagents_parser = subparsers.add_parser(
        "subagents",
        help="List or inspect subagent rollouts for a parent thread.",
    )
    subagents_parser.add_argument(
        "target",
        nargs="?",
        help="Parent rollout path or thread id. If omitted, uses the latest matching rollout.",
    )
    subagents_parser.add_argument(
        "--archived",
        action="store_true",
        help="When target is omitted, start from the latest archived rollout.",
    )
    subagents_parser.add_argument(
        "--project",
        default=None,
        help="Filter by cwd/project substring when selecting the parent rollout.",
    )
    subagents_parser.add_argument(
        "--agent",
        default=None,
        help="Filter child rollouts by agent nickname, agent path, thread id, or thread name substring.",
    )

    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    paths = resolve_paths(args.codex_home)
    thread_names = load_session_index(paths.session_index_path)
    db_path = DB.default_db_path(paths.codex_home)

    match args.command:
        case "locate":
            emit(args.json, locate_payload(paths, db_path=db_path, cwd=Path.cwd()))
            return 0
        case "refresh":
            if args.pending:
                reconciled = IMPORTER.reconcile_pending(paths.codex_home)
                result = {
                    "reconciled_pending": reconciled,
                    "reconciled_pending_count": len(reconciled),
                    "pending_markers": DB.pending_marker_stats(db_path),
                    "db_path": str(db_path),
                }
            else:
                result = IMPORTER.refresh_rollouts(
                    paths.codex_home,
                    target=args.target,
                    archived=True if args.archived else None,
                    project=args.project,
                    since=args.since,
                )
            emit(args.json, result)
            return 0
        case "rebuild":
            result = IMPORTER.rebuild_rollouts(
                paths.codex_home,
                archived=True if args.archived else None,
                project=args.project,
                since=args.since,
            )
            emit(args.json, result)
            return 0
        case "list":
            if db_path.exists():
                raw_rollouts = collect_quick_rollouts(
                    paths,
                    thread_names,
                    archived=args.archived,
                    since=args.since,
                    project=args.project,
                    include_subagents=False,
                )
                IMPORTER.refresh_rollouts(
                    paths.codex_home,
                    rollout_paths=[item.path for item in raw_rollouts],
                )
                emit(
                    args.json,
                    IMPORTER.list_payload(
                        paths.codex_home,
                        archived=args.archived,
                        project=args.project,
                        since=args.since,
                        limit=args.limit,
                        profile=args.profile,
                    ),
                )
                return 0
            print(
                "SQLite cache not found; using stateless rollout scan. Run `refresh` to create it.",
                file=sys.stderr,
            )
            rollouts = collect_quick_rollouts(
                paths,
                thread_names,
                archived=args.archived,
                since=args.since,
                project=args.project,
                include_subagents=False,
            )
            selected = rollouts[-args.limit :][::-1]
            if args.profile == "ingestion":
                payload = [ingestion_stub_from_quick(item) for item in selected]
            else:
                payload = [_dc_dict(item) for item in selected]
            emit(args.json, payload)
            return 0
        case "summary":
            rollout_path = resolve_target(
                paths,
                thread_names,
                args.target,
                archived=args.archived,
                project=args.project,
                prefer_parent_on_default=True,
            )
            if db_path.exists():
                IMPORTER.refresh_rollouts(paths.codex_home, rollout_paths=[rollout_path])
                payload = IMPORTER.summary_payload(
                    paths.codex_home,
                    quick_rollout_info(rollout_path, thread_names).thread_id,
                    profile=args.profile,
                )
                if payload is not None:
                    emit(args.json, payload)
                    return 0
            else:
                print(
                    "SQLite cache not found; using stateless rollout summary. Run `refresh` to create it.",
                    file=sys.stderr,
                )
            loaded = load_rollout(rollout_path)
            if args.profile == "ingestion":
                payload = summarize_rollout_ingestion(loaded, paths, thread_names)
            else:
                payload = summarize_rollout(loaded, paths, thread_names)
            emit(args.json, payload)
            return 0
        case "records":
            rollout_path = resolve_target(
                paths,
                thread_names,
                args.target,
                archived=args.archived,
                project=args.project,
                prefer_parent_on_default=True,
            )
            loaded = load_rollout(rollout_path)
            matches = filter_records(
                loaded.records,
                record_type=args.record_type,
                payload_type=args.payload_type,
                tool_name=args.tool_name,
            )
            emit(args.json, matches[-args.tail :])
            return 0
        case "subagents":
            rollout_path = resolve_target(
                paths,
                thread_names,
                args.target,
                archived=args.archived,
                project=args.project,
            )
            if db_path.exists():
                IMPORTER.refresh_rollouts(paths.codex_home, rollout_paths=[rollout_path])
                payload = IMPORTER.subagents_payload(
                    paths.codex_home,
                    quick_rollout_info(rollout_path, thread_names).thread_id,
                    profile=args.profile,
                    agent=args.agent,
                )
                if payload is not None:
                    emit(args.json, payload)
                    return 0
            else:
                print(
                    "SQLite cache not found; using stateless subagent scan. Run `refresh` to create it.",
                    file=sys.stderr,
                )
            children = list_child_rollouts(rollout_path, paths, thread_names)
            if args.agent is not None:
                children = [child for child in children if matches_agent_filter(child, args.agent)]
            if args.profile == "ingestion":
                payload = [
                    summarize_rollout_ingestion(
                        load_rollout(child.path),
                        paths,
                        thread_names,
                        include_subagents=False,
                        kind="subagent_summary",
                    )
                    for child in children
                ]
            else:
                payload = [summarize_child_rollout(child.path, paths, thread_names) for child in children]
            emit(args.json, payload)
            return 0
        case _:
            raise ValueError(f"unsupported command: {args.command}")


def resolve_paths(override: Path | None) -> RolloutPaths:
    if override is not None:
        codex_home = override.expanduser()
    else:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    return RolloutPaths(
        codex_home=codex_home,
        sessions_dir=codex_home / "sessions",
        archived_sessions_dir=codex_home / "archived_sessions",
        history_path=codex_home / "history.jsonl",
        session_index_path=codex_home / "session_index.jsonl",
        log_dir=codex_home / "log",
    )


def parse_since_date(value: str) -> date:
    return date.fromisoformat(value)


def find_git_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).expanduser().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def candidate_config_paths(
    codex_home: Path,
    filename: str,
    *,
    cwd: Path | None = None,
) -> list[tuple[str, Path]]:
    # Codex discovers hooks/config files from active config layers such as the
    # user config folder and the current repo root.
    candidates: list[tuple[str, Path]] = [("user", codex_home / filename)]
    git_root = find_git_root(cwd)
    if git_root is not None:
        repo_candidate = git_root / ".codex" / filename
        if repo_candidate != candidates[0][1]:
            candidates.append(("repo", repo_candidate))
    return candidates


def hook_config_candidate(path: Path, *, scope: str) -> dict[str, Any]:
    candidate = {
        "scope": scope,
        "path": str(path),
        "exists": path.exists(),
        "stop_command_count": 0,
        "codex_rollout_inspector_stop_hook": False,
        "parse_error": None,
    }
    if not path.exists():
        return candidate
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        candidate["parse_error"] = str(exc)
        return candidate
    if not isinstance(payload, dict):
        candidate["parse_error"] = "hooks.json did not contain a JSON object"
        return candidate
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return candidate
    stop_groups = hooks.get("Stop")
    if not isinstance(stop_groups, list):
        return candidate
    stop_commands = 0
    matched_command = False
    for group in stop_groups:
        if not isinstance(group, dict):
            continue
        handlers = group.get("hooks")
        if not isinstance(handlers, list):
            continue
        for handler in handlers:
            if not isinstance(handler, dict) or handler.get("type") != "command":
                continue
            command = string_or_none(handler.get("command"))
            if command is None:
                continue
            stop_commands += 1
            if "sync_rollout.py" in command:
                matched_command = True
    candidate["stop_command_count"] = stop_commands
    candidate["codex_rollout_inspector_stop_hook"] = matched_command
    return candidate


def config_toml_candidate(path: Path, *, scope: str) -> dict[str, Any]:
    candidate = {
        "scope": scope,
        "path": str(path),
        "exists": path.exists(),
        "hooks": None,
        "codex_hooks": None,
        "parse_error": None,
    }
    if not path.exists():
        return candidate
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        candidate["parse_error"] = str(exc)
        return candidate
    features = payload.get("features")
    if not isinstance(features, dict):
        return candidate
    hooks = features.get("hooks")
    if isinstance(hooks, bool):
        candidate["hooks"] = hooks
    codex_hooks = features.get("codex_hooks")
    if isinstance(codex_hooks, bool):
        candidate["codex_hooks"] = codex_hooks
    return candidate


def recommended_stop_hook_command() -> str:
    resolver = (
        "import os, sys; "
        "from pathlib import Path; "
        'codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser(); '
        'installed = codex_home / "skills" / "codex-rollout-inspector" / "scripts" / "sync_rollout.py"; '
        'selected = installed if installed.is_file() else None; '
        'root = codex_home / "plugins" / "cache"; '
        'matches = sorted('
        'root.glob("*/codex-rollout-inspector/*/skills/codex-rollout-inspector/scripts/sync_rollout.py"), '
        'key=lambda p: (p.stat().st_mtime_ns, str(p)), '
        'reverse=True'
        ') if root.exists() else []; '
        'selected = selected or (matches[0] if matches else None); '
        'sys.stdout.write(str(selected) if selected else "")'
    )
    return (
        f'script="$(python3 -c {shlex.quote(resolver)} 2>/dev/null)"; '
        '[ -n "$script" ] && { "$script" || python3 "$script"; } || exit 0'
    )


def locate_payload(
    paths: RolloutPaths,
    *,
    db_path: Path,
    cwd: Path | None = None,
) -> dict[str, Any]:
    latest_active = latest_rollout(paths.sessions_dir)
    latest_archived = latest_rollout(paths.archived_sessions_dir)
    db_info = DB.database_stats(db_path)
    pending_stats = DB.pending_marker_stats(db_path)
    hook_candidates = [
        hook_config_candidate(path, scope=scope)
        for scope, path in candidate_config_paths(paths.codex_home, "hooks.json", cwd=cwd)
    ]
    config_candidates = [
        config_toml_candidate(path, scope=scope)
        for scope, path in candidate_config_paths(paths.codex_home, "config.toml", cwd=cwd)
    ]
    configured_hook_paths = [
        candidate["path"]
        for candidate in hook_candidates
        if candidate["codex_rollout_inspector_stop_hook"]
    ]
    return {
        "codex_home": str(paths.codex_home),
        "sessions_dir": str(paths.sessions_dir),
        "archived_sessions_dir": str(paths.archived_sessions_dir),
        "history_path": str(paths.history_path),
        "session_index_path": str(paths.session_index_path),
        "log_dir": str(paths.log_dir),
        "db_path": str(db_path),
        "db_exists": db_info["exists"],
        "db_session_count": db_info["session_count"],
        "db_subagent_count": db_info["subagent_count"],
        "db_last_import_at": db_info["last_import_at"],
        "pending_dir": str(DB.pending_dir(db_path)),
        "pending_markers": pending_stats,
        "hook_config_path": hook_candidates[0]["path"],
        "hook_config_paths": [candidate["path"] for candidate in hook_candidates],
        "hook_config_candidates": hook_candidates,
        "hook_configured_paths": configured_hook_paths,
        "hook_configured": bool(configured_hook_paths),
        "config_toml_paths": [candidate["path"] for candidate in config_candidates],
        "config_toml_candidates": config_candidates,
        "hooks_enabled": any(candidate["hooks"] is True for candidate in config_candidates),
        "legacy_codex_hooks_enabled": any(candidate["codex_hooks"] is True for candidate in config_candidates),
        "codex_hooks_enabled": any(
            candidate["hooks"] is True or candidate["codex_hooks"] is True
            for candidate in config_candidates
        ),
        "hooks_feature_flag": "[features]\nhooks = true",
        "codex_hooks_feature_flag": "[features]\nhooks = true",
        "hook_command": recommended_stop_hook_command(),
        "hook_discovery_scope": "config_layers",
        "latest_rollout": str(latest_active) if latest_active else None,
        "latest_archived_rollout": str(latest_archived) if latest_archived else None,
    }


def load_session_index(path: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    if not path.exists():
        return names
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        thread_id = obj.get("id")
        thread_name = obj.get("thread_name")
        if isinstance(thread_id, str) and isinstance(thread_name, str):
            names[thread_id] = thread_name
    return names


def latest_rollout(root: Path) -> Path | None:
    rollouts = collect_rollouts_in_root(root)
    return rollouts[-1] if rollouts else None


def collect_rollouts_in_root(root: Path) -> list[Path]:
    if not root.exists():
        return []
    glob_pattern = "*.jsonl" if root.name == "archived_sessions" else "*/*/*/rollout-*.jsonl"
    paths = sorted(root.glob(glob_pattern))
    return [path for path in paths if path.is_file() and ROLLOUT_RE.match(path.name)]


def collect_rollouts(
    paths: RolloutPaths,
    *,
    archived: bool,
    since: date | None,
) -> list[Path]:
    root = paths.archived_sessions_dir if archived else paths.sessions_dir
    rollouts = collect_rollouts_in_root(root)
    if since is None:
        return rollouts
    return [path for path in rollouts if (rollout_dt := rollout_date(path)) is not None and rollout_dt >= since]


def collect_quick_rollouts(
    paths: RolloutPaths,
    thread_names: dict[str, str],
    *,
    archived: bool,
    since: date | None,
    project: str | None,
    include_subagents: bool = True,
) -> list[QuickRollout]:
    cache = get_quick_rollout_cache(paths, thread_names)
    return cache.collect(
        archived=archived,
        since=since,
        project=project,
        include_subagents=include_subagents,
    )


def rollout_date(path: Path) -> date | None:
    match = ROLLOUT_RE.match(path.name)
    if not match:
        return None
    return date.fromisoformat(match.group("ts")[0:10])


def quick_rollout_info(path: Path, thread_names: dict[str, str]) -> QuickRollout:
    match = ROLLOUT_RE.match(path.name)
    if not match:
        raise ValueError(f"not a rollout file: {path}")

    thread_id = match.group("thread_id")
    session_meta: dict[str, Any] | None = None
    latest_turn_context: dict[str, Any] | None = None
    first_event_user_message: str | None = None
    first_response_user_message: str | None = None

    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            record_type = obj.get("type")
            payload = obj.get("payload")
            if record_type == "session_meta" and isinstance(payload, dict) and session_meta is None:
                session_meta = payload
            elif record_type == "turn_context" and isinstance(payload, dict):
                latest_turn_context = payload
            if first_event_user_message is None:
                first_event_user_message = extract_event_user_message(obj)
            if first_response_user_message is None:
                first_response_user_message = extract_response_item_user_message(obj)

    first_user_message = first_event_user_message or first_response_user_message

    cwd = string_or_none(
        latest_turn_context.get("cwd") if isinstance(latest_turn_context, dict) else None
    ) or string_or_none(
        session_meta.get("cwd") if isinstance(session_meta, dict) else None
    )
    thread_name = thread_names.get(thread_id)
    title = thread_name or first_user_message
    source = session_meta.get("source") if isinstance(session_meta, dict) else None
    thread_spawn = extract_thread_spawn(source)

    return QuickRollout(
        path=path,
        archived="archived_sessions" in path.parts,
        thread_id=thread_id,
        filename_timestamp=match.group("ts"),
        thread_name=thread_name,
        title=title,
        cwd=cwd,
        project=project_name_from_cwd(cwd),
        first_user_message=preview_text(first_user_message),
        model=string_or_none(
            latest_turn_context.get("model") if isinstance(latest_turn_context, dict) else None
        ),
        forked_from_id=string_or_none(
            session_meta.get("forked_from_id") if isinstance(session_meta, dict) else None
        ),
        parent_thread_id=string_or_none(thread_spawn.get("parent_thread_id") if thread_spawn else None),
        agent_nickname=string_or_none(
            session_meta.get("agent_nickname") if isinstance(session_meta, dict) else None
        ) or string_or_none(thread_spawn.get("agent_nickname") if thread_spawn else None),
        agent_role=string_or_none(
            session_meta.get("agent_role") if isinstance(session_meta, dict) else None
        ) or string_or_none(thread_spawn.get("agent_role") if thread_spawn else None),
        agent_path=string_or_none(
            session_meta.get("agent_path") if isinstance(session_meta, dict) else None
        ) or string_or_none(thread_spawn.get("agent_path") if thread_spawn else None),
    )


def resolve_target(
    paths: RolloutPaths,
    thread_names: dict[str, str],
    target: str | None,
    *,
    archived: bool,
    project: str | None,
    prefer_parent_on_default: bool = False,
) -> Path:
    if target is None:
        candidates = collect_quick_rollouts(
            paths,
            thread_names,
            archived=archived,
            since=None,
            project=project,
            include_subagents=not prefer_parent_on_default,
        )
        if not candidates:
            kind = "archived " if archived else ""
            project_suffix = f" for project filter `{project}`" if project else ""
            raise FileNotFoundError(f"no {kind}rollout files found{project_suffix}")
        return candidates[-1].path

    candidate_path = Path(target).expanduser()
    if candidate_path.exists():
        return candidate_path

    if not THREAD_ID_RE.match(target):
        raise FileNotFoundError(f"could not resolve rollout target: {target}")

    searched: list[QuickRollout] = collect_quick_rollouts(
        paths,
        thread_names,
        archived=archived,
        since=None,
        project=project,
        include_subagents=True,
    )
    if not archived:
        searched.extend(
            collect_quick_rollouts(
                paths,
                thread_names,
                archived=True,
                since=None,
                project=project,
                include_subagents=True,
            )
        )
    matches = [item for item in searched if item.thread_id == target]
    if not matches:
        raise FileNotFoundError(f"could not resolve rollout target: {target}")
    return matches[-1].path


def load_rollout(path: Path) -> LoadedRollout:
    records: list[dict[str, Any]] = []
    parse_errors = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            parse_errors += 1
    return LoadedRollout(path=path, records=records, parse_errors=parse_errors)


def summarize_rollout(
    loaded: LoadedRollout,
    paths: RolloutPaths,
    thread_names: dict[str, str],
    *,
    include_subagents: bool = True,
) -> dict[str, Any]:
    quick = quick_rollout_info(loaded.path, thread_names)
    record_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    response_item_counts: Counter[str] = Counter()
    model_counts: Counter[str] = Counter()
    session_meta_payload: dict[str, Any] | None = None
    latest_turn_context: dict[str, Any] | None = None

    for obj in loaded.records:
        record_type = string_or_none(obj.get("type")) or "unknown"
        record_counts[record_type] += 1
        payload = obj.get("payload")
        if record_type == "session_meta" and isinstance(payload, dict) and session_meta_payload is None:
            session_meta_payload = payload
        elif record_type == "turn_context" and isinstance(payload, dict):
            latest_turn_context = payload
            model = string_or_none(payload.get("model"))
            if model is not None:
                model_counts[model] += 1
        elif record_type == "event_msg" and isinstance(payload, dict):
            event_counts[string_or_none(payload.get("type")) or "unknown"] += 1
        elif record_type == "response_item" and isinstance(payload, dict):
            response_item_counts[string_or_none(payload.get("type")) or "unknown"] += 1

    raw_first_user_message = quick.first_user_message
    first_user_message = raw_first_user_message
    title = quick.title
    subagent_task = summarize_subagent_task(loaded, paths, thread_names, quick)
    if subagent_task is not None:
        first_user_message = subagent_task
        if quick.thread_name is None:
            title = subagent_task

    session_meta = None
    git = None
    if isinstance(session_meta_payload, dict):
        git_value = session_meta_payload.get("git")
        git = git_value if isinstance(git_value, dict) else None
        session_meta = {key: value for key, value in session_meta_payload.items() if key != "git"}

    tool_usage = summarize_tool_usage(loaded.records)
    child_rollouts = (
        [summarize_child_rollout(child.path, paths, thread_names) for child in list_child_rollouts(loaded.path, paths, thread_names)]
        if include_subagents
        else []
    )

    return {
        "path": str(loaded.path),
        "archived": quick.archived,
        "thread_id": quick.thread_id,
        "thread_name": quick.thread_name,
        "title": title,
        "filename_timestamp": quick.filename_timestamp,
        "cwd": quick.cwd,
        "project": quick.project,
        "is_subagent": quick.is_subagent,
        "first_user_message": first_user_message,
        "raw_first_user_message": raw_first_user_message,
        "delegated_task": subagent_task,
        "parse_errors": loaded.parse_errors,
        "record_count": len(loaded.records),
        "record_counts": dict(record_counts.most_common()),
        "event_counts": dict(event_counts.most_common()),
        "response_item_counts": dict(response_item_counts.most_common()),
        "model_usage": [{"model": model, "count": count} for model, count in model_counts.most_common()],
        "session_meta": session_meta,
        "git": git,
        "latest_turn_context": latest_turn_context,
        "token_usage": summarize_token_usage(loaded.records),
        "tool_usage": tool_usage,
        "tool_error_count": int_or_none(tool_usage.get("tool_error_count")) or 0,
        "tool_errors_by_name": tool_usage.get("tool_errors_by_name") or {},
        "turn_durations": summarize_turn_durations(loaded.records),
        "pr_links": extract_pr_links(loaded.records),
        "current_subagent": summarize_current_subagent(session_meta),
        "subagents": {
            "count": len(child_rollouts),
            "children": child_rollouts,
        }
        if include_subagents
        else None,
    }


def summarize_rollout_ingestion(
    loaded: LoadedRollout,
    paths: RolloutPaths,
    thread_names: dict[str, str],
    *,
    include_subagents: bool = True,
    kind: str = "session_summary",
) -> dict[str, Any]:
    summary = summarize_rollout(
        loaded,
        paths,
        thread_names,
        include_subagents=include_subagents,
    )
    return build_ingestion_summary(summary, paths, thread_names, kind=kind)


def summarize_child_rollout(
    path: Path,
    paths: RolloutPaths,
    thread_names: dict[str, str],
) -> dict[str, Any]:
    loaded = load_rollout(path)
    summary = summarize_rollout(
        loaded,
        paths,
        thread_names,
        include_subagents=False,
    )
    tool_usage = summary.get("tool_usage") or {}
    token_usage = summary.get("token_usage") or {}
    current_subagent = summary.get("current_subagent") or {}
    latest_turn_context = summary.get("latest_turn_context")
    return {
        "path": summary["path"],
        "archived": summary["archived"],
        "thread_id": summary["thread_id"],
        "thread_name": summary["thread_name"],
        "title": summary["title"],
        "project": summary["project"],
        "cwd": summary["cwd"],
        "model": latest_turn_context.get("model") if isinstance(latest_turn_context, dict) else None,
        "first_user_message": summary.get("first_user_message"),
        "raw_first_user_message": summary.get("raw_first_user_message"),
        "delegated_task": summary.get("delegated_task"),
        "token_total": token_usage.get("latest_total_token_usage", {}).get("total_tokens"),
        "tool_calls": tool_usage.get("all_calls"),
        "top_tools": tool_usage.get("top_tools"),
        "tool_error_count": summary.get("tool_error_count"),
        "tool_errors_by_name": summary.get("tool_errors_by_name"),
        "agent_nickname": current_subagent.get("agent_nickname"),
        "agent_role": current_subagent.get("agent_role"),
        "agent_path": current_subagent.get("agent_path"),
        "parent_thread_id": current_subagent.get("parent_thread_id"),
    }


def build_ingestion_summary(
    summary: dict[str, Any],
    paths: RolloutPaths,
    thread_names: dict[str, str],
    *,
    kind: str,
) -> dict[str, Any]:
    session_meta = summary.get("session_meta")
    session_meta = session_meta if isinstance(session_meta, dict) else {}
    latest_turn_context = summary.get("latest_turn_context")
    latest_turn_context = latest_turn_context if isinstance(latest_turn_context, dict) else {}
    git = summary.get("git")
    git = git if isinstance(git, dict) else {}
    current_subagent = summary.get("current_subagent")
    current_subagent = current_subagent if isinstance(current_subagent, dict) else {}
    token_usage = summary.get("token_usage")
    token_usage = token_usage if isinstance(token_usage, dict) else {}
    turn_durations = summary.get("turn_durations")
    turn_durations = turn_durations if isinstance(turn_durations, dict) else {}
    pr_links = summary.get("pr_links")
    pr_links = pr_links if isinstance(pr_links, list) else []
    subagents = summary.get("subagents")
    child_rollouts = []
    if isinstance(subagents, dict):
        children = subagents.get("children")
        if isinstance(children, list):
            child_rollouts = children

    timestamp = string_or_none(session_meta.get("timestamp")) or filename_timestamp_to_iso(
        string_or_none(summary.get("filename_timestamp"))
    )
    model_entries = normalize_model_entries(summary.get("model_usage"))
    if not model_entries:
        model = string_or_none(latest_turn_context.get("model"))
        if model is not None:
            model_entries = [{"model": model, "count": 1}]

    tool_entries = ingestion_tool_entries(summary.get("tool_usage"))

    child_entries = []
    for child in child_rollouts:
        if not isinstance(child, dict):
            continue
        child_entries.append(
            {
                "id": child.get("thread_id"),
                "path": child.get("path"),
                "title": child.get("title"),
                "display_name": child.get("thread_name") or child.get("title"),
                "project": child.get("project"),
                "cwd": child.get("cwd"),
                "model": child.get("model"),
                "token_total": child.get("token_total"),
                "tool_error_count": child.get("tool_error_count"),
                "agent": {
                    "nickname": child.get("agent_nickname"),
                    "role": child.get("agent_role"),
                    "path": child.get("agent_path"),
                },
                "parent_session_id": child.get("parent_thread_id"),
            }
        )

    return {
        "schema_version": "session_inspector_v2",
        "source": "codex_cli",
        "kind": kind,
        "session": {
            "id": summary.get("thread_id"),
            "path": summary.get("path"),
            "project": summary.get("project"),
            "cwd": summary.get("cwd"),
            "timestamp": timestamp,
            "title": summary.get("title"),
            "display_name": summary.get("thread_name") or summary.get("title"),
            "archived": summary.get("archived"),
            "version": session_meta.get("cli_version"),
            "model_provider": session_meta.get("model_provider"),
            "model": latest_turn_context.get("model"),
            "git_branch": git.get("branch"),
            "git_commit": git.get("commit_hash"),
            "session_origin": session_origin_value(session_meta.get("source")),
            "is_subagent": summary.get("is_subagent"),
            "parent_session_id": current_subagent.get("parent_thread_id")
            or current_subagent.get("forked_from_id"),
            "forked_from_session_id": current_subagent.get("forked_from_id"),
            "agent": {
                "nickname": current_subagent.get("agent_nickname"),
                "role": current_subagent.get("agent_role"),
                "path": current_subagent.get("agent_path"),
                "depth": current_subagent.get("depth"),
            }
            if current_subagent
            else None,
        },
        "content": {
            "first_user_message": summary.get("first_user_message"),
            "raw_first_user_message": summary.get("raw_first_user_message"),
            "delegated_task": summary.get("delegated_task"),
        },
        "counts": {
            "records": summary.get("record_count"),
            "parse_errors": summary.get("parse_errors"),
            "tool_error_count": summary.get("tool_error_count"),
            "by_record_type": counter_dict_to_rows(summary.get("record_counts"), key_name="type"),
            "by_event_type": counter_dict_to_rows(summary.get("event_counts"), key_name="type"),
            "by_item_type": counter_dict_to_rows(summary.get("response_item_counts"), key_name="type"),
        },
        "usage": {
            "models": model_entries,
            "tokens": {
                "mode": "cumulative_snapshot",
                "input": nested_int(token_usage, "latest_total_token_usage", "input_tokens"),
                "output": nested_int(token_usage, "latest_total_token_usage", "output_tokens"),
                "cache_create": None,
                "cache_read": nested_int(token_usage, "latest_total_token_usage", "cached_input_tokens"),
                "reasoning_output": nested_int(
                    token_usage,
                    "latest_total_token_usage",
                    "reasoning_output_tokens",
                ),
                "total": nested_int(token_usage, "latest_total_token_usage", "total_tokens"),
                "api_calls_exact": None,
                "api_calls_approx": token_usage.get("api_call_count_approx"),
                "note": token_usage.get("deduplication_note"),
            },
            "tools": tool_entries,
        },
        "turns": {
            "completed": turn_durations.get("completed_count"),
            "incomplete": turn_durations.get("incomplete_count"),
            "total_duration_ms": turn_durations.get("total_duration_ms"),
            "durations": turn_durations.get("turns"),
        },
        "links": {
            "prs": [parse_github_pr(link) for link in pr_links],
        },
        "subagents": child_entries,
    }


def ingestion_stub_from_quick(item: QuickRollout) -> dict[str, Any]:
    return {
        "schema_version": "session_inspector_v2",
        "source": "codex_cli",
        "kind": "session_stub",
        "session": {
            "id": item.thread_id,
            "path": str(item.path),
            "project": item.project,
            "cwd": item.cwd,
            "timestamp": filename_timestamp_to_iso(item.filename_timestamp),
            "title": item.title,
            "display_name": item.thread_name or item.title,
            "archived": item.archived,
            "version": None,
            "model_provider": None,
            "model": item.model,
            "git_branch": None,
            "git_commit": None,
            "session_origin": None,
            "is_subagent": item.is_subagent,
            "parent_session_id": item.parent_thread_id or item.forked_from_id,
            "forked_from_session_id": item.forked_from_id,
            "agent": {
                "nickname": item.agent_nickname,
                "role": item.agent_role,
                "path": item.agent_path,
                "depth": None,
            }
            if item.is_subagent
            else None,
        },
        "content": {
            "first_user_message": item.first_user_message,
            "raw_first_user_message": item.first_user_message,
            "delegated_task": None,
        },
    }


def summarize_current_subagent(session_meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(session_meta, dict):
        return None
    source = session_meta.get("source")
    thread_spawn = extract_thread_spawn(source)
    if thread_spawn is None and not any(
        session_meta.get(key) for key in ("agent_nickname", "agent_role", "agent_path", "forked_from_id")
    ):
        return None
    return {
        "forked_from_id": string_or_none(session_meta.get("forked_from_id")),
        "parent_thread_id": string_or_none(thread_spawn.get("parent_thread_id") if thread_spawn else None),
        "depth": thread_spawn.get("depth") if thread_spawn else None,
        "agent_nickname": string_or_none(session_meta.get("agent_nickname"))
        or string_or_none(thread_spawn.get("agent_nickname") if thread_spawn else None),
        "agent_role": string_or_none(session_meta.get("agent_role"))
        or string_or_none(thread_spawn.get("agent_role") if thread_spawn else None),
        "agent_path": string_or_none(session_meta.get("agent_path"))
        or string_or_none(thread_spawn.get("agent_path") if thread_spawn else None),
        "source": source,
    }


def summarize_token_usage(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    snapshot_count = 0
    snapshot_count_with_usage = 0
    api_call_count_approx = 0
    latest_total_token_usage: dict[str, Any] | None = None
    latest_last_token_usage: dict[str, Any] | None = None
    latest_rate_limits: dict[str, Any] | None = None
    latest_model_context_window: int | None = None
    previous_signature: tuple[int | None, int | None, int | None, int | None, int | None] | None = None

    for obj in records:
        if obj.get("type") != "event_msg":
            continue
        payload = obj.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        snapshot_count += 1
        rate_limits = payload.get("rate_limits")
        if isinstance(rate_limits, dict):
            latest_rate_limits = rate_limits
        info = payload.get("info")
        if not isinstance(info, dict):
            continue
        total_token_usage = info.get("total_token_usage")
        last_token_usage = info.get("last_token_usage")
        if not isinstance(total_token_usage, dict):
            continue
        snapshot_count_with_usage += 1
        latest_total_token_usage = total_token_usage
        latest_last_token_usage = last_token_usage if isinstance(last_token_usage, dict) else None
        latest_model_context_window = int_or_none(info.get("model_context_window"))
        signature = (
            int_or_none(total_token_usage.get("input_tokens")),
            int_or_none(total_token_usage.get("cached_input_tokens")),
            int_or_none(total_token_usage.get("output_tokens")),
            int_or_none(total_token_usage.get("reasoning_output_tokens")),
            int_or_none(total_token_usage.get("total_tokens")),
        )
        if signature != previous_signature:
            api_call_count_approx += 1
            previous_signature = signature

    return {
        "snapshot_count": snapshot_count,
        "snapshot_count_with_usage": snapshot_count_with_usage,
        "api_call_count_approx": api_call_count_approx,
        "deduplication_note": (
            "Codex rollouts do not expose requestId. This approximation counts changed cumulative token snapshots."
        ),
        "latest_total_token_usage": latest_total_token_usage,
        "latest_last_token_usage": latest_last_token_usage,
        "latest_model_context_window": latest_model_context_window,
        "latest_rate_limits": latest_rate_limits,
    }


def summarize_tool_usage(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    function_calls: Counter[str] = Counter()
    custom_tool_calls: Counter[str] = Counter()
    native_calls: Counter[str] = Counter()
    call_types: Counter[str] = Counter()
    tool_errors_by_name: Counter[str] = Counter()
    pending_calls: dict[str, str] = {}
    calls_with_output = 0
    successful_output_count = 0
    error_output_count = 0
    unknown_output_status_count = 0
    unmatched_output_count = 0

    for obj in records:
        if obj.get("type") != "response_item":
            continue
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue
        payload_type = string_or_none(payload.get("type")) or "unknown"
        if payload_type == FUNCTION_CALL_TYPE:
            name = tool_name_from_payload(payload)
            function_calls[name] += 1
            call_types[payload_type] += 1
            call_id = string_or_none(payload.get("call_id"))
            if call_id is not None:
                pending_calls[call_id] = name
        elif payload_type == CUSTOM_TOOL_CALL_TYPE:
            name = tool_name_from_payload(payload)
            custom_tool_calls[name] += 1
            call_types[payload_type] += 1
            call_id = string_or_none(payload.get("call_id"))
            if call_id is not None:
                pending_calls[call_id] = name
        elif payload_type == TOOL_SEARCH_CALL_TYPE:
            name = tool_name_from_payload(payload)
            native_calls[name] += 1
            call_types[payload_type] += 1
            call_id = string_or_none(payload.get("call_id"))
            if call_id is not None:
                pending_calls[call_id] = name
        elif payload_type in DIRECT_STATUS_TOOL_CALL_TYPES:
            name = tool_name_from_payload(payload)
            native_calls[name] += 1
            call_types[payload_type] += 1
            status = string_or_none(payload.get("status"))
            if is_error_status(status):
                tool_errors_by_name[name] += 1
        elif payload_type in {FUNCTION_CALL_OUTPUT_TYPE, CUSTOM_TOOL_CALL_OUTPUT_TYPE, TOOL_SEARCH_OUTPUT_TYPE}:
            call_id = string_or_none(payload.get("call_id"))
            name = pending_calls.pop(call_id, None) if call_id is not None else None
            if name is None:
                name = tool_name_from_payload(payload)
                unmatched_output_count += 1
            else:
                calls_with_output += 1
            if payload_type == TOOL_SEARCH_OUTPUT_TYPE:
                success = status_to_success_flag(string_or_none(payload.get("status")))
            else:
                _, success = call_output_content_and_success(payload.get("output"))
            if success is True:
                successful_output_count += 1
            elif success is False:
                error_output_count += 1
                tool_errors_by_name[name] += 1
            else:
                unknown_output_status_count += 1

    combined = function_calls + custom_tool_calls + native_calls
    return {
        "function_calls": dict(function_calls.most_common()),
        "custom_tool_calls": dict(custom_tool_calls.most_common()),
        "native_calls": dict(native_calls.most_common()),
        "all_calls": dict(combined.most_common()),
        "top_tools": [
            {"name": name, "count": count}
            for name, count in combined.most_common(10)
        ],
        "call_type_counts": dict(call_types.most_common()),
        "tool_error_count": sum(tool_errors_by_name.values()),
        "tool_errors_by_name": dict(tool_errors_by_name.most_common()),
        "calls_with_output": calls_with_output,
        "calls_without_output": len(pending_calls),
        "successful_output_count": successful_output_count,
        "error_output_count": error_output_count,
        "unknown_output_status_count": unknown_output_status_count,
        "unmatched_output_count": unmatched_output_count,
    }


def summarize_model_usage_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    models: Counter[str] = Counter()
    for obj in records:
        if obj.get("type") != "turn_context":
            continue
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue
        model = string_or_none(payload.get("model"))
        if model is not None:
            models[model] += 1
    return [{"model": model, "count": count} for model, count in models.most_common()]


def summarize_turn_durations(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    started_at: dict[str, datetime] = {}
    completed_turns: list[dict[str, Any]] = []

    for obj in records:
        if obj.get("type") != "event_msg":
            continue
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue
        event_type = payload.get("type")
        turn_id = string_or_none(payload.get("turn_id"))
        if turn_id is None:
            continue
        timestamp = parse_iso_timestamp(string_or_none(obj.get("timestamp")))
        if timestamp is None:
            continue
        if event_type == "task_started":
            started_at[turn_id] = timestamp
        elif event_type == "task_complete":
            started = started_at.get(turn_id)
            duration_ms = (
                int((timestamp - started).total_seconds() * 1000) if started is not None else None
            )
            completed_turns.append(
                {
                    "turn_id": turn_id,
                    "started_at": started.isoformat() if started is not None else None,
                    "completed_at": timestamp.isoformat(),
                    "duration_ms": duration_ms,
                    "duration_seconds": round(duration_ms / 1000, 3) if duration_ms is not None else None,
                }
            )

    completed_ids = {turn["turn_id"] for turn in completed_turns}
    incomplete_turns = [
        {
            "turn_id": turn_id,
            "started_at": timestamp.isoformat(),
        }
        for turn_id, timestamp in started_at.items()
        if turn_id not in completed_ids
    ]
    total_duration_ms = sum(
        turn["duration_ms"] for turn in completed_turns if isinstance(turn.get("duration_ms"), int)
    )
    return {
        "completed_count": len(completed_turns),
        "incomplete_count": len(incomplete_turns),
        "total_duration_ms": total_duration_ms,
        "total_duration_seconds": round(total_duration_ms / 1000, 3),
        "turns": completed_turns,
        "incomplete_turns": incomplete_turns,
    }


def list_child_rollouts(
    parent_path: Path,
    paths: RolloutPaths,
    thread_names: dict[str, str],
) -> list[QuickRollout]:
    cache = get_quick_rollout_cache(paths, thread_names)
    parent = cache.get_quick_info(parent_path)
    return cache.children_for_parent(parent.thread_id)


def extract_pr_links(records: Iterable[dict[str, Any]]) -> list[str]:
    links: set[str] = set()
    for obj in records:
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue
        for text in walk_strings(payload):
            for match in GITHUB_PR_RE.findall(text):
                links.add(match)
    return sorted(links)


def filter_records(
    records: Iterable[dict[str, Any]],
    *,
    record_type: str | None,
    payload_type: str | None,
    tool_name: str | None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for obj in records:
        if record_type is not None and obj.get("type") != record_type:
            continue
        payload = obj.get("payload")
        if payload_type is not None:
            if not isinstance(payload, dict) or payload.get("type") != payload_type:
                continue
        if tool_name is not None:
            if not isinstance(payload, dict):
                continue
            item_payload_type = string_or_none(payload.get("type"))
            if item_payload_type not in ALL_TOOL_CALL_TYPES:
                continue
            if tool_name_from_payload(payload) != tool_name:
                continue
        matches.append(obj)
    return matches


def extract_user_message(obj: dict[str, Any]) -> str | None:
    return extract_event_user_message(obj) or extract_response_item_user_message(obj)


def extract_event_user_message(obj: dict[str, Any]) -> str | None:
    record_type = obj.get("type")
    payload = obj.get("payload")
    if record_type == "event_msg" and isinstance(payload, dict) and payload.get("type") == "user_message":
        return string_or_none(payload.get("message"))
    return None


def extract_response_item_user_message(obj: dict[str, Any]) -> str | None:
    record_type = obj.get("type")
    payload = obj.get("payload")
    if record_type == "response_item" and isinstance(payload, dict):
        return extract_user_message_from_response_item(payload)
    return None


def extract_event_user_messages(records: Iterable[dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for obj in records:
        message = extract_event_user_message(obj)
        if message is not None:
            messages.append(message)
    return messages


def extract_user_message_metrics(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract per-user-prompt metrics from event_msg records."""
    metrics: list[dict[str, Any]] = []
    current_turn_index = 0
    open_turns: dict[str, int] = {}

    for obj in records:
        record_type = obj.get("type")
        if record_type == "turn_context":
            current_turn_index += 1
            continue
        if record_type != "event_msg":
            continue

        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue

        event_type = payload.get("type")
        if event_type == "task_started":
            turn_id = string_or_none(payload.get("turn_id"))
            if turn_id is not None:
                open_turns[turn_id] = max(current_turn_index, 1)
            continue
        if event_type == "task_complete":
            turn_id = string_or_none(payload.get("turn_id"))
            if turn_id is not None:
                open_turns.pop(turn_id, None)
            continue
        if event_type != "user_message":
            continue

        raw_message = string_or_none(payload.get("message"))
        if raw_message is None:
            continue
        normalized = " ".join(raw_message.split())
        preceding_turn_index = max(open_turns.values()) if open_turns else (current_turn_index or None)
        metrics.append(
            {
                "message_index": len(metrics) + 1,
                "timestamp": string_or_none(obj.get("timestamp")),
                "is_first": len(metrics) == 0,
                "is_interrupt": bool(open_turns),
                "word_count": len(normalized.split()) if normalized else 0,
                "char_count": len(normalized),
                "preceding_turn_index": preceding_turn_index,
            }
        )
    return metrics


def extract_reasoning_block_metrics(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract per-turn reasoning item metrics from response_item records."""
    metrics: list[dict[str, Any]] = []
    current_turn_index = 0
    per_turn_block_index: dict[int, int] = {}

    for obj in records:
        record_type = obj.get("type")
        if record_type == "turn_context":
            current_turn_index += 1
            continue
        if record_type != "response_item":
            continue

        payload = obj.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "reasoning":
            continue

        plaintext_content = _reasoning_content_text(payload.get("content"))
        encrypted_content = string_or_none(payload.get("encrypted_content"))
        summary = payload.get("summary")
        turn_index = max(current_turn_index, 1)
        per_turn_block_index[turn_index] = per_turn_block_index.get(turn_index, 0) + 1

        plaintext_length = len(plaintext_content) if plaintext_content is not None else 0
        encrypted_length = len(encrypted_content) if encrypted_content is not None else 0
        metrics.append(
            {
                "turn_index": turn_index,
                "block_index": per_turn_block_index[turn_index],
                "block_type": "reasoning",
                "is_redacted": 0 if plaintext_length > 0 else 1,
                "content_length": plaintext_length if plaintext_length > 0 else encrypted_length,
                "encrypted_content_length": encrypted_length,
                "summary_item_count": len(summary) if isinstance(summary, list) else 0,
                "has_plaintext_content": 1 if plaintext_length > 0 else 0,
            }
        )

    return metrics


def summarize_subagent_task(
    loaded: LoadedRollout,
    paths: RolloutPaths,
    thread_names: dict[str, str],
    quick: QuickRollout,
) -> str | None:
    if not quick.is_subagent:
        return None
    child_messages = extract_event_user_messages(loaded.records)
    if not child_messages:
        return None

    parent_thread_id = quick.parent_thread_id or quick.forked_from_id
    if parent_thread_id is not None:
        try:
            parent_path = resolve_target(
                paths,
                thread_names,
                parent_thread_id,
                archived=False,
                project=None,
            )
        except FileNotFoundError:
            parent_path = None
        if parent_path is not None:
            parent_messages = extract_event_user_messages(load_rollout(parent_path).records)
            shared_prefix = shared_prefix_len(parent_messages, child_messages)
            if shared_prefix < len(child_messages):
                return preview_text(child_messages[shared_prefix])

    return preview_text(child_messages[-1])


def shared_prefix_len(left: Sequence[str], right: Sequence[str]) -> int:
    index = 0
    for left_item, right_item in zip(left, right):
        if left_item != right_item:
            break
        index += 1
    return index


def extract_user_message_from_response_item(payload: dict[str, Any]) -> str | None:
    if payload.get("type") != "message" or payload.get("role") != "user":
        return None
    content = payload.get("content")
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = string_or_none(item.get("text"))
        if text is not None and text.strip():
            parts.append(text.strip())
    joined = "\n".join(parts).strip()
    return joined or None


def _reasoning_content_text(content: Any) -> str | None:
    if isinstance(content, str):
        normalized = " ".join(content.split())
        return normalized or None
    if isinstance(content, list):
        parts = [
            normalized
            for normalized in (
                " ".join(item.split()) if isinstance(item, str) else None
                for item in walk_strings(content)
            )
            if normalized
        ]
        if parts:
            return " ".join(parts)
    if isinstance(content, dict):
        parts = [
            normalized
            for normalized in (
                " ".join(item.split()) if isinstance(item, str) else None
                for item in walk_strings(content)
            )
            if normalized
        ]
        if parts:
            return " ".join(parts)
    return None


def tool_name_from_payload(payload: dict[str, Any]) -> str:
    payload_type = string_or_none(payload.get("type"))
    if payload_type in {FUNCTION_CALL_TYPE, CUSTOM_TOOL_CALL_TYPE}:
        return string_or_none(payload.get("name")) or "unknown"
    if payload_type == TOOL_SEARCH_OUTPUT_TYPE:
        return TOOL_SEARCH_CALL_TYPE
    if payload_type in NATIVE_TOOL_CALL_TYPES:
        return payload_type
    return string_or_none(payload.get("name")) or payload_type or "unknown"


def call_output_content_and_success(output: Any) -> tuple[str | None, bool | None]:
    if isinstance(output, str):
        text = " ".join(output.split())
        return text or None, None

    if isinstance(output, list):
        if len(output) != 1:
            return None, None
        item = output[0]
        if not isinstance(item, dict) or item.get("type") != "input_text":
            return None, None
        text = string_or_none(item.get("text"))
        if text is None:
            return None, None
        normalized = " ".join(text.split())
        return normalized or None, None

    if not isinstance(output, dict):
        return None, None

    text = string_or_none(output.get("content"))
    normalized = " ".join(text.split()) if text else None
    success = output.get("success")
    return normalized or None, success if isinstance(success, bool) else None


def is_error_status(status: str | None) -> bool:
    if status is None:
        return False
    normalized = status.strip().lower()
    return normalized in {
        "aborted",
        "canceled",
        "cancelled",
        "denied",
        "error",
        "failed",
        "failure",
        "incomplete",
        "interrupted",
        "timed_out",
        "timeout",
    }


def is_success_status(status: str | None) -> bool:
    if status is None:
        return False
    normalized = status.strip().lower()
    return normalized in {"complete", "completed", "ok", "success", "succeeded"}


def status_to_success_flag(status: str | None) -> bool | None:
    if is_success_status(status):
        return True
    if is_error_status(status):
        return False
    return None


def walk_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from walk_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from walk_strings(item)


def extract_thread_spawn(source: Any) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    subagent = source.get("subagent")
    if not isinstance(subagent, dict):
        return None
    thread_spawn = subagent.get("thread_spawn")
    return thread_spawn if isinstance(thread_spawn, dict) else None


def project_name_from_cwd(cwd: str | None) -> str | None:
    if cwd is None:
        return None
    return Path(cwd).name


def matches_project(item: QuickRollout, project: str) -> bool:
    needle = project.lower()
    haystacks = [
        item.cwd or "",
        item.project or "",
    ]
    return any(needle in haystack.lower() for haystack in haystacks)


def matches_agent_filter(item: QuickRollout, agent: str) -> bool:
    needle = agent.lower()
    values = [
        item.thread_id,
        item.thread_name or "",
        item.agent_nickname or "",
        item.agent_role or "",
        item.agent_path or "",
    ]
    return any(needle in value.lower() for value in values)


def parse_iso_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        timestamp = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)


def string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def nested_int(container: dict[str, Any], key: str, nested_key: str) -> int | None:
    value = container.get(key)
    if not isinstance(value, dict):
        return None
    return int_or_none(value.get(nested_key))


def counter_dict_to_rows(counter_dict: Any, *, key_name: str) -> list[dict[str, Any]]:
    if not isinstance(counter_dict, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key, value in counter_dict.items():
        if not isinstance(key, str) or not isinstance(value, int):
            continue
        rows.append({key_name: key, "count": value})
    return rows


def normalize_model_entries(value: Any) -> list[dict[str, int | str]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, int | str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        model = string_or_none(item.get("model"))
        count = int_or_none(item.get("count"))
        if model is None or count is None:
            continue
        entries.append({"model": model, "count": count})
    return entries


def ingestion_tool_entries(tool_usage: Any) -> list[dict[str, Any]]:
    if not isinstance(tool_usage, dict):
        return []
    entries: list[dict[str, Any]] = []
    for kind, key in (
        (FUNCTION_CALL_TYPE, "function_calls"),
        (CUSTOM_TOOL_CALL_TYPE, "custom_tool_calls"),
        ("native_call", "native_calls"),
    ):
        mapping = tool_usage.get(key)
        if not isinstance(mapping, dict):
            continue
        error_mapping = tool_usage.get("tool_errors_by_name")
        error_mapping = error_mapping if isinstance(error_mapping, dict) else {}
        for name, count in mapping.items():
            if isinstance(name, str) and isinstance(count, int):
                errors = error_mapping.get(name, 0)
                errors = errors if isinstance(errors, int) else 0
                entry_kind = name if kind == "native_call" and name in NATIVE_TOOL_CALL_TYPES else kind
                entries.append({"name": name, "count": count, "errors": errors, "kind": entry_kind})
    entries.sort(key=lambda item: (-item["count"], item["name"]))
    return entries


def session_origin_value(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "subagent" in value:
            return "subagent"
        return json.dumps(value, sort_keys=True)
    return None


def filename_timestamp_to_iso(value: str | None) -> str | None:
    if value is None:
        return None
    if "T" not in value:
        return value
    date_part, time_part = value.split("T", 1)
    return f"{date_part}T{time_part.replace('-', ':')}Z"


def parse_github_pr(url: Any) -> dict[str, Any]:
    if not isinstance(url, str):
        return {"url": None, "number": None, "repository": None}
    match = re.match(r"^https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)$", url)
    if not match:
        return {"url": url, "number": None, "repository": None}
    return {
        "url": url,
        "number": int(match.group(2)),
        "repository": match.group(1),
    }


def preview_text(value: str | None, *, limit: int = 240) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def emit(as_json: bool, payload: Any) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return
    match payload:
        case dict():
            for key, value in payload.items():
                print(
                    f"{key}: {json.dumps(value, default=str) if isinstance(value, (dict, list)) else value}"
                )
        case list():
            for item in payload:
                print(json.dumps(item, default=str))
        case _:
            print(payload)


if __name__ == "__main__":
    sys.exit(main())
