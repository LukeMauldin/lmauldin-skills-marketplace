from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from collections import Counter
from collections.abc import Sequence
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PARSER_VERSION = 7
BATCH_SIZE = 50
SOURCE = "codex_cli"


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


def _load_parser() -> Any:
    return _load_module("codex_rollout_inspector_runtime", "inspect_rollout.py")


def resolve_db_path(codex_home: Path) -> Path:
    return DB.default_db_path(codex_home.expanduser())


def reconcile_pending(codex_home: Path) -> list[str]:
    db_path = resolve_db_path(codex_home)
    now = datetime.now(timezone.utc)

    def handler(payload: dict[str, Any]) -> bool:
        if not DB.is_retryable_pending_marker(payload):
            return False
        not_before = DB.parse_marker_timestamp(payload.get("not_before"))
        if not_before is not None and not_before > now:
            return False
        target = payload.get("target") or payload.get("session_id")
        if not isinstance(target, str) or not target:
            return False
        target_path = Path(target).expanduser()
        session_id = payload.get("session_id")
        if target_path.is_absolute() and not target_path.exists():
            if isinstance(session_id, str) and session_id:
                target = session_id
        try:
            refresh_rollouts(
                codex_home,
                target=target,
                reconcile=False,
                analyze=False,
            )
            return True
        except Exception:
            return False

    return DB.reconcile_pending_markers(db_path, handler)


def resolve_refresh_target(
    codex_home: Path,
    target: str,
    *,
    archived: bool | None = None,
    project: str | None = None,
) -> Path:
    parser = _load_parser()
    targets = _collect_refresh_targets(
        parser,
        codex_home.expanduser(),
        target=target,
        archived=archived,
        project=project,
        since=None,
        rollout_paths=None,
    )
    if not targets:
        raise FileNotFoundError(f"could not resolve rollout target: {target}")
    return targets[0]


def refresh_rollouts(
    codex_home: Path,
    *,
    target: str | None = None,
    archived: bool | None = None,
    project: str | None = None,
    since: date | None = None,
    rollout_paths: Sequence[Path] | None = None,
    reconcile: bool = True,
    analyze: bool = True,
) -> dict[str, Any]:
    codex_home = codex_home.expanduser()
    reconciled_pending: list[str] = []
    if reconcile:
        reconciled_pending = reconcile_pending(codex_home)

    parser = _load_parser()
    db_path = resolve_db_path(codex_home)
    targets = _collect_refresh_targets(
        parser,
        codex_home,
        target=target,
        archived=archived,
        project=project,
        since=since,
        rollout_paths=rollout_paths,
    )
    counts = {"imported": 0, "skipped": 0, "failed": 0, "errors": []}
    with closing(DB.open_db(db_path)) as conn:
        paths = parser.resolve_paths(codex_home)
        thread_names = parser.load_session_index(paths.session_index_path)
        for start in range(0, len(targets), BATCH_SIZE):
            batch = targets[start : start + BATCH_SIZE]
            for rollout_path in batch:
                try:
                    result = import_rollout_tree(conn, rollout_path, paths, parser, thread_names)
                except Exception as exc:
                    counts["failed"] += 1
                    counts["errors"].append({"path": str(rollout_path), "error": str(exc)})
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


def rebuild_rollouts(
    codex_home: Path,
    *,
    archived: bool | None = None,
    project: str | None = None,
    since: date | None = None,
) -> dict[str, Any]:
    db_path = resolve_db_path(codex_home.expanduser())
    DB.remove_db_files(db_path)
    return refresh_rollouts(
        codex_home,
        archived=archived,
        project=project,
        since=since,
        reconcile=False,
        analyze=True,
    )


def _collect_refresh_targets(
    parser: Any,
    codex_home: Path,
    *,
    target: str | None,
    archived: bool | None,
    project: str | None,
    since: date | None,
    rollout_paths: Sequence[Path] | None,
) -> list[Path]:
    paths = parser.resolve_paths(codex_home)
    thread_names = parser.load_session_index(paths.session_index_path)
    tree_cache = parser.get_rollout_tree_cache(paths)
    raw_targets: list[Path] = []
    if rollout_paths is not None:
        raw_targets.extend(path.expanduser() for path in rollout_paths)
    elif target is not None:
        candidate_path = Path(target).expanduser()
        if candidate_path.exists():
            raw_targets.append(candidate_path)
        elif project is None and parser.THREAD_ID_RE.match(target):
            raw_targets.append(tree_cache.resolve_thread_id(target))
        else:
            raw_targets.append(
                parser.resolve_target(
                    paths,
                    thread_names,
                    target,
                    archived=bool(archived),
                    project=project,
                )
            )
    else:
        cache = parser.get_quick_rollout_cache(paths, thread_names)
        archive_modes = [True] if archived else ([False] if archived is False else [False, True])
        for archived_mode in archive_modes:
            raw_targets.extend(
                item.path
                for item in cache.collect(
                    archived=archived_mode,
                    since=since,
                    project=project,
                )
            )
    normalized_targets = [
        _tree_root_rollout_path(tree_cache, rollout_path)
        for rollout_path in raw_targets
    ]
    deduped: list[Path] = []
    seen: set[str] = set()
    for rollout_path in normalized_targets:
        key = str(rollout_path)
        if key not in seen:
            seen.add(key)
            deduped.append(rollout_path)
    return deduped


