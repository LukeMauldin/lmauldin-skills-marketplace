from __future__ import annotations

import importlib.util
import re
import sqlite3
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PARSER_VERSION = 4
BATCH_SIZE = 50
SOURCE = "claude_code"
SUBAGENT_SESSION_SEPARATOR = "::subagent::"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


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


DB = _load_module("claude_session_inspector_db", "db.py")


def _load_parser() -> Any:
    return _load_module("claude_session_inspector_runtime", "inspect_session.py")


def resolve_db_path(claude_home: Path) -> Path:
    return DB.default_db_path(claude_home.expanduser())


def build_subagent_session_id(parent_session_id: str, agent_id: str) -> str:
    return f"{parent_session_id}{SUBAGENT_SESSION_SEPARATOR}{agent_id}"


def split_subagent_session_id(session_id: str) -> tuple[str, str] | None:
    if SUBAGENT_SESSION_SEPARATOR not in session_id:
        return None
    parent_session_id, agent_id = session_id.split(SUBAGENT_SESSION_SEPARATOR, 1)
    if not parent_session_id or not agent_id:
        return None
    return parent_session_id, agent_id


def _subagents_dir_ancestor(path: Path) -> Path | None:
    """Return the nearest ancestor directory named ``subagents``, if any.

    Handles both direct subagents (``<session>/subagents/agent-*.jsonl``) and
    nested workflow subagents (``<session>/subagents/workflows/<wf>/agent-*.jsonl``).
    """
    for ancestor in path.parents:
        if ancestor.name == "subagents":
            return ancestor
    return None


def is_subagent_path(path: Path) -> bool:
    if not (path.name.startswith("agent-") and path.suffix == ".jsonl"):
        return False
    return _subagents_dir_ancestor(path) is not None


def subagent_agent_id(path: Path) -> str | None:
    """Collision-safe agent id for a subagent transcript path.

    Direct subagents keep their bare hex id (``<hex>``); nested workflow
    subagents are qualified by their directory under ``subagents`` so two
    workflow runs that reuse an agent-id hex cannot collide on the same parent:
    ``workflows/<wf>/<hex>``.  This is the single source of truth shared by the
    parser's ``list_subagents`` and ``session_id_for_path`` below.
    """
    subagents_dir = _subagents_dir_ancestor(path)
    if subagents_dir is None:
        return None
    hex_id = path.stem.removeprefix("agent-")
    rel_parent = path.parent.relative_to(subagents_dir)
    if rel_parent == Path("."):
        return hex_id
    return f"{rel_parent.as_posix()}/{hex_id}"


def parent_session_id_for_subagent(path: Path) -> str | None:
    subagents_dir = _subagents_dir_ancestor(path)
    return subagents_dir.parent.name if subagents_dir is not None else None


def session_id_for_path(path: Path) -> str:
    if not is_subagent_path(path):
        return path.stem
    parent_session_id = parent_session_id_for_subagent(path)
    agent_id = subagent_agent_id(path)
    if not parent_session_id or not agent_id:
        return path.stem
    return build_subagent_session_id(parent_session_id, agent_id)


def parent_session_path_for_subagent(path: Path) -> Path | None:
    if not is_subagent_path(path):
        return None
    subagents_dir = _subagents_dir_ancestor(path)
    if subagents_dir is None:
        return None
    project_dir = subagents_dir.parent.parent
    parent_session_id = subagents_dir.parent.name
    candidate = project_dir / f"{parent_session_id}.jsonl"
    return candidate if candidate.exists() else None


def should_scope_project_for_target(target: str | None) -> bool:
    if not isinstance(target, str) or not target:
        return True
    if UUID_RE.match(target):
        return False
    return split_subagent_session_id(target) is None


def reconcile_pending(claude_home: Path) -> list[str]:
    db_path = resolve_db_path(claude_home)
    now = datetime.now(timezone.utc)

    def handler(payload: dict[str, Any]) -> bool:
        if not DB.is_retryable_pending_marker(payload):
            return False
        not_before = DB.parse_marker_timestamp(payload.get("not_before"))
        if not_before is not None and not_before > now:
            return False
        target = payload.get("target") or payload.get("session_id")
        project = payload.get("project")
        if not should_scope_project_for_target(target):
            project = None
        elif project is None:
            cwd = payload.get("cwd")
            project = cwd if isinstance(cwd, str) and cwd else None
        try:
            refresh_sessions(
                claude_home,
                target=target if isinstance(target, str) else None,
                project=project if isinstance(project, str) else None,
                reconcile=False,
                analyze=False,
            )
            return True
        except Exception:
            return False

    return DB.reconcile_pending_markers(db_path, handler)


