#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///
"""Locate and inspect Cursor sessions under ~/.cursor and Cursor Application Support."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
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
UI = _load_module("cursor_session_inspector_ui_store_reader", "ui_store_reader.py")
CLI = _load_module("cursor_session_inspector_cli_blob_walker", "cli_blob_walker.py")
TRANSCRIPTS = _load_module("cursor_session_inspector_transcript_reader", "transcript_reader.py")
AI = _load_module("cursor_session_inspector_ai_tracking", "ai_tracking.py")


@dataclass(slots=True, frozen=True)
class CursorPaths:
    cursor_profile: str | None
    cursor_home: Path
    cursor_app_support: Path
    ui_store_path: Path
    cli_chats_dir: Path
    transcripts_root: Path
    ai_tracking_db_path: Path
    db_path: Path
    hook_config_path_user: Path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Locate and inspect Cursor sessions.",
        suggest_on_error=True,
    )
    parser.add_argument(
        "--cursor-home",
        type=Path,
        default=None,
        help="Override Cursor home. Defaults to $CURSOR_HOME or ~/.cursor.",
    )
    parser.add_argument(
        "--cursor-app-support",
        type=Path,
        default=None,
        help="Override Cursor Application Support root. Defaults to $CURSOR_APP_SUPPORT or ~/Library/Application Support/Cursor.",
    )
    parser.add_argument(
        "--cursor-profile",
        choices=sorted(CURSOR_PROFILES),
        default=None,
        help="Resolve split Cursor paths for a known local profile. Defaults to $CURSOR_PROFILE, then repo-root inference.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of plain text.")
    parser.add_argument(
        "--profile",
        choices=("default", "ingestion"),
        default="default",
        help="Output profile. `ingestion` emits a normalized machine-oriented shape.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("locate", help="Print key Cursor data locations.")

    list_parser = subparsers.add_parser("list", help="List cached Cursor sessions.")
    list_parser.add_argument("--since", type=parse_since_date, default=None)
    list_parser.add_argument("--workspace", default=None)
    list_parser.add_argument("--project", default=None)
    list_parser.add_argument(
        "--source-type",
        choices=("ui_composer", "cli_agent", "transcript_only"),
        default=None,
    )
    list_parser.add_argument("--limit", type=int, default=20)

    summary_parser = subparsers.add_parser("summary", help="Summarize a Cursor session.")
    summary_parser.add_argument("target", nargs="?")

    records_parser = subparsers.add_parser("records", help="Print raw matching Cursor records.")
    records_parser.add_argument("target", nargs="?")
    records_parser.add_argument(
        "--record-type",
        choices=("composer", "bubble", "tool_result", "thinking_block", "cli_message", "transcript"),
        default=None,
    )
    records_parser.add_argument("--tool-name", default=None)
    records_parser.add_argument("--tail", type=int, default=20)

    subagents_parser = subparsers.add_parser("subagents", help="List subagents for a parent session.")
    subagents_parser.add_argument("target", nargs="?")
    subagents_parser.add_argument("--agent", default=None)

    refresh_parser = subparsers.add_parser("refresh", help="Incrementally import Cursor data into SQLite.")
    refresh_parser.add_argument("target", nargs="?")
    refresh_parser.add_argument("--project", default=None)
    refresh_parser.add_argument("--since", type=parse_since_date, default=None)
    refresh_parser.add_argument("--pending", action="store_true")

    rebuild_parser = subparsers.add_parser("rebuild", help="Delete and rebuild the SQLite cache.")
    rebuild_parser.add_argument("--project", default=None)
    rebuild_parser.add_argument("--since", type=parse_since_date, default=None)

    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    paths = resolve_paths(args.cursor_home, args.cursor_app_support, args.cursor_profile)
    match args.command:
        case "locate":
            emit(args.json, locate_payload(paths))
        case "refresh":
            if args.pending:
                reconciled = IMPORTER.reconcile_pending(
                    paths.cursor_home,
                    app_support=paths.cursor_app_support,
                )
                payload = {
                    "reconciled_pending": reconciled,
                    "reconciled_pending_count": len(reconciled),
                    "pending_markers": DB.pending_marker_stats(paths.db_path),
                    "db_path": str(paths.db_path),
                }
            else:
                payload = IMPORTER.refresh_sessions(
                    paths.cursor_home,
                    app_support=paths.cursor_app_support,
                    target=args.target,
                    project=args.project,
                    since=args.since,
                )
            emit(args.json, payload)
        case "rebuild":
            payload = IMPORTER.rebuild_sessions(
                paths.cursor_home,
                app_support=paths.cursor_app_support,
                project=args.project,
                since=args.since,
            )
            emit(args.json, payload)
        case "list":
            _ensure_cache_for_read(paths)
            payload = IMPORTER.list_payload(
                paths.cursor_home,
                source_type=args.source_type,
                workspace=args.workspace,
                project=args.project,
                since=args.since,
                limit=args.limit,
                profile=args.profile,
            )
            emit(args.json, payload)
        case "summary":
            _ensure_cache_for_read(paths, target=args.target)
            payload = IMPORTER.summary_payload(paths.cursor_home, args.target, profile=args.profile)
            if payload is None:
                raise ValueError(f"could not resolve Cursor session target: {args.target}")
            emit(args.json, payload)
        case "records":
            payload = records_payload(
                paths,
                target=args.target,
                record_type=args.record_type,
                tool_name=args.tool_name,
                tail=args.tail,
            )
            emit(args.json, payload)
        case "subagents":
            _ensure_cache_for_read(paths, target=args.target)
            payload = IMPORTER.subagents_payload(
                paths.cursor_home,
                args.target,
                profile=args.profile,
                agent=args.agent,
            )
            if payload is None:
                raise ValueError(f"could not resolve Cursor session target: {args.target}")
            emit(args.json, payload)
        case _:
            raise ValueError(f"unsupported command: {args.command}")
    return 0


def resolve_paths(
    cursor_home_override: Path | None,
    app_support_override: Path | None,
    cursor_profile_override: str | None = None,
) -> CursorPaths:
    cursor_home_env = os.environ.get("CURSOR_HOME")
    app_support_env = os.environ.get("CURSOR_APP_SUPPORT")
    cursor_profile = resolve_cursor_profile(
        cursor_profile_override,
        infer_from_cwd=not any(
            (cursor_home_override, app_support_override, cursor_home_env, app_support_env)
        ),
    )
    profile_home: Path | None = None
    profile_app_support: Path | None = None
    if cursor_profile is not None:
        profile_home, profile_app_support = cursor_profile_paths(cursor_profile)

    cursor_home = (
        cursor_home_override
        or (Path(cursor_home_env) if cursor_home_env else None)
        or profile_home
        or Path.home() / ".cursor"
    ).expanduser()
    app_support = (
        app_support_override
        or (Path(app_support_env) if app_support_env else None)
        or profile_app_support
        or IMPORTER.default_app_support_path()
    ).expanduser()
    return CursorPaths(
        cursor_profile=cursor_profile,
        cursor_home=cursor_home,
        cursor_app_support=app_support,
        ui_store_path=app_support / "User" / "globalStorage" / "state.vscdb",
        cli_chats_dir=cursor_home / "chats",
        transcripts_root=cursor_home / "projects",
        ai_tracking_db_path=cursor_home / "ai-tracking" / "ai-code-tracking.db",
        db_path=IMPORTER.resolve_db_path(cursor_home),
        hook_config_path_user=cursor_home / "hooks.json",
    )


def resolve_cursor_profile(
    cursor_profile_override: str | None = None,
    *,
    infer_from_cwd: bool = True,
) -> str | None:
    profile = cursor_profile_override or os.environ.get("CURSOR_PROFILE")
    if profile:
        return validate_cursor_profile(profile)
    profile = infer_cursor_profile_from_env_paths()
    if profile is not None:
        return profile
    return infer_cursor_profile(Path.cwd()) if infer_from_cwd else None


def infer_cursor_profile_from_env_paths() -> str | None:
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
    return None


def cursor_profile_paths(profile: str) -> tuple[Path, Path]:
    profile = validate_cursor_profile(profile)
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


def validate_cursor_profile(profile: str) -> str:
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


def parse_since_date(value: str) -> date:
    return date.fromisoformat(value)


def locate_payload(paths: CursorPaths) -> dict[str, Any]:
    db_info = DB.database_stats(paths.db_path)
    pending_stats = DB.pending_marker_stats(paths.db_path)
    hook_status = hook_config_status(paths.hook_config_path_user)
    return {
        "cursor_profile": paths.cursor_profile,
        "cursor_app_support": str(paths.cursor_app_support),
        "cursor_home": str(paths.cursor_home),
        "ui_store_path": str(paths.ui_store_path),
        "cli_chats_dir": str(paths.cli_chats_dir),
        "transcripts_root": str(paths.transcripts_root),
        "ai_tracking_db_path": str(paths.ai_tracking_db_path),
        "db_path": str(paths.db_path),
        "db_exists": db_info["exists"],
        "db_session_count": db_info["session_count"],
        "db_subagent_count": db_info["subagent_count"],
        "db_last_import_at": db_info["last_import_at"],
        "hook_config_path_user": str(paths.hook_config_path_user),
        "hook_configured": hook_status["configured"],
        "hook_config": hook_status,
        "hook_runtime_env_present": bool(os.environ.get("CURSOR_SESSION_ID") or os.environ.get("CURSOR_WORKSPACE_ID")),
        "recommended_hook_command": recommended_hook_command(),
        "hook_create_file_snippet": hook_create_file_snippet(paths.hook_config_path_user),
        "hook_merge_jq_command": hook_merge_jq_command(paths.hook_config_path_user),
        "pending_dir": str(DB.pending_dir(paths.db_path)),
        "pending_markers": pending_stats,
        "workspace_count": workspace_count(paths.cursor_home),
        "ui_composer_count": UI.count_ui_composers(paths.ui_store_path),
        "cli_agent_count": CLI.count_cli_agents(paths.cursor_home),
        "transcript_only_count": TRANSCRIPTS.count_transcripts(paths.cursor_home),
        "ai_tracking_counts": AI.database_counts(paths.ai_tracking_db_path),
    }


def hook_config_status(path: Path) -> dict[str, Any]:
    status = {
        "path": str(path),
        "exists": path.exists(),
        "configured": False,
        "stop_command_count": 0,
        "parse_error": None,
    }
    if not path.exists():
        return status
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        status["parse_error"] = str(exc)
        return status
    hooks = payload.get("hooks") if isinstance(payload, dict) else None
    stop_hooks = hooks.get("stop") if isinstance(hooks, dict) else None
    if not isinstance(stop_hooks, list):
        return status
    for item in stop_hooks:
        if not isinstance(item, dict):
            continue
        command = item.get("command")
        if not isinstance(command, str):
            continue
        status["stop_command_count"] += 1
        if "cursor-session-inspector" in command and (
            "sync_session.py" in command or "debug_hook.py" in command
        ):
            status["configured"] = True
    return status


def recommended_hook_command() -> str:
    return (
        "sh -c 'p=$(ls -dt "
        "${HOME}/.cursor/plugins/cache/*/cursor-session-inspector/*/skills/cursor-session-inspector/scripts/sync_session.py "
        "2>/dev/null | head -1); [ -n \"$p\" ] && uv run --python 3.14 \"$p\"'"
    )


def hook_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "hooks": {
            "stop": [
                {
                    "matcher": "*",
                    "command": recommended_hook_command(),
                    "timeout": 30,
                }
            ]
        },
    }


def hook_create_file_snippet(path: Path) -> str:
    payload = json.dumps(hook_payload(), indent=2)
    return f"cat > {shlex.quote(str(path))} <<'JSON'\n{payload}\nJSON"


def hook_merge_jq_command(path: Path) -> str:
    hook = json.dumps(hook_payload()["hooks"]["stop"][0], separators=(",", ":"))
    return (
        f"tmp=$(mktemp); jq --argjson hook {shlex.quote(hook)} "
        "'.version = 1 | .hooks.stop = ((.hooks.stop // []) + [$hook])' "
        f"{shlex.quote(str(path))} > \"$tmp\" && mv \"$tmp\" {shlex.quote(str(path))}"
    )


def workspace_count(cursor_home: Path) -> int:
    projects_dir = cursor_home / "projects"
    if not projects_dir.exists():
        return 0
    return sum(1 for item in projects_dir.iterdir() if item.is_dir())


def records_payload(
    paths: CursorPaths,
    *,
    target: str | None,
    record_type: str | None,
    tool_name: str | None,
    tail: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    records.extend(_ui_records(paths, target=target, record_type=record_type, tool_name=tool_name))
    if not records:
        records.extend(_cli_records(paths, target=target, record_type=record_type))
    if not records:
        records.extend(_transcript_records(paths, target=target, record_type=record_type))
    if not records:
        raise ValueError(f"could not resolve raw Cursor target: {target}")
    return records[-tail:] if tail > 0 else records


def _ui_records(
    paths: CursorPaths,
    *,
    target: str | None,
    record_type: str | None,
    tool_name: str | None,
) -> list[dict[str, Any]]:
    if record_type not in {None, "composer", "bubble", "tool_result", "thinking_block"}:
        return []
    if not paths.ui_store_path.exists():
        return []
    snapshot_path: Path | None = None
    try:
        snapshot_path = UI.snapshot_state_vscdb(paths.ui_store_path)
        composers = list(UI.list_composers(snapshot_path))
        composer = _select_composer(composers, target)
        if composer is None:
            return []
        records: list[dict[str, Any]] = []
        if record_type in {None, "composer"}:
            records.append({"record_type": "composer", "session_id": composer.composer_id, "payload": composer.payload})
        for header, bubble in UI.iter_bubbles(snapshot_path, composer):
            if bubble is None:
                continue
            payload = bubble.payload
            if record_type in {None, "bubble"}:
                records.append(
                    {
                        "record_type": "bubble",
                        "session_id": composer.composer_id,
                        "bubble_id": bubble.bubble_id,
                        "header": header,
                        "payload": payload,
                    }
                )
            if record_type in {None, "tool_result"}:
                for item in _list(payload.get("toolResults")):
                    if tool_name and tool_name.lower() not in json.dumps(item, sort_keys=True).lower():
                        continue
                    records.append(
                        {
                            "record_type": "tool_result",
                            "session_id": composer.composer_id,
                            "bubble_id": bubble.bubble_id,
                            "payload": item,
                        }
                    )
            if record_type in {None, "thinking_block"}:
                for item in _list(payload.get("allThinkingBlocks")):
                    records.append(
                        {
                            "record_type": "thinking_block",
                            "session_id": composer.composer_id,
                            "bubble_id": bubble.bubble_id,
                            "payload": item,
                        }
                    )
        return records
    finally:
        if snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)


def _cli_records(paths: CursorPaths, *, target: str | None, record_type: str | None) -> list[dict[str, Any]]:
    if record_type not in {None, "cli_message"}:
        return []
    agents = CLI.list_cli_agents(paths.cursor_home)
    agent = _select_cli_agent(agents, target)
    if agent is None:
        return []
    return [
        {
            "record_type": "cli_message",
            "session_id": agent.session_id,
            "blob_id": message.blob_id,
            "kind": message.kind,
            "role": message.role,
            "content": message.content,
            "payload": message.payload,
        }
        for message in CLI.walk_messages(agent.store_db_path, root_blob_id=agent.latest_root_blob_id)
    ]


def _transcript_records(paths: CursorPaths, *, target: str | None, record_type: str | None) -> list[dict[str, Any]]:
    if record_type not in {None, "transcript"}:
        return []
    for transcript in TRANSCRIPTS.iter_transcripts(paths.cursor_home, include_subagents=True):
        haystack = f"{transcript.session_id} {transcript.path}".lower()
        if target and target.lower() not in haystack:
            continue
        records, parse_errors = TRANSCRIPTS.load_records(transcript.path)
        return [
            {
                "record_type": "transcript",
                "session_id": transcript.session_id,
                "path": str(transcript.path),
                "parse_errors": parse_errors,
                "payload": record,
            }
            for record in records
        ]
    return []


def _select_composer(composers: list[Any], target: str | None) -> Any | None:
    if not composers:
        return None
    if target is None:
        return composers[0]
    target_lower = target.lower()
    for composer in composers:
        haystack = json.dumps(
            {
                "composer_id": composer.composer_id,
                "key": composer.key,
                "name": composer.payload.get("name"),
                "header": composer.header,
            },
            sort_keys=True,
        ).lower()
        if target_lower in haystack:
            return composer
    return None


def _select_cli_agent(agents: list[Any], target: str | None) -> Any | None:
    if not agents:
        return None
    if target is None:
        return agents[0]
    target_lower = target.lower()
    for agent in agents:
        haystack = json.dumps(
            {
                "session_id": agent.session_id,
                "agent_id": agent.agent_id,
                "name": agent.name,
                "workspace_hash": agent.workspace_hash,
                "path": str(agent.store_db_path),
            },
            sort_keys=True,
        ).lower()
        if target_lower in haystack:
            return agent
    return None


def _ensure_cache_for_read(paths: CursorPaths, *, target: str | None = None) -> None:
    if paths.db_path.exists():
        return
    print("SQLite cache not found; running refresh first.", file=sys.stderr)
    IMPORTER.refresh_sessions(
        paths.cursor_home,
        app_support=paths.cursor_app_support,
        target=target,
        reconcile=False,
        analyze=True,
    )


def emit(json_mode: bool, payload: Any) -> None:
    if json_mode or not isinstance(payload, (list, dict)):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


if __name__ == "__main__":
    sys.exit(main())