def _tree_root_rollout_path(
    cache: Any,
    rollout_path: Path,
) -> Path:
    current_path = rollout_path
    seen_thread_ids: set[str] = set()
    while True:
        quick = cache.get_info(current_path)
        if quick.thread_id in seen_thread_ids:
            return current_path
        seen_thread_ids.add(quick.thread_id)
        parent_thread_id = quick.parent_thread_id
        if not parent_thread_id:
            return current_path
        try:
            current_path = cache.resolve_thread_id(parent_thread_id)
        except FileNotFoundError:
            return current_path


def import_rollout_tree(
    conn: sqlite3.Connection,
    rollout_path: Path,
    paths: Any,
    parser: Any | None = None,
    thread_names: dict[str, str] | None = None,
) -> dict[str, int]:
    parser = parser or _load_parser()
    if thread_names is None:
        thread_names = parser.load_session_index(paths.session_index_path)
    quick = parser.quick_rollout_info(rollout_path, thread_names)
    child_rollouts = parser.list_child_rollouts(rollout_path, paths, thread_names)
    if _tree_is_fresh(conn, rollout_path, quick.thread_id, child_rollouts):
        return {"imported": 0, "skipped": 1}

    existing_children = set(DB.child_session_ids(conn, quick.thread_id))
    current_children = {child.thread_id for child in child_rollouts}
    for child_session_id in sorted(existing_children | current_children):
        DB.delete_session(conn, child_session_id)
    DB.delete_session(conn, quick.thread_id)

    loaded = parser.load_rollout(rollout_path)
    summary = parser.summarize_rollout(loaded, paths, thread_names, include_subagents=False)
    _insert_rollout(conn, parser, loaded, summary, parent_thread_id=None)
    DB.record_import(
        conn,
        rollout_path,
        session_id=quick.thread_id,
        parser_version=PARSER_VERSION,
        record_count=len(loaded.records),
    )

    imported = 1
    for child in child_rollouts:
        child_loaded = parser.load_rollout(child.path)
        child_summary = parser.summarize_rollout(child_loaded, paths, thread_names, include_subagents=False)
        _insert_rollout(
            conn,
            parser,
            child_loaded,
            child_summary,
            parent_thread_id=quick.thread_id,
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
                quick.thread_id,
                child.thread_id,
                child.agent_nickname,
                child.agent_role,
                child.model,
                child_summary.get("first_user_message"),
            ),
        )
        DB.record_import(
            conn,
            child.path,
            session_id=child.thread_id,
            parser_version=PARSER_VERSION,
            record_count=len(child_loaded.records),
        )
        imported += 1
    return {"imported": imported, "skipped": 0}


def _tree_is_fresh(
    conn: sqlite3.Connection,
    rollout_path: Path,
    thread_id: str,
    child_rollouts: Sequence[Any],
) -> bool:
    if not DB.should_skip(conn, rollout_path, PARSER_VERSION):
        return False
    current_children = {child.thread_id for child in child_rollouts}
    existing_children = set(DB.child_session_ids(conn, thread_id))
    if current_children != existing_children:
        return False
    return all(DB.should_skip(conn, child.path, PARSER_VERSION) for child in child_rollouts)