def resolve_refresh_target(
    claude_home: Path,
    target: str,
    *,
    project: str | None = None,
) -> Path:
    parser = _load_parser()
    paths = parser.resolve_paths(claude_home.expanduser())
    return parser.resolve_target(paths, target, project=project)


def refresh_sessions(
    claude_home: Path,
    *,
    target: str | None = None,
    project: str | None = None,
    since: date | None = None,
    session_paths: Sequence[Path] | None = None,
    reconcile: bool = True,
    analyze: bool = True,
) -> dict[str, Any]:
    claude_home = claude_home.expanduser()
    reconciled_pending: list[str] = []
    if reconcile:
        reconciled_pending = reconcile_pending(claude_home)

    parser = _load_parser()
    db_path = resolve_db_path(claude_home)
    targets = _collect_refresh_targets(
        parser,
        claude_home,
        target=target,
        project=project,
        since=since,
        session_paths=session_paths,
    )
    counts = {"imported": 0, "skipped": 0, "failed": 0, "errors": []}
    with DB.open_db(db_path) as conn:
        for start in range(0, len(targets), BATCH_SIZE):
            batch = targets[start : start + BATCH_SIZE]
            for session_path in batch:
                try:
                    result = import_session_tree(conn, session_path, parser)
                except Exception as exc:
                    counts["failed"] += 1
                    counts["errors"].append({"path": str(session_path), "error": str(exc)})
                    continue
                counts["imported"] += int(result["imported"])
                counts["skipped"] += int(result["skipped"])
            conn.commit()
        if analyze and counts["imported"] > 0:
            conn.execute("ANALYZE")
    counts["db_path"] = str(db_path)
    counts["reconciled_pending"] = reconciled_pending
    counts["reconciled_pending_count"] = len(reconciled_pending)
    return counts


def rebuild_sessions(
    claude_home: Path,
    *,
    target: str | None = None,
    project: str | None = None,
    since: date | None = None,
) -> dict[str, Any]:
    db_path = resolve_db_path(claude_home.expanduser())
    DB.remove_db_files(db_path)
    return refresh_sessions(
        claude_home,
        target=target,
        project=project,
        since=since,
        reconcile=False,
        analyze=True,
    )


def _collect_refresh_targets(
    parser: Any,
    claude_home: Path,
    *,
    target: str | None,
    project: str | None,
    since: date | None,
    session_paths: Sequence[Path] | None,
) -> list[Path]:
    paths = parser.resolve_paths(claude_home)
    raw_targets: list[Path] = []
    if session_paths is not None:
        raw_targets.extend(path.expanduser() for path in session_paths)
    elif target is not None:
        raw_targets.append(parser.resolve_target(paths, target, project=project))
    else:
        raw_targets.extend(session.path for session in parser.collect_sessions(paths, project=project, since=since))

    deduped: list[Path] = []
    seen: set[str] = set()
    for raw_target in raw_targets:
        normalized = raw_target
        if is_subagent_path(raw_target):
            parent = parent_session_path_for_subagent(raw_target)
            if parent is not None:
                normalized = parent
        key = str(normalized)
        if key not in seen:
            seen.add(key)
            deduped.append(normalized)
    return deduped


def import_session_tree(conn: sqlite3.Connection, session_path: Path, parser: Any | None = None) -> dict[str, int]:
    parser = parser or _load_parser()
    session_id = session_path.stem
    subagents = parser.list_subagents(session_path)
    if _tree_is_fresh(conn, session_path, session_id, subagents):
        return {"imported": 0, "skipped": 1}

    existing_children = DB.child_session_ids(conn, session_id)
    for child_session_id in existing_children:
        DB.delete_session(conn, child_session_id)
    DB.delete_session(conn, session_id)

    loaded = parser.load_session(session_path)
    project = parser.project_dir_name_for_path(session_path)
    project_cwd = parser.decode_project_dir_name(project) if project else None
    parsed = parser.parse_loaded_session(
        loaded,
        session_id_override=session_id,
        project=project,
        project_cwd=project_cwd,
    )
    summary = parser.build_session_summary(parsed, subagents=subagents)
    _insert_claude_session(conn, parser, parsed, summary, parent_session_id=None, agent_id=None)
    DB.record_import(
        conn,
        session_path,
        session_id=session_id,
        parser_version=PARSER_VERSION,
        record_count=parsed.record_count,
    )

    imported = 1
    for subagent in subagents:
        imported += _import_subagent(conn, parser, parsed.session_id, project, project_cwd, subagent)
    return {"imported": imported, "skipped": 0}


def _tree_is_fresh(
    conn: sqlite3.Connection,
    session_path: Path,
    session_id: str,
    subagents: Sequence[Any],
) -> bool:
    if not DB.should_skip(conn, session_path, PARSER_VERSION):
        return False
    current_children = {
        build_subagent_session_id(session_id, subagent.agent_id)
        for subagent in subagents
    }
    existing_children = set(DB.child_session_ids(conn, session_id))
    if current_children != existing_children:
        return False
    return all(DB.should_skip(conn, subagent.path, PARSER_VERSION) for subagent in subagents)


def _import_subagent(
    conn: sqlite3.Connection,
    parser: Any,
    parent_session_id: str,
    project: str | None,
    project_cwd: str | None,
    subagent: Any,
) -> int:
    child_session_id = build_subagent_session_id(parent_session_id, subagent.agent_id)
    DB.delete_session(conn, child_session_id)

    loaded = parser.load_session(subagent.path)
    parsed = parser.parse_loaded_session(
        loaded,
        session_id_override=child_session_id,
        project=project,
        project_cwd=project_cwd,
    )
    summary = parser.build_session_summary(parsed, subagents=[])
    _insert_claude_session(
        conn,
        parser,
        parsed,
        summary,
        parent_session_id=parent_session_id,
        agent_id=subagent.agent_id,
    )
    conn.execute(
        """
        INSERT INTO subagent_links(
            parent_session_id,
            child_session_id,
            agent_nickname,
            agent_role,
            model,
            first_task
        )
        VALUES(?, ?, ?, ?, ?, ?)
        """,
        (
            parent_session_id,
            child_session_id,
            subagent.agent_id,
            None,
            subagent.model,
            subagent.first_task,
        ),
    )
    DB.record_import(
        conn,
        subagent.path,
        session_id=child_session_id,
        parser_version=PARSER_VERSION,
        record_count=parsed.record_count,
    )
    return 1