def _insert_rollout(
    conn: sqlite3.Connection,
    parser: Any,
    loaded: Any,
    summary: dict[str, Any],
    *,
    parent_thread_id: str | None,
) -> None:
    session_meta = summary.get("session_meta") if isinstance(summary.get("session_meta"), dict) else {}
    git = summary.get("git") if isinstance(summary.get("git"), dict) else {}
    latest_turn_context = summary.get("latest_turn_context") if isinstance(summary.get("latest_turn_context"), dict) else {}
    token_usage = summary.get("token_usage") if isinstance(summary.get("token_usage"), dict) else {}
    tool_usage = summary.get("tool_usage") if isinstance(summary.get("tool_usage"), dict) else {}
    turn_durations = summary.get("turn_durations") if isinstance(summary.get("turn_durations"), dict) else {}
    current_subagent = summary.get("current_subagent") if isinstance(summary.get("current_subagent"), dict) else {}
    model_entries = summary.get("model_usage") if isinstance(summary.get("model_usage"), list) else []
    user_messages = parser.extract_user_message_metrics(loaded.records)
    reasoning_items = parser.extract_reasoning_block_metrics(loaded.records)
    default_model = _infer_default_model(loaded.records, latest_turn_context.get("model"))
    session_row = {
        "session_id": summary.get("thread_id"),
        "source": SOURCE,
        "file_path": summary.get("path"),
        "project": summary.get("project"),
        "cwd": summary.get("cwd"),
        "title": summary.get("title"),
        "display_name": summary.get("thread_name") or summary.get("title"),
        "model": latest_turn_context.get("model"),
        "git_branch": git.get("branch"),
        "git_commit": git.get("commit_hash"),
        "version": session_meta.get("cli_version"),
        "first_user_message": summary.get("first_user_message"),
        "raw_first_user_message": summary.get("raw_first_user_message"),
        "delegated_task": summary.get("delegated_task"),
        "start_timestamp": session_meta.get("timestamp")
        or parser.filename_timestamp_to_iso(summary.get("filename_timestamp")),
        "archived": 1 if summary.get("archived") else 0,
        "is_subagent": 1 if summary.get("is_subagent") else 0,
        "parent_session_id": parent_thread_id or current_subagent.get("parent_thread_id"),
        "forked_from_id": current_subagent.get("forked_from_id"),
        "agent_nickname": current_subagent.get("agent_nickname"),
        "agent_role": current_subagent.get("agent_role"),
        "record_count": summary.get("record_count") or 0,
        "parse_errors": summary.get("parse_errors") or 0,
        "turn_count": int(turn_durations.get("completed_count") or 0) + int(turn_durations.get("incomplete_count") or 0),
        "completed_turn_count": turn_durations.get("completed_count") or 0,
        "total_turn_duration_ms": turn_durations.get("total_duration_ms") or 0,
        "total_input_tokens": parser.nested_int(token_usage, "latest_total_token_usage", "input_tokens") or 0,
        "total_output_tokens": parser.nested_int(token_usage, "latest_total_token_usage", "output_tokens") or 0,
        "total_cache_read": parser.nested_int(token_usage, "latest_total_token_usage", "cached_input_tokens") or 0,
        "total_cache_write": parser.nested_int(
            token_usage,
            "latest_total_token_usage",
            "cache_write_tokens",
        ),
        "tool_call_count": sum((tool_usage.get("all_calls") or {}).values()),
        "tool_error_count": tool_usage.get("tool_error_count") or 0,
        "total_reasoning_items": len(reasoning_items),
        "total_encrypted_reasoning_items": sum(
            1 for item in reasoning_items if item["encrypted_content_length"] > 0
        ),
        "total_reasoning_content_len": sum(item["content_length"] for item in reasoning_items),
        "total_reasoning_tokens": parser.nested_int(
            token_usage,
            "latest_total_token_usage",
            "reasoning_output_tokens",
        )
        or 0,
        "user_message_count": len(user_messages),
        "user_interrupt_count": sum(1 for message in user_messages if message["is_interrupt"]),
        "total_user_char_count": sum(message["char_count"] for message in user_messages),
        "models_used": DB.json_dumps(model_entries),
        "thread_name": summary.get("thread_name"),
        "filename_timestamp": summary.get("filename_timestamp"),
        "model_provider": session_meta.get("model_provider"),
        "token_mode": "cumulative_snapshot",
        "record_counts_json": DB.json_dumps(summary.get("record_counts")),
        "event_counts_json": DB.json_dumps(summary.get("event_counts")),
        "response_item_counts_json": DB.json_dumps(summary.get("response_item_counts")),
        "session_meta_json": DB.json_dumps(session_meta),
        "git_json": DB.json_dumps(git),
        "latest_turn_context_json": DB.json_dumps(latest_turn_context),
        "token_usage_json": DB.json_dumps(token_usage),
        "tool_usage_json": DB.json_dumps(tool_usage),
        "turn_durations_json": DB.json_dumps(turn_durations),
        "current_subagent_json": DB.json_dumps(current_subagent),
    }
    columns = ", ".join(session_row)
    placeholders = ", ".join(f":{column}" for column in session_row)
    conn.execute(f"INSERT INTO sessions ({columns}) VALUES ({placeholders})", session_row)

    turns, token_event_rows = _extract_turn_and_token_rows(
        parser,
        loaded.records,
        default_model=default_model,
        model_provider=session_meta.get("model_provider"),
    )
    tool_rows = _extract_tool_rows(parser, loaded.records, turns)
    reasoning_counts_by_turn = Counter(item["turn_index"] for item in reasoning_items)
    tool_counts_by_turn = Counter(tool_row["turn_index"] for tool_row in tool_rows)
    turn_row_ids: dict[int, int] = {}
    for turn in turns:
        cursor = conn.execute(
            """
            INSERT INTO turns(
                session_id,
                turn_index,
                message_id,
                timestamp,
                model,
                duration_ms,
                input_tokens,
                cached_input_tokens,
                cache_write_tokens,
                output_tokens,
                total_tokens,
                reasoning_item_count,
                tool_use_block_count,
                reasoning_output_tokens
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary.get("thread_id"),
                turn["turn_index"],
                turn["message_id"],
                turn["timestamp"],
                turn["model"],
                turn["duration_ms"],
                turn["input_tokens"],
                turn["cached_input_tokens"],
                turn["cache_write_tokens"],
                turn["output_tokens"],
                turn["total_tokens"],
                reasoning_counts_by_turn.get(turn["turn_index"], 0),
                tool_counts_by_turn.get(turn["turn_index"], 0),
                turn["reasoning_output_tokens"],
            ),
        )
        turn_row_ids[turn["turn_index"]] = int(cursor.lastrowid)

    fallback_turn_row_id = next(iter(turn_row_ids.values()), None)
    global_call_order = 0
    for tool_row in tool_rows:
        turn_row_id = turn_row_ids.get(tool_row["turn_index"], fallback_turn_row_id)
        if turn_row_id is None:
            cursor = conn.execute(
                """
                INSERT INTO turns(
                    session_id,
                    turn_index,
                    message_id,
                    timestamp,
                    model,
                    duration_ms,
                    input_tokens,
                    cached_input_tokens,
                    cache_write_tokens,
                    output_tokens,
                    total_tokens,
                    reasoning_item_count,
                    tool_use_block_count,
                    reasoning_output_tokens
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    summary.get("thread_id"),
                    1,
                    "synthetic-turn-1",
                    summary.get("start_timestamp"),
                    latest_turn_context.get("model"),
                    None,
                    0,
                    0,
                    None,
                    0,
                    0,
                    0,
                    tool_counts_by_turn.get(tool_row["turn_index"], 0),
                    0,
                ),
            )
            fallback_turn_row_id = int(cursor.lastrowid)
            turn_row_id = fallback_turn_row_id
            turn_row_ids[tool_row["turn_index"]] = turn_row_id
        global_call_order += 1
        cursor = conn.execute(
            """
            INSERT INTO tool_calls(
                turn_id,
                session_id,
                tool_name,
                file_path,
                command,
                is_error,
                error_text,
                call_type,
                call_id,
                call_order
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn_row_id,
                summary.get("thread_id"),
                tool_row["tool_name"],
                tool_row["file_path"],
                tool_row["command"],
                tool_row["is_error"],
                tool_row["error_text"],
                tool_row["call_type"],
                tool_row["call_id"],
                global_call_order,
            ),
        )
        tool_call_id = int(cursor.lastrowid)
        for file_path in tool_row["file_paths"]:
            conn.execute(
                """
                INSERT OR IGNORE INTO tool_call_files(tool_call_id, session_id, file_path)
                VALUES(?, ?, ?)
                """,
                (
                    tool_call_id,
                    summary.get("thread_id"),
                    file_path,
                ),
            )

    for token_event in token_event_rows:
        turn_row_id = turn_row_ids.get(token_event["turn_index"], fallback_turn_row_id)
        conn.execute(
            """
            INSERT INTO token_usage_events(
                session_id,
                turn_id,
                turn_index,
                timestamp,
                raw_model,
                model_provider,
                model_context_window,
                usage_source,
                is_approximate,
                input_tokens,
                cached_input_tokens,
                cache_write_tokens,
                output_tokens,
                reasoning_output_tokens,
                total_tokens,
                cumulative_input_tokens,
                cumulative_cached_input_tokens,
                cumulative_cache_write_tokens,
                cumulative_output_tokens,
                cumulative_reasoning_output_tokens,
                cumulative_total_tokens
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                summary.get("thread_id"),
                turn_row_id,
                token_event["turn_index"],
                token_event["timestamp"],
                token_event["raw_model"],
                token_event["model_provider"],
                token_event["model_context_window"],
                token_event["usage_source"],
                token_event["is_approximate"],
                token_event["input_tokens"],
                token_event["cached_input_tokens"],
                token_event["cache_write_tokens"],
                token_event["output_tokens"],
                token_event["reasoning_output_tokens"],
                token_event["total_tokens"],
                token_event["cumulative_input_tokens"],
                token_event["cumulative_cached_input_tokens"],
                token_event["cumulative_cache_write_tokens"],
                token_event["cumulative_output_tokens"],
                token_event["cumulative_reasoning_output_tokens"],
                token_event["cumulative_total_tokens"],
            ),
        )

    for reasoning_item in reasoning_items:
        turn_row_id = turn_row_ids.get(reasoning_item["turn_index"], fallback_turn_row_id)
        if turn_row_id is None:
            continue
        conn.execute(
            """
            INSERT INTO reasoning_items(
                turn_id,
                session_id,
                block_index,
                block_type,
                is_redacted,
                content_length,
                encrypted_content_length,
                summary_item_count,
                has_plaintext_content
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn_row_id,
                summary.get("thread_id"),
                reasoning_item["block_index"],
                reasoning_item["block_type"],
                reasoning_item["is_redacted"],
                reasoning_item["content_length"],
                reasoning_item["encrypted_content_length"],
                reasoning_item["summary_item_count"],
                reasoning_item["has_plaintext_content"],
            ),
        )

    for user_message in user_messages:
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
                summary.get("thread_id"),
                user_message["message_index"],
                user_message["timestamp"],
                1 if user_message["is_first"] else 0,
                1 if user_message["is_interrupt"] else 0,
                user_message["word_count"],
                user_message["char_count"],
                user_message["preceding_turn_index"],
            ),
        )

    for pr_link in summary.get("pr_links") or []:
        parsed_pr = parser.parse_github_pr(pr_link)
        conn.execute(
            "INSERT INTO pr_links(session_id, url, number, repository) VALUES(?, ?, ?, ?)",
            (
                summary.get("thread_id"),
                parsed_pr.get("url"),
                parsed_pr.get("number"),
                parsed_pr.get("repository"),
            ),
        )


def _extract_turn_and_token_rows(
    parser: Any,
    records: Sequence[dict[str, Any]],
    *,
    default_model: str | None,
    model_provider: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    turns: list[dict[str, Any]] = []
    token_rows: list[dict[str, Any]] = []
    current_index = 0
    current_model = default_model
    last_timestamp: str | None = None
    previous_total_usage: dict[str, int] | None = None
    for obj in records:
        record_type = obj.get("type")
        if record_type == "turn_context":
            payload = obj.get("payload")
            if not isinstance(payload, dict):
                continue
            current_index += 1
            timestamp = obj.get("timestamp")
            current_model = parser.string_or_none(payload.get("model")) or current_model
            turns.append(
                {
                    "turn_index": current_index,
                    "message_id": f"turn-{current_index}",
                    "timestamp": timestamp,
                    "model": current_model,
                    "duration_ms": None,
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "cache_write_tokens": 0,
                    "cache_write_tokens_known": True,
                    "has_token_usage": False,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "reasoning_item_count": 0,
                    "tool_use_block_count": 0,
                    "reasoning_output_tokens": 0,
                }
            )
            last_timestamp = timestamp if isinstance(timestamp, str) else last_timestamp
            continue
        if record_type != "event_msg":
            continue
        payload = obj.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        if not isinstance(info, dict):
            continue
        total_token_usage = info.get("total_token_usage")
        if not isinstance(total_token_usage, dict):
            continue
        timestamp = obj.get("timestamp")
        total_usage = _parse_token_usage(parser, total_token_usage)
        last_token_usage = info.get("last_token_usage")
        if isinstance(last_token_usage, dict):
            usage = _parse_token_usage(parser, last_token_usage)
            usage_source = "last_token_usage"
            is_approximate = 0
        elif previous_total_usage is not None:
            usage = _diff_token_usage(total_usage, previous_total_usage)
            usage_source = "total_token_usage_delta"
            is_approximate = 1
        else:
            usage = total_usage
            usage_source = "first_total_token_usage_snapshot"
            is_approximate = 1
        previous_total_usage = total_usage
        turn_row = _ensure_turn_row(
            turns,
            turn_index=max(current_index, 1),
            timestamp=timestamp if isinstance(timestamp, str) else last_timestamp,
            model=current_model,
        )
        turn_row["input_tokens"] += usage["input_tokens"]
        turn_row["cached_input_tokens"] += usage["cached_input_tokens"]
        turn_row["has_token_usage"] = True
        if usage["cache_write_tokens"] is None:
            turn_row["cache_write_tokens_known"] = False
        elif turn_row["cache_write_tokens_known"]:
            turn_row["cache_write_tokens"] += usage["cache_write_tokens"]
        turn_row["output_tokens"] += usage["output_tokens"]
        turn_row["total_tokens"] += usage["total_tokens"]
        turn_row["reasoning_output_tokens"] += usage["reasoning_output_tokens"]
        token_rows.append(
            {
                "turn_index": turn_row["turn_index"],
                "timestamp": timestamp,
                "raw_model": current_model,
                "model_provider": model_provider,
                "model_context_window": parser.int_or_none(info.get("model_context_window")),
                "usage_source": usage_source,
                "is_approximate": is_approximate,
                "input_tokens": usage["input_tokens"],
                "cached_input_tokens": usage["cached_input_tokens"],
                "cache_write_tokens": usage["cache_write_tokens"],
                "output_tokens": usage["output_tokens"],
                "reasoning_output_tokens": usage["reasoning_output_tokens"],
                "total_tokens": usage["total_tokens"],
                "cumulative_input_tokens": total_usage["input_tokens"],
                "cumulative_cached_input_tokens": total_usage["cached_input_tokens"],
                "cumulative_cache_write_tokens": total_usage["cache_write_tokens"],
                "cumulative_output_tokens": total_usage["output_tokens"],
                "cumulative_reasoning_output_tokens": total_usage["reasoning_output_tokens"],
                "cumulative_total_tokens": total_usage["total_tokens"],
            }
        )
    if not turns:
        turns.append(
            {
                "turn_index": 1,
                "message_id": "turn-1",
                "timestamp": last_timestamp,
                "model": current_model,
                "duration_ms": None,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "cache_write_tokens": 0,
                "cache_write_tokens_known": True,
                "has_token_usage": False,
                "output_tokens": 0,
                "total_tokens": 0,
                "reasoning_item_count": 0,
                "tool_use_block_count": 0,
                "reasoning_output_tokens": 0,
            }
        )
    for turn in turns:
        if not turn.pop("cache_write_tokens_known") or not turn.pop("has_token_usage"):
            turn["cache_write_tokens"] = None
    return turns, token_rows


def _infer_default_model(records: Sequence[dict[str, Any]], fallback_model: str | None) -> str | None:
    for obj in records:
        if obj.get("type") != "turn_context":
            continue
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue
        model = payload.get("model")
        if isinstance(model, str) and model:
            return model
    return fallback_model


def _ensure_turn_row(
    turns: list[dict[str, Any]],
    *,
    turn_index: int,
    timestamp: str | None,
    model: str | None,
) -> dict[str, Any]:
    while len(turns) < turn_index:
        synthetic_index = len(turns) + 1
        turns.append(
            {
                "turn_index": synthetic_index,
                "message_id": f"turn-{synthetic_index}",
                "timestamp": timestamp,
                "model": model,
                "duration_ms": None,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "cache_write_tokens": 0,
                "cache_write_tokens_known": True,
                "has_token_usage": False,
                "output_tokens": 0,
                "total_tokens": 0,
                "reasoning_item_count": 0,
                "tool_use_block_count": 0,
                "reasoning_output_tokens": 0,
            }
        )
    row = turns[turn_index - 1]
    if row["timestamp"] is None and timestamp is not None:
        row["timestamp"] = timestamp
    if row["model"] is None and model is not None:
        row["model"] = model
    return row


def _parse_token_usage(parser: Any, payload: dict[str, Any]) -> dict[str, int | None]:
    input_tokens = max(parser.int_or_none(payload.get("input_tokens")) or 0, 0)
    cached_input_tokens = max(parser.int_or_none(payload.get("cached_input_tokens")) or 0, 0)
    raw_cache_write_tokens = parser.int_or_none(payload.get("cache_write_tokens"))
    cache_write_tokens = (
        max(raw_cache_write_tokens, 0) if raw_cache_write_tokens is not None else None
    )
    output_tokens = max(parser.int_or_none(payload.get("output_tokens")) or 0, 0)
    reasoning_output_tokens = max(parser.int_or_none(payload.get("reasoning_output_tokens")) or 0, 0)
    total_tokens = max(
        parser.int_or_none(payload.get("total_tokens")) or 0,
        input_tokens + output_tokens,
    )
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": min(cached_input_tokens, input_tokens),
        "cache_write_tokens": (
            min(cache_write_tokens, input_tokens) if cache_write_tokens is not None else None
        ),
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning_output_tokens,
        "total_tokens": total_tokens,
    }


def _diff_token_usage(
    current: dict[str, int | None],
    previous: dict[str, int | None],
) -> dict[str, int | None]:
    current_cache_write = current["cache_write_tokens"]
    previous_cache_write = previous["cache_write_tokens"]
    return {
        "input_tokens": max(int(current["input_tokens"]) - int(previous["input_tokens"]), 0),
        "cached_input_tokens": max(
            int(current["cached_input_tokens"]) - int(previous["cached_input_tokens"]),
            0,
        ),
        "cache_write_tokens": (
            max(current_cache_write - previous_cache_write, 0)
            if current_cache_write is not None and previous_cache_write is not None
            else None
        ),
        "output_tokens": max(int(current["output_tokens"]) - int(previous["output_tokens"]), 0),
        "reasoning_output_tokens": max(
            int(current["reasoning_output_tokens"])
            - int(previous["reasoning_output_tokens"]),
            0,
        ),
        "total_tokens": max(int(current["total_tokens"]) - int(previous["total_tokens"]), 0),
    }


def _extract_tool_rows(parser: Any, records: Sequence[dict[str, Any]], turns: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_rows: list[dict[str, Any]] = []
    current_turn_index = 1
    pending: dict[str, dict[str, Any]] = {}
    for obj in records:
        record_type = obj.get("type")
        payload = obj.get("payload")
        if record_type == "turn_context":
            current_turn_index = min(current_turn_index + 1, max(turn["turn_index"] for turn in turns))
            continue
        if record_type != "response_item" or not isinstance(payload, dict):
            continue
        payload_type = parser.string_or_none(payload.get("type")) or "unknown"
        tool_name = parser.tool_name_from_payload(payload)
        if payload_type in parser.ALL_TOOL_CALL_TYPES:
            tool_row = {
                "turn_index": current_turn_index,
                "tool_name": tool_name,
                "file_path": _extract_file_path(payload),
                "file_paths": _extract_file_paths(payload),
                "command": _extract_command(payload),
                "is_error": 0,
                "error_text": None,
                "call_type": payload_type,
                "call_id": parser.string_or_none(payload.get("call_id")) or parser.string_or_none(payload.get("id")),
            }
            tool_rows.append(tool_row)
            call_id = tool_row["call_id"]
            if call_id:
                pending[call_id] = tool_row
            if payload_type in parser.DIRECT_STATUS_TOOL_CALL_TYPES:
                status = parser.string_or_none(payload.get("status"))
                if parser.is_error_status(status):
                    tool_row["is_error"] = 1
        elif payload_type in {
            parser.FUNCTION_CALL_OUTPUT_TYPE,
            parser.CUSTOM_TOOL_CALL_OUTPUT_TYPE,
            parser.TOOL_SEARCH_OUTPUT_TYPE,
        }:
            call_id = parser.string_or_none(payload.get("call_id"))
            target = pending.get(call_id) if call_id else None
            if target is None:
                continue
            if payload_type == parser.TOOL_SEARCH_OUTPUT_TYPE:
                success = parser.status_to_success_flag(parser.string_or_none(payload.get("status")))
                error_text = None if success is not False else "tool_search output failed"
            else:
                error_text, success = parser.call_output_content_and_success(payload.get("output"))
            if success is False:
                target["is_error"] = 1
                target["error_text"] = error_text
    return tool_rows


def _extract_command(payload: dict[str, Any]) -> str | None:
    action = payload.get("action")
    if isinstance(action, dict):
        command = action.get("command")
        normalized = _stringify_command(command)
        if normalized is not None:
            return normalized
        query = action.get("query")
        if isinstance(query, str):
            return query
    arguments = _payload_arguments_dict(payload)
    if arguments is not None:
        command = arguments.get("command")
        normalized = _stringify_command(command)
        if normalized is not None:
            return normalized
        cmd = arguments.get("cmd")
        normalized = _stringify_command(cmd)
        if normalized is not None:
            return normalized
        query = arguments.get("query")
        if isinstance(query, str):
            return query
    return None


def _extract_file_path(payload: dict[str, Any]) -> str | None:
    file_paths = _extract_file_paths(payload)
    if file_paths:
        return file_paths[0]
    return None


def _extract_file_paths(payload: dict[str, Any]) -> list[str]:
    if payload.get("type") == "custom_tool_call" and payload.get("name") == "apply_patch":
        return _extract_apply_patch_paths(payload)
    arguments = _payload_arguments_dict(payload)
    file_paths: list[str] = []
    if arguments is not None:
        for key in ("file_path", "path", "file"):
            value = arguments.get(key)
            if isinstance(value, str) and value:
                file_paths.append(value)
    action = payload.get("action")
    if isinstance(action, dict):
        file_path = action.get("file_path")
        if isinstance(file_path, str) and file_path:
            file_paths.append(file_path)
    return _dedupe_file_paths(file_paths)


def _payload_arguments_dict(payload: dict[str, Any]) -> dict[str, Any] | None:
    arguments = payload.get("arguments")
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            decoded = json.loads(arguments)
        except json.JSONDecodeError:
            return None
        if isinstance(decoded, dict):
            return decoded
    return None


def _stringify_command(value: Any) -> str | None:
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    if isinstance(value, str) and value:
        return value
    return None


def _extract_apply_patch_paths(payload: dict[str, Any]) -> list[str]:
    patch_text = payload.get("input")
    if not isinstance(patch_text, str):
        return []
    prefixes = (
        "*** Update File: ",
        "*** Add File: ",
        "*** Delete File: ",
        "*** Move to: ",
    )
    file_paths: list[str] = []
    for line in patch_text.splitlines():
        for prefix in prefixes:
            if line.startswith(prefix):
                candidate = line.removeprefix(prefix).strip()
                if candidate:
                    file_paths.append(candidate)
                break
    return _dedupe_file_paths(file_paths)


def _dedupe_file_paths(paths: Sequence[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path not in seen:
            seen.add(path)
            deduped.append(path)
    return deduped


def list_payload(
    codex_home: Path,
    *,
    archived: bool,
    project: str | None,
    since: date | None,
    limit: int,
    profile: str,
) -> list[dict[str, Any]]:
    with closing(DB.open_db(resolve_db_path(codex_home))) as conn:
        rows = _list_rollout_rows(conn, archived=archived, project=project, since=since, limit=limit)
        return [
            _row_to_ingestion_stub(row) if profile == "ingestion" else _row_to_descriptor(row)
            for row in rows
        ]


def summary_payload(codex_home: Path, session_id: str, *, profile: str) -> dict[str, Any] | None:
    with closing(DB.open_db(resolve_db_path(codex_home))) as conn:
        row = DB.session_row(conn, session_id)
        if row is None:
            return None
        summary = _row_to_summary(conn, row)
        if profile == "ingestion":
            parser = _load_parser()
            payload = parser.build_ingestion_summary(
                summary,
                parser.resolve_paths(codex_home),
                {},
                kind="session_summary",
            )
            payload["schema_version"] = "session_inspector_v2"
            return payload
        return summary


def subagents_payload(
    codex_home: Path,
    parent_session_id: str,
    *,
    profile: str,
    agent: str | None = None,
) -> list[dict[str, Any]] | None:
    with closing(DB.open_db(resolve_db_path(codex_home))) as conn:
        child_rows = _child_rows(conn, parent_session_id)
        if agent:
            child_rows = [row for row in child_rows if _matches_agent(row, agent)]
        payloads = [_child_row_to_summary(conn, row) for row in child_rows]
        if profile == "ingestion":
            parser = _load_parser()
            results = []
            for row in child_rows:
                payload = parser.build_ingestion_summary(
                    _row_to_summary(conn, row),
                    parser.resolve_paths(codex_home),
                    {},
                    kind="subagent_summary",
                )
                payload["schema_version"] = "session_inspector_v2"
                results.append(payload)
            return results
        return payloads


def _list_rollout_rows(
    conn: sqlite3.Connection,
    *,
    archived: bool,
    project: str | None,
    since: date | None,
    limit: int,
) -> list[sqlite3.Row]:
    clauses = ["is_subagent = 0", "archived = ?"]
    params: list[Any] = [1 if archived else 0]
    if project:
        like_value = f"%{project.lower()}%"
        clauses.append("(LOWER(COALESCE(project, '')) LIKE ? OR LOWER(COALESCE(cwd, '')) LIKE ?)")
        params.extend([like_value, like_value])
    if since is not None:
        clauses.append("DATE(start_timestamp) >= DATE(?)")
        params.append(since.isoformat())
    params.append(limit)
    return conn.execute(
        f"""
        SELECT *
        FROM sessions
        WHERE {' AND '.join(clauses)}
        ORDER BY COALESCE(start_timestamp, imported_at) DESC
        LIMIT ?
        """,
        params,
    ).fetchall()


def _row_to_descriptor(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "path": row["file_path"],
        "archived": bool(row["archived"]),
        "thread_id": row["session_id"],
        "filename_timestamp": row["filename_timestamp"],
        "thread_name": row["thread_name"],
        "title": row["title"],
        "cwd": row["cwd"],
        "project": row["project"],
        "first_user_message": row["first_user_message"],
        "raw_first_user_message": row["raw_first_user_message"],
        "delegated_task": row["delegated_task"],
        "model": row["model"],
        "forked_from_id": row["forked_from_id"],
        "parent_thread_id": row["parent_session_id"],
        "agent_nickname": row["agent_nickname"],
        "agent_role": row["agent_role"],
        "agent_path": (_json(row["current_subagent_json"]) or {}).get("agent_path"),
    }


def _row_to_ingestion_stub(row: sqlite3.Row) -> dict[str, Any]:
    current_subagent = _json(row["current_subagent_json"]) or {}
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
            "display_name": row["display_name"],
            "archived": bool(row["archived"]),
            "version": row["version"],
            "model_provider": row["model_provider"],
            "model": row["model"],
            "git_branch": row["git_branch"],
            "git_commit": row["git_commit"],
            "session_origin": None,
            "is_subagent": bool(row["is_subagent"]),
            "parent_session_id": row["parent_session_id"],
            "forked_from_session_id": row["forked_from_id"],
            "agent": {
                "nickname": row["agent_nickname"],
                "role": row["agent_role"],
                "path": current_subagent.get("agent_path"),
                "depth": current_subagent.get("depth"),
            }
            if row["is_subagent"]
            else None,
        },
        "content": {
            "first_user_message": row["first_user_message"],
            "raw_first_user_message": row["raw_first_user_message"],
            "delegated_task": row["delegated_task"],
        },
    }


def _row_to_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    tool_usage = _json(row["tool_usage_json"]) or {}
    current_subagent = _json(row["current_subagent_json"]) or None
    child_rollouts = [_child_row_to_summary(conn, child_row) for child_row in _child_rows(conn, row["session_id"])]
    return {
        "path": row["file_path"],
        "archived": bool(row["archived"]),
        "thread_id": row["session_id"],
        "thread_name": row["thread_name"],
        "title": row["title"],
        "filename_timestamp": row["filename_timestamp"],
        "cwd": row["cwd"],
        "project": row["project"],
        "is_subagent": bool(row["is_subagent"]),
        "first_user_message": row["first_user_message"],
        "raw_first_user_message": row["raw_first_user_message"],
        "delegated_task": row["delegated_task"],
        "parse_errors": int(row["parse_errors"] or 0),
        "record_count": int(row["record_count"] or 0),
        "record_counts": _json(row["record_counts_json"]) or {},
        "event_counts": _json(row["event_counts_json"]) or {},
        "response_item_counts": _json(row["response_item_counts_json"]) or {},
        "model_usage": _json(row["models_used"]) or [],
        "session_meta": _json(row["session_meta_json"]) or None,
        "git": _json(row["git_json"]) or None,
        "latest_turn_context": _json(row["latest_turn_context_json"]) or None,
        "token_usage": _json(row["token_usage_json"]) or {},
        "tool_usage": tool_usage,
        "tool_error_count": int(row["tool_error_count"] or 0),
        "tool_errors_by_name": (tool_usage.get("tool_errors_by_name") or {}),
        "turn_durations": _json(row["turn_durations_json"]) or {},
        "pr_links": [pr["url"] for pr in _load_prs(conn, row["session_id"])],
        "current_subagent": current_subagent,
        "subagents": {
            "count": len(child_rollouts),
            "children": child_rollouts,
        },
    }


def _child_row_to_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    tool_usage = _json(row["tool_usage_json"]) or {}
    token_usage = _json(row["token_usage_json"]) or {}
    current_subagent = _json(row["current_subagent_json"]) or {}
    latest_turn_context = _json(row["latest_turn_context_json"]) or {}
    return {
        "path": row["file_path"],
        "archived": bool(row["archived"]),
        "thread_id": row["session_id"],
        "thread_name": row["thread_name"],
        "title": row["title"],
        "first_user_message": row["first_user_message"],
        "raw_first_user_message": row["raw_first_user_message"],
        "delegated_task": row["delegated_task"],
        "project": row["project"],
        "cwd": row["cwd"],
        "model": latest_turn_context.get("model") or row["model"],
        "token_total": (token_usage.get("latest_total_token_usage") or {}).get("total_tokens"),
        "tool_calls": tool_usage.get("all_calls"),
        "top_tools": tool_usage.get("top_tools"),
        "tool_error_count": row["tool_error_count"],
        "tool_errors_by_name": tool_usage.get("tool_errors_by_name") or {},
        "agent_nickname": row["agent_nickname"],
        "agent_role": row["agent_role"],
        "agent_path": current_subagent.get("agent_path"),
        "parent_thread_id": row["parent_session_id"],
    }


def _child_rows(conn: sqlite3.Connection, parent_session_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT sessions.*
        FROM subagent_links
        JOIN sessions ON sessions.session_id = subagent_links.child_session_id
        WHERE subagent_links.parent_session_id = ?
        ORDER BY COALESCE(sessions.start_timestamp, sessions.imported_at), sessions.file_path
        """,
        (parent_session_id,),
    ).fetchall()


def _load_prs(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT url, number, repository FROM pr_links WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [
        {"url": row["url"], "number": row["number"], "repository": row["repository"]}
        for row in rows
    ]


def _matches_agent(row: sqlite3.Row, agent: str) -> bool:
    agent_lower = agent.lower()
    values = [
        row["agent_nickname"],
        row["agent_role"],
        row["session_id"],
        row["thread_name"],
    ]
    return any(isinstance(value, str) and agent_lower in value.lower() for value in values)


def _json(value: Any) -> Any:
    return DB.json_loads(value)