def _insert_claude_session(
    conn: sqlite3.Connection,
    parser: Any,
    parsed: Any,
    summary: dict[str, Any],
    *,
    parent_session_id: str | None,
    agent_id: str | None,
) -> None:
    session_meta = summary.get("session_meta") if isinstance(summary.get("session_meta"), dict) else {}
    token_usage = summary.get("token_usage") if isinstance(summary.get("token_usage"), dict) else {}
    hook_summary = summary.get("hook_summary") if isinstance(summary.get("hook_summary"), dict) else {}
    model_counts = summary.get("models") if isinstance(summary.get("models"), dict) else {}
    thinking_blocks = [
        thinking_block
        for turn in parsed.turns
        for thinking_block in turn.thinking_blocks
    ]
    # Reconcile each turn's aggregate cache-write total with its per-TTL split
    # into pricing buckets (5m + 1h == reconciled total).  Computed once and
    # reused for both the per-turn rows and the session totals so they agree.
    turn_cache_buckets: dict[int, tuple[int, int]] = {
        turn.index: parser.reconcile_cache_creation(
            turn.token_usage.cache_creation_input_tokens,
            turn.token_usage.cache_creation_5m_input_tokens,
            turn.token_usage.cache_creation_1h_input_tokens,
        )
        for turn in parsed.turns
    }
    total_cache_create_5m = sum(five for five, _one in turn_cache_buckets.values())
    total_cache_create_1h = sum(one for _five, one in turn_cache_buckets.values())
    title = parser.display_name_for_session(
        custom_title=summary.get("custom_title"),
        agent_name=summary.get("agent_name"),
        slug=summary.get("slug"),
        first_user_message=summary.get("first_user_message"),
    )
    session_row = {
        "session_id": parsed.session_id,
        "source": SOURCE,
        "file_path": str(parsed.path),
        "project": summary.get("project"),
        "cwd": session_meta.get("cwd") or summary.get("project_cwd"),
        "title": title,
        "display_name": title,
        "model": parser.dominant_model_from_counts(model_counts) if model_counts else None,
        "git_branch": summary.get("latest_git_branch"),
        "git_commit": None,
        "version": session_meta.get("version"),
        "first_user_message": summary.get("first_user_message"),
        "start_timestamp": summary.get("timestamp"),
        "archived": 0,
        "is_subagent": 1 if parent_session_id else 0,
        "parent_session_id": parent_session_id,
        "forked_from_id": None,
        "agent_nickname": agent_id,
        "agent_role": None,
        "record_count": summary.get("record_count") or 0,
        "parse_errors": summary.get("parse_errors") or 0,
        "turn_count": summary.get("turn_count") or 0,
        "completed_turn_count": summary.get("completed_turn_count") or 0,
        "total_turn_duration_ms": summary.get("total_turn_duration_ms") or 0,
        "total_input_tokens": token_usage.get("input_tokens") or 0,
        "total_output_tokens": token_usage.get("output_tokens") or 0,
        "total_cache_read": token_usage.get("cache_read_input_tokens") or 0,
        "total_cache_create": token_usage.get("cache_creation_input_tokens") or 0,
        "total_cache_create_5m": total_cache_create_5m,
        "total_cache_create_1h": total_cache_create_1h,
        "tool_call_count": sum(len(turn.tool_calls) for turn in parsed.turns),
        "tool_error_count": summary.get("tool_error_count") or 0,
        "server_tool_call_count": summary.get("server_tool_call_count") or 0,
        "server_tool_aborted_count": summary.get("server_tool_aborted_count") or 0,
        "server_tool_input_tokens": summary.get("server_tool_input_tokens") or 0,
        "server_tool_output_tokens": summary.get("server_tool_output_tokens") or 0,
        "server_tool_total_latency_ms": summary.get("server_tool_total_latency_ms") or 0,
        "api_error_count": summary.get("api_error_count") or 0,
        "max_tokens_stops": summary.get("max_tokens_stop_count") or 0,
        "total_hook_ms": hook_summary.get("total_duration_ms") or 0,
        "total_thinking_blocks": len(thinking_blocks),
        "total_redacted_blocks": sum(1 for block in thinking_blocks if block.is_redacted),
        "total_thinking_content_len": sum(block.content_length for block in thinking_blocks),
        "total_reasoning_tokens": 0,
        "user_message_count": len(parsed.user_messages),
        "user_interrupt_count": sum(1 for message in parsed.user_messages if message.is_interrupt),
        "total_user_char_count": sum(message.char_count for message in parsed.user_messages),
        "models_used": DB.json_dumps(summary.get("models_used") or []),
        "slug": summary.get("slug"),
        "custom_title": summary.get("custom_title"),
        "agent_name": summary.get("agent_name"),
        "permission_mode": session_meta.get("permissionMode"),
        "entrypoint": session_meta.get("entrypoint"),
        "api_call_count": token_usage.get("api_calls") or 0,
        "thread_name": None,
        "filename_timestamp": None,
        "model_provider": None,
        "token_mode": None,
        "record_counts_json": DB.json_dumps(summary.get("record_counts")),
        "system_subtypes_json": DB.json_dumps(summary.get("system_subtypes")),
        "event_counts_json": None,
        "response_item_counts_json": None,
        "session_meta_json": DB.json_dumps(session_meta),
        "git_json": None,
        "latest_turn_context_json": None,
        "token_usage_json": DB.json_dumps(token_usage),
        "tool_usage_json": DB.json_dumps(
            {
                "all_calls": summary.get("tool_usage") or {},
                "tool_errors_by_name": summary.get("tool_errors_by_name") or {},
            }
        ),
        "turn_durations_json": DB.json_dumps(
            {
                "durations": summary.get("turn_durations_ms") or [],
                "completed_count": summary.get("completed_turn_count") or 0,
                "incomplete_count": summary.get("incomplete_turn_count") or 0,
            }
        ),
        "current_subagent_json": None,
    }
    columns = ", ".join(session_row)
    placeholders = ", ".join(f":{column}" for column in session_row)
    conn.execute(f"INSERT INTO sessions ({columns}) VALUES ({placeholders})", session_row)

    turn_row_ids: dict[int, int] = {}
    for turn in parsed.turns:
        cursor = conn.execute(
            """
            INSERT INTO turns(
                session_id,
                turn_index,
                message_id,
                timestamp,
                model,
                stop_reason,
                speed,
                duration_ms,
                user_gap_ms,
                input_tokens,
                output_tokens,
                cache_read,
                cache_create,
                cache_create_5m,
                cache_create_1h,
                text_block_count,
                thinking_block_count,
                tool_use_block_count,
                reasoning_output_tokens
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.session_id,
                turn.index,
                turn.message_id,
                parser.isoformat_utc(turn.timestamp),
                turn.model,
                turn.stop_reason,
                turn.speed,
                turn.turn_duration_ms,
                turn.user_gap_ms,
                turn.token_usage.input_tokens,
                turn.token_usage.output_tokens,
                turn.token_usage.cache_read_input_tokens,
                turn.token_usage.cache_creation_input_tokens,
                turn_cache_buckets[turn.index][0],
                turn_cache_buckets[turn.index][1],
                turn.text_block_count,
                turn.thinking_block_count,
                turn.tool_use_block_count,
                turn.reasoning_output_tokens,
            ),
        )
        turn_row_ids[turn.index] = int(cursor.lastrowid)

    global_call_order = 0
    for turn in parsed.turns:
        turn_row_id = turn_row_ids[turn.index]
        for tool_call in turn.tool_calls:
            global_call_order += 1
            conn.execute(
                """
                INSERT INTO tool_calls(
                    turn_id,
                    session_id,
                    tool_name,
                    tool_use_id,
                    file_path,
                    command,
                    is_error,
                    error_text,
                    call_type,
                    call_id,
                    call_order
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_row_id,
                    parsed.session_id,
                    tool_call.name,
                    tool_call.tool_use_id or None,
                    tool_call.file_path,
                    tool_call.command,
                    1 if tool_call.is_error else 0,
                    tool_call.error_text,
                    None,
                    None,
                    global_call_order,
                ),
            )

    global_stc_order = 0
    for turn in parsed.turns:
        turn_row_id = turn_row_ids[turn.index]
        for stc in turn.server_tool_calls:
            global_stc_order += 1
            conn.execute(
                """
                INSERT INTO server_tool_calls(
                    turn_id,
                    session_id,
                    tool_name,
                    tool_use_id,
                    call_order,
                    is_aborted,
                    emit_timestamp,
                    result_timestamp,
                    latency_ms,
                    iteration_type,
                    iteration_model,
                    iteration_input_tokens,
                    iteration_output_tokens,
                    iteration_cache_read,
                    iteration_cache_create,
                    iteration_cache_create_5m,
                    iteration_cache_create_1h
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_row_id,
                    parsed.session_id,
                    stc.name,
                    stc.tool_use_id,
                    global_stc_order,
                    1 if stc.is_aborted else 0,
                    parser.isoformat_utc(stc.emit_timestamp),
                    parser.isoformat_utc(stc.result_timestamp),
                    stc.latency_ms,
                    stc.iteration_type,
                    stc.iteration_model,
                    stc.iteration_input_tokens,
                    stc.iteration_output_tokens,
                    stc.iteration_cache_read,
                    stc.iteration_cache_create,
                    *parser.reconcile_cache_creation(
                        stc.iteration_cache_create,
                        stc.iteration_cache_create_5m,
                        stc.iteration_cache_create_1h,
                    ),
                ),
            )

    for turn in parsed.turns:
        turn_row_id = turn_row_ids[turn.index]
        for thinking_block in turn.thinking_blocks:
            conn.execute(
                """
                INSERT INTO thinking_blocks(
                    turn_id,
                    session_id,
                    block_index,
                    block_type,
                    is_redacted,
                    content_length,
                    signature_length,
                    has_signature
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    turn_row_id,
                    parsed.session_id,
                    thinking_block.block_index,
                    "thinking",
                    1 if thinking_block.is_redacted else 0,
                    thinking_block.content_length,
                    thinking_block.signature_length,
                    1 if thinking_block.has_signature else 0,
                ),
            )

    for user_message in parsed.user_messages:
        conn.execute(
            """
            INSERT INTO user_messages(
                session_id,
                message_index,
                timestamp,
                is_first,
                is_interrupt,
                word_count,
                char_count,
                preceding_turn_index
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.session_id,
                user_message.message_index,
                parser.isoformat_utc(user_message.timestamp),
                1 if user_message.is_first else 0,
                1 if user_message.is_interrupt else 0,
                user_message.word_count,
                user_message.char_count,
                user_message.preceding_turn_index,
            ),
        )

    for hook in parsed.hooks:
        conn.execute(
            """
            INSERT INTO hook_executions(session_id, hook_command, duration_ms, is_error)
            VALUES(?, ?, ?, ?)
            """,
            (
                parsed.session_id,
                hook.command,
                hook.duration_ms,
                1 if hook.is_error else 0,
            ),
        )

    for pr_link in parsed.pr_links:
        conn.execute(
            """
            INSERT INTO pr_links(session_id, url, number, repository)
            VALUES(?, ?, ?, ?)
            """,
            (
                parsed.session_id,
                pr_link.get("prUrl"),
                pr_link.get("prNumber"),
                pr_link.get("prRepository"),
            ),
        )


def list_payload(
    claude_home: Path,
    *,
    project: str | None,
    since: date | None,
    limit: int,
    profile: str,
) -> list[dict[str, Any]]:
    with DB.open_db(resolve_db_path(claude_home)) as conn:
        rows = _list_session_rows(conn, project=project, since=since, limit=limit)
        return [
            _session_row_to_ingestion_stub(row) if profile == "ingestion" else _session_row_to_descriptor(row)
            for row in rows
        ]


def summary_payload(claude_home: Path, session_id: str, *, profile: str) -> dict[str, Any] | None:
    with DB.open_db(resolve_db_path(claude_home)) as conn:
        row = DB.session_row(conn, session_id)
        if row is None:
            return None
        summary = _session_row_to_summary(conn, row)
        if profile == "ingestion":
            parser = _load_parser()
            payload = parser.summarize_session_ingestion(summary)
            payload["schema_version"] = "session_inspector_v2"
            return payload
        return summary


def subagents_payload(
    claude_home: Path,
    parent_session_id: str,
    *,
    profile: str,
    agent_id: str | None = None,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    with DB.open_db(resolve_db_path(claude_home)) as conn:
        parent_row = DB.session_row(conn, parent_session_id)
        if parent_row is None:
            return None
        child_rows = _child_rows_for_parent(conn, parent_session_id)
        payloads = [_subagent_row_to_summary(conn, row) for row in child_rows]
        if agent_id is not None:
            matched = next((payload for payload in payloads if payload.get("agent_id") == agent_id), None)
            if matched is None:
                return None
            if profile == "ingestion":
                parser = _load_parser()
                payload = parser.build_subagent_ingestion_summary(Path(str(parent_row["file_path"])), matched)
                payload["schema_version"] = "session_inspector_v2"
                return payload
            return matched
        if profile == "ingestion":
            parser = _load_parser()
            parent_path = Path(str(parent_row["file_path"]))
            results = [parser.build_subagent_ingestion_summary(parent_path, payload) for payload in payloads]
            for result in results:
                result["schema_version"] = "session_inspector_v2"
            return results
        return payloads


def _list_session_rows(
    conn: sqlite3.Connection,
    *,
    project: str | None,
    since: date | None,
    limit: int,
) -> list[sqlite3.Row]:
    clauses = ["is_subagent = 0"]
    params: list[Any] = []
    if project:
        like_value = f"%{project.lower()}%"
        clauses.append("(LOWER(COALESCE(project, '')) LIKE ? OR LOWER(COALESCE(cwd, '')) LIKE ?)")
        params.extend([like_value, like_value])
    if since is not None:
        clauses.append("DATE(start_timestamp) >= DATE(?)")
        params.append(since.isoformat())
    query = f"""
        SELECT *
        FROM sessions
        WHERE {' AND '.join(clauses)}
        ORDER BY COALESCE(start_timestamp, imported_at) DESC
        LIMIT ?
    """
    params.append(limit)
    return conn.execute(query, params).fetchall()


def _session_row_to_descriptor(row: sqlite3.Row) -> dict[str, Any]:
    file_path = Path(str(row["file_path"]))
    size_bytes = file_path.stat().st_size if file_path.exists() else None
    return {
        "path": str(row["file_path"]),
        "session_id": row["session_id"],
        "project": row["project"],
        "project_cwd": row["cwd"],
        "timestamp": row["start_timestamp"],
        "slug": row["slug"],
        "custom_title": row["custom_title"],
        "agent_name": row["agent_name"],
        "display_name": row["display_name"] or row["title"],
        "size_bytes": size_bytes,
    }


def _session_row_to_ingestion_stub(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "session_inspector_v2",
        "source": SOURCE,
        "kind": "session_stub",
        "session": {
            "id": row["session_id"],
            "path": row["file_path"],
            "project": row["project"],
            "cwd": row["cwd"],
            "timestamp": row["start_timestamp"],
            "title": row["title"],
            "display_name": row["display_name"] or row["title"],
            "archived": None,
            "version": row["version"],
            "model_provider": None,
            "model": row["model"],
            "git_branch": row["git_branch"],
            "git_commit": None,
            "session_origin": row["entrypoint"],
            "is_subagent": False,
            "parent_session_id": None,
            "forked_from_session_id": None,
            "agent": {
                "nickname": row["agent_name"],
                "role": None,
                "path": None,
                "depth": None,
            }
            if row["agent_name"]
            else None,
        },
    }


def _session_row_to_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    session_id = str(row["session_id"])
    turns = _load_turns(conn, session_id)
    hooks = _load_hooks(conn, session_id)
    pr_links = _load_pr_links(conn, session_id)
    subagents = _load_subagent_infos(conn, session_id)
    models = Counter[str]()
    tool_usage = Counter[str]()
    tool_errors_by_name = Counter[str]()
    turn_summaries: list[dict[str, Any]] = []
    turn_durations: list[int] = []

    server_tool_usage = Counter[str]()

    for turn_row in turns:
        model = turn_row["model"]
        if isinstance(model, str) and model:
            models[model] += 1
        duration_ms = turn_row["duration_ms"]
        if isinstance(duration_ms, int):
            turn_durations.append(duration_ms)
        tool_rows = conn.execute(
            "SELECT * FROM tool_calls WHERE turn_id = ? ORDER BY id",
            (turn_row["id"],),
        ).fetchall()
        tool_call_payloads = []
        for tool_row in tool_rows:
            tool_name = str(tool_row["tool_name"])
            tool_usage[tool_name] += 1
            if int(tool_row["is_error"] or 0):
                tool_errors_by_name[tool_name] += 1
            tool_call_payloads.append(
                {
                    "id": tool_row["tool_use_id"],
                    "name": tool_name,
                    "file_path": tool_row["file_path"],
                    "command": tool_row["command"],
                    "is_error": bool(tool_row["is_error"]),
                    "error_text": tool_row["error_text"],
                }
            )
        stc_rows = conn.execute(
            "SELECT * FROM server_tool_calls WHERE turn_id = ? ORDER BY call_order",
            (turn_row["id"],),
        ).fetchall()
        stc_payloads = []
        for stc_row in stc_rows:
            stc_name = str(stc_row["tool_name"])
            server_tool_usage[stc_name] += 1
            stc_payloads.append(
                {
                    "id": stc_row["tool_use_id"],
                    "name": stc_name,
                    "is_aborted": bool(stc_row["is_aborted"]),
                    "latency_ms": stc_row["latency_ms"],
                    "iteration_type": stc_row["iteration_type"],
                    "iteration_model": stc_row["iteration_model"],
                    "iteration_input_tokens": int(stc_row["iteration_input_tokens"] or 0),
                    "iteration_output_tokens": int(stc_row["iteration_output_tokens"] or 0),
                }
            )
        input_tokens = int(turn_row["input_tokens"] or 0)
        output_tokens = int(turn_row["output_tokens"] or 0)
        cache_create = int(turn_row["cache_create"] or 0)
        cache_read = int(turn_row["cache_read"] or 0)
        turn_summaries.append(
            {
                "index": turn_row["turn_index"],
                "message_id": turn_row["message_id"],
                "timestamp": turn_row["timestamp"],
                "model": turn_row["model"],
                "stop_reason": turn_row["stop_reason"],
                "duration_ms": turn_row["duration_ms"],
                "user_gap_ms": turn_row["user_gap_ms"],
                "token_usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_creation_input_tokens": cache_create,
                    "cache_read_input_tokens": cache_read,
                    "total_tokens": input_tokens + output_tokens,
                },
                "tool_calls": tool_call_payloads,
                "server_tool_calls": stc_payloads,
            }
        )

    return {
        "path": row["file_path"],
        "session_id": session_id,
        "project": row["project"],
        "project_cwd": row["cwd"],
        "timestamp": row["start_timestamp"],
        "slug": row["slug"],
        "custom_title": row["custom_title"],
        "agent_name": row["agent_name"],
        "latest_git_branch": row["git_branch"],
        "parse_errors": int(row["parse_errors"] or 0),
        "record_count": int(row["record_count"] or 0),
        "record_counts": DB.json_loads(row["record_counts_json"]) or {},
        "session_meta": DB.json_loads(row["session_meta_json"]) or None,
        "first_user_message": row["first_user_message"],
        "models": dict(models),
        "models_used": [model for model, _count in models.most_common()],
        "token_usage": {
            "input_tokens": int(row["total_input_tokens"] or 0),
            "output_tokens": int(row["total_output_tokens"] or 0),
            "cache_creation_input_tokens": int(row["total_cache_create"] or 0),
            "cache_read_input_tokens": int(row["total_cache_read"] or 0),
            "total_tokens": int(row["total_input_tokens"] or 0) + int(row["total_output_tokens"] or 0),
            "api_calls": int(row["api_call_count"] or 0),
        },
        "tool_usage": dict(tool_usage.most_common()),
        "tool_error_count": int(row["tool_error_count"] or 0),
        "tool_errors_by_name": dict(tool_errors_by_name.most_common()),
        "system_subtypes": DB.json_loads(row["system_subtypes_json"]) or {},
        "turn_count": int(row["turn_count"] or 0),
        "completed_turn_count": int(row["completed_turn_count"] or 0),
        "incomplete_turn_count": max(
            0,
            int(row["turn_count"] or 0) - int(row["completed_turn_count"] or 0),
        ),
        "max_tokens_stop_count": int(row["max_tokens_stops"] or 0),
        "turn_durations_ms": turn_durations,
        "total_turn_duration_ms": sum(turn_durations) if turn_durations else None,
        "api_error_count": int(row["api_error_count"] or 0),
        "hook_summary": _hook_summary(hooks),
        "server_tool_call_count": int(row["server_tool_call_count"] or 0),
        "server_tool_aborted_count": int(row["server_tool_aborted_count"] or 0),
        "server_tool_usage": dict(server_tool_usage.most_common()),
        "server_tool_input_tokens": int(row["server_tool_input_tokens"] or 0),
        "server_tool_output_tokens": int(row["server_tool_output_tokens"] or 0),
        "server_tool_total_latency_ms": int(row["server_tool_total_latency_ms"] or 0),
        "turns": turn_summaries,
        "pr_links": pr_links or None,
        "subagents": subagents or None,
    }


def _subagent_row_to_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    summary = _session_row_to_summary(conn, row)
    child_id = str(row["session_id"])
    split = split_subagent_session_id(child_id)
    parent_session_id, agent_id = split if split is not None else (row["parent_session_id"], row["agent_nickname"])
    return {
        "agent_id": agent_id,
        "path": summary["path"],
        "project": summary["project"],
        "project_cwd": summary["project_cwd"],
        "parent_session_id": parent_session_id,
        "record_count": summary["record_count"],
        "record_counts": summary["record_counts"],
        "model": row["model"],
        "first_task": summary["first_user_message"],
        "tool_usage": summary["tool_usage"],
        "tool_error_count": summary["tool_error_count"],
        "tool_errors_by_name": summary["tool_errors_by_name"],
        "token_usage": summary["token_usage"],
        "system_subtypes": summary["system_subtypes"],
        "turn_count": summary["turn_count"],
        "completed_turn_count": summary["completed_turn_count"],
        "incomplete_turn_count": summary["incomplete_turn_count"],
        "max_tokens_stop_count": summary["max_tokens_stop_count"],
        "api_error_count": summary["api_error_count"],
        "hook_summary": summary["hook_summary"],
        "server_tool_call_count": summary["server_tool_call_count"],
        "server_tool_aborted_count": summary["server_tool_aborted_count"],
        "server_tool_usage": summary["server_tool_usage"],
        "server_tool_input_tokens": summary["server_tool_input_tokens"],
        "server_tool_output_tokens": summary["server_tool_output_tokens"],
        "server_tool_total_latency_ms": summary["server_tool_total_latency_ms"],
        "turns": summary["turns"],
        "session_meta": summary["session_meta"],
        "parse_errors": summary["parse_errors"],
    }


def _load_turns(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM turns WHERE session_id = ? ORDER BY turn_index",
        (session_id,),
    ).fetchall()


def _load_hooks(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM hook_executions WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()


def _load_pr_links(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT number, url, repository FROM pr_links WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [
        {"prNumber": row["number"], "prUrl": row["url"], "prRepository": row["repository"]}
        for row in rows
    ]


def _child_rows_for_parent(conn: sqlite3.Connection, parent_session_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT sessions.*
        FROM subagent_links
        JOIN sessions ON sessions.session_id = subagent_links.child_session_id
        WHERE subagent_links.parent_session_id = ?
        ORDER BY sessions.start_timestamp, sessions.file_path
        """,
        (parent_session_id,),
    ).fetchall()


def _load_subagent_infos(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            sessions.file_path,
            sessions.record_count,
            sessions.model,
            subagent_links.agent_nickname,
            subagent_links.first_task
        FROM subagent_links
        JOIN sessions ON sessions.session_id = subagent_links.child_session_id
        WHERE subagent_links.parent_session_id = ?
        ORDER BY sessions.start_timestamp, sessions.file_path
        """,
        (session_id,),
    ).fetchall()
    return [
        {
            "agent_id": row["agent_nickname"],
            "path": row["file_path"],
            "record_count": row["record_count"],
            "model": row["model"],
            "first_task": row["first_task"],
        }
        for row in rows
    ]


def _hook_summary(hooks: Iterable[sqlite3.Row]) -> dict[str, Any]:
    by_command: dict[str, dict[str, Any]] = {}
    total_duration_ms = 0
    total_errors = 0
    count = 0
    for hook in hooks:
        count += 1
        command = str(hook["hook_command"])
        duration_ms = int(hook["duration_ms"] or 0)
        is_error = bool(hook["is_error"])
        total_duration_ms += duration_ms
        if is_error:
            total_errors += 1
        stats = by_command.setdefault(
            command,
            {"command": command, "count": 0, "total_duration_ms": 0, "errors": 0},
        )
        stats["count"] += 1
        stats["total_duration_ms"] += duration_ms
        if is_error:
            stats["errors"] += 1
    ordered = sorted(
        by_command.values(),
        key=lambda item: (-int(item["total_duration_ms"]), -int(item["count"]), str(item["command"])),
    )
    return {
        "count": count,
        "total_duration_ms": total_duration_ms,
        "errors": total_errors,
        "by_command": ordered,
    }
