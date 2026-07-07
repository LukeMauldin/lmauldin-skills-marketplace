from __future__ import annotations

import importlib.util
import json
import re
import sqlite3
import sys
from collections import Counter
from collections.abc import Sequence
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PARSER_VERSION = 2
BATCH_SIZE = 50
SOURCE = "cursor"
GITHUB_PR_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+")


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
UI = _load_module("cursor_session_inspector_ui_store_reader", "ui_store_reader.py")
CLI = _load_module("cursor_session_inspector_cli_blob_walker", "cli_blob_walker.py")
TRANSCRIPTS = _load_module("cursor_session_inspector_transcript_reader", "transcript_reader.py")
AI = _load_module("cursor_session_inspector_ai_tracking", "ai_tracking.py")


def resolve_db_path(cursor_home: Path) -> Path:
    return DB.default_db_path(cursor_home.expanduser())


def reconcile_pending(cursor_home: Path, *, app_support: Path | None = None) -> list[str]:
    db_path = resolve_db_path(cursor_home)
    now = datetime.now(UTC)

    def handler(payload: dict[str, Any]) -> bool:
        if not DB.is_retryable_pending_marker(payload):
            return False
        not_before = DB.parse_marker_timestamp(payload.get("not_before"))
        if not_before is not None and not_before > now:
            return False
        target = payload.get("target") or payload.get("session_id")
        if not isinstance(target, str) or not target:
            return False
        try:
            refresh_sessions(
                cursor_home,
                app_support=app_support,
                target=target,
                reconcile=False,
                analyze=False,
            )
            return True
        except Exception:
            return False

    return DB.reconcile_pending_markers(db_path, handler)


def refresh_sessions(
    cursor_home: Path,
    *,
    app_support: Path | None = None,
    target: str | None = None,
    project: str | None = None,
    since: date | None = None,
    reconcile: bool = True,
    analyze: bool = True,
) -> dict[str, Any]:
    cursor_home = cursor_home.expanduser()
    app_support = (app_support or default_app_support_path()).expanduser()
    db_path = resolve_db_path(cursor_home)
    reconciled_pending: list[str] = []
    if reconcile:
        reconciled_pending = reconcile_pending(cursor_home, app_support=app_support)

    counts: dict[str, Any] = {
        "imported": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
        "ui_composers": {"imported": 0, "skipped": 0, "failed": 0},
        "cli_agents": {"imported": 0, "skipped": 0, "failed": 0},
        "transcripts": {"imported": 0, "skipped": 0, "failed": 0},
        "ai_tracking": {"imported": 0, "skipped": 0, "failed": 0},
        "hook_token_events": {"imported": 0, "skipped": 0, "failed": 0},
    }
    with closing(DB.open_db(db_path)) as conn:
        state_db_path = app_support / "User" / "globalStorage" / "state.vscdb"
        if state_db_path.exists():
            _merge_counts(
                counts,
                "ui_composers",
                _import_ui_composers(conn, state_db_path, target=target, project=project, since=since),
            )
        _commit_maybe(conn)

        _merge_counts(
            counts,
            "cli_agents",
            _import_cli_agents(conn, cursor_home, target=target, project=project, since=since),
        )
        _commit_maybe(conn)

        _merge_counts(
            counts,
            "transcripts",
            _import_transcripts(conn, cursor_home, target=target, project=project, since=since),
        )
        _commit_maybe(conn)

        _merge_counts(
            counts,
            "ai_tracking",
            _import_ai_tracking(conn, cursor_home),
        )
        _commit_maybe(conn)

        _merge_counts(
            counts,
            "hook_token_events",
            _import_hook_token_captures(conn, cursor_home),
        )
        if analyze and counts["imported"] > 0:
            conn.execute("ANALYZE")
        conn.commit()

    counts["db_path"] = str(db_path)
    counts["reconciled_pending"] = reconciled_pending
    counts["reconciled_pending_count"] = len(reconciled_pending)
    return counts


def rebuild_sessions(
    cursor_home: Path,
    *,
    app_support: Path | None = None,
    project: str | None = None,
    since: date | None = None,
) -> dict[str, Any]:
    db_path = resolve_db_path(cursor_home.expanduser())
    DB.remove_db_files(db_path)
    return refresh_sessions(
        cursor_home,
        app_support=app_support,
        project=project,
        since=since,
        reconcile=False,
        analyze=True,
    )


def default_app_support_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "Cursor"


def list_payload(
    cursor_home: Path,
    *,
    source_type: str | None,
    workspace: str | None,
    project: str | None,
    since: date | None,
    limit: int,
    profile: str,
) -> list[dict[str, Any]]:
    with closing(DB.open_db(resolve_db_path(cursor_home))) as conn:
        rows = _list_rows(
            conn,
            source_type=source_type,
            workspace=workspace,
            project=project,
            since=since,
            limit=limit,
            include_subagents=False,
        )
        return [
            _row_to_ingestion_stub(row) if profile == "ingestion" else _row_to_descriptor(row)
            for row in rows
        ]


def summary_payload(cursor_home: Path, target: str | None, *, profile: str) -> dict[str, Any] | None:
    with closing(DB.open_db(resolve_db_path(cursor_home))) as conn:
        session_id = resolve_session_id(conn, target)
        if session_id is None:
            return None
        row = DB.session_row(conn, session_id)
        if row is None:
            return None
        summary = _row_to_summary(conn, row)
        if profile == "ingestion":
            return _summary_to_ingestion(summary, kind="session_summary")
        return summary


def subagents_payload(
    cursor_home: Path,
    target: str | None,
    *,
    profile: str,
    agent: str | None = None,
) -> list[dict[str, Any]] | None:
    with closing(DB.open_db(resolve_db_path(cursor_home))) as conn:
        parent_session_id = resolve_session_id_with_children(conn, target)
        if parent_session_id is None:
            return None
        rows = conn.execute(
            """
            SELECT
              sal.*,
              s.session_id AS child_row_session_id,
              s.title AS child_title,
              s.display_name AS child_display_name,
              s.model AS child_model,
              s.first_user_message AS child_first_user_message,
              s.turn_count AS child_turn_count,
              s.total_tokens AS child_total_tokens,
              COALESCE(hte.event_count, 0) AS child_hook_event_count,
              COALESCE(hte.input_tokens, 0) AS child_hook_input_tokens,
              COALESCE(hte.output_tokens, 0) AS child_hook_output_tokens,
              COALESCE(hte.cache_read_tokens, 0) AS child_hook_cache_read_tokens,
              COALESCE(hte.cache_write_tokens, 0) AS child_hook_cache_write_tokens,
              s.agent_backend AS child_agent_backend,
              s.source_type AS child_source_type
            FROM subagent_links sal
            LEFT JOIN sessions s ON s.session_id = sal.child_session_id
            LEFT JOIN (
              SELECT
                session_id,
                COUNT(*) AS event_count,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens
              FROM hook_token_events
              GROUP BY session_id
            ) hte ON hte.session_id = sal.child_session_id
            WHERE sal.parent_session_id = ?
            ORDER BY COALESCE(s.last_updated_at, s.start_timestamp, s.imported_at) DESC
            """,
            (parent_session_id,),
        ).fetchall()
        payloads = [_subagent_row_to_payload(row) for row in rows]
        if agent:
            agent_lower = agent.lower()
            payloads = [
                item
                for item in payloads
                if agent_lower in json.dumps(item, sort_keys=True).lower()
            ]
        if profile == "ingestion":
            return [
                {
                    "schema_version": "session_inspector_v2",
                    "source": SOURCE,
                    "kind": "subagent_summary",
                    "session": item,
                    "content": {
                        "first_user_message": item.get("first_user_message"),
                        "delegated_task": item.get("first_task"),
                    },
                }
                for item in payloads
            ]
        return payloads


def resolve_session_id(conn: sqlite3.Connection, target: str | None) -> str | None:
    if target is None:
        return DB.latest_session_id(conn)
    exact = conn.execute(
        "SELECT session_id FROM sessions WHERE session_id = ? LIMIT 1",
        (target,),
    ).fetchone()
    if exact:
        return str(exact["session_id"])
    if target.startswith("cli:"):
        return None
    like_value = f"%{target}%"
    row = conn.execute(
        """
        SELECT session_id
        FROM sessions
        WHERE session_id LIKE ?
           OR title LIKE ?
           OR display_name LIKE ?
           OR file_path LIKE ?
        ORDER BY COALESCE(last_updated_at, start_timestamp, imported_at) DESC
        LIMIT 1
        """,
        (like_value, like_value, like_value, like_value),
    ).fetchone()
    return str(row["session_id"]) if row else None


def resolve_session_id_with_children(conn: sqlite3.Connection, target: str | None) -> str | None:
    if target is not None:
        return resolve_session_id(conn, target)
    row = conn.execute(
        """
        SELECT parent_session_id AS session_id
        FROM subagent_links
        GROUP BY parent_session_id
        ORDER BY MAX(id) DESC
        LIMIT 1
        """
    ).fetchone()
    if row:
        return str(row["session_id"])
    return DB.latest_session_id(conn)


def _import_ui_composers(
    conn: sqlite3.Connection,
    state_db_path: Path,
    *,
    target: str | None,
    project: str | None,
    since: date | None,
) -> dict[str, Any]:
    counts = _counts()
    snapshot_path: Path | None = None
    try:
        snapshot_path = UI.snapshot_state_vscdb(state_db_path)
        composers = list(UI.list_composers(snapshot_path))
        for start in range(0, len(composers), BATCH_SIZE):
            for composer in composers[start : start + BATCH_SIZE]:
                try:
                    if not _matches_ui_filters(composer, target=target, project=project, since=since):
                        continue
                    result = _import_ui_composer(conn, snapshot_path, state_db_path, composer)
                except Exception as exc:
                    counts["failed"] += 1
                    counts["errors"].append({"session_id": composer.composer_id, "error": str(exc)})
                    continue
                counts[result] += 1
            conn.commit()
        _import_plans(conn, snapshot_path)
    finally:
        if snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)
    return counts


def _import_ui_composer(
    conn: sqlite3.Connection,
    snapshot_path: Path,
    state_db_path: Path,
    composer: Any,
) -> str:
    last_updated_ms = _int(composer.payload.get("lastUpdatedAt")) or _int(
        (composer.header or {}).get("lastUpdatedAt")
    ) or 0
    raw_session_json = DB.json_dumps(composer.payload) or "{}"
    source_key = f"ui_composer:{composer.composer_id}"
    if DB.should_skip_stats(
        conn,
        source_key,
        mtime_ns=last_updated_ms * 1_000_000,
        size_bytes=len(raw_session_json),
        parser_version=PARSER_VERSION,
    ):
        return "skipped"

    bubbles: list[tuple[dict[str, Any], Any | None]] = list(UI.iter_bubbles(snapshot_path, composer))
    DB.delete_session(conn, composer.composer_id)
    session_row = _ui_session_row(composer, bubbles, state_db_path)
    _insert_row(conn, "sessions", session_row)

    turn_row_ids: dict[int, int] = {}
    user_message_index = 0
    assistant_turn_index = 0
    global_tool_order = 0
    for header, bubble in bubbles:
        payload = bubble.payload if bubble is not None else {}
        bubble_type = _int(payload.get("type")) or _int(header.get("type"))
        if bubble_type == 1:
            user_message_index += 1
            text = _text_from_bubble(payload)
            _insert_row(
                conn,
                "user_messages",
                {
                    "session_id": composer.composer_id,
                    "message_index": user_message_index,
                    "timestamp": _ms_to_iso(_int(payload.get("createdAt"))),
                    "text": text,
                    "word_count": len((text or "").split()),
                    "char_count": len(text or ""),
                    "raw_json": DB.json_dumps(payload),
                },
            )
        elif bubble_type == 2:
            assistant_turn_index += 1
            turn_id = _insert_ui_turn(conn, composer.composer_id, assistant_turn_index, header, payload)
            turn_row_ids[assistant_turn_index] = turn_id
            for block_index, block in enumerate(_list(payload.get("allThinkingBlocks")), start=1):
                block_text = _text_from_any(block)
                _insert_row(
                    conn,
                    "thinking_blocks",
                    {
                        "turn_id": turn_id,
                        "session_id": composer.composer_id,
                        "block_index": block_index,
                        "text": block_text,
                        "duration_ms": _int(block.get("durationMs")) if isinstance(block, dict) else None,
                        "raw_json": DB.json_dumps(block),
                    },
                )
            for tool_result in _list(payload.get("toolResults")):
                global_tool_order += 1
                _insert_ui_tool_call(
                    conn,
                    composer.composer_id,
                    turn_id,
                    tool_result,
                    call_order=global_tool_order,
                )
            # Cursor Composer records each tool invocation as a single
            # ``toolFormerData`` dict on its own bubble (not in ``toolResults``),
            # so extract those too or the run looks like it made zero tool calls.
            tool_former = payload.get("toolFormerData")
            if isinstance(tool_former, dict) and tool_former:
                global_tool_order += 1
                _insert_ui_tool_former_call(
                    conn,
                    composer.composer_id,
                    turn_id,
                    tool_former,
                    call_order=global_tool_order,
                )
    _insert_pr_links(conn, composer.composer_id, [composer.payload, *[bubble.payload for _, bubble in bubbles if bubble]])
    for child_session_id in _string_list(composer.payload.get("subagentComposerIds")):
        conn.execute(
            """
            INSERT OR IGNORE INTO subagent_links(
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
                composer.composer_id,
                child_session_id,
                None,
                None,
                None,
                None,
            ),
        )
    DB.record_import_stats(
        conn,
        source_key,
        mtime_ns=last_updated_ms * 1_000_000,
        size_bytes=len(raw_session_json),
        session_id=composer.composer_id,
        parser_version=PARSER_VERSION,
        record_count=len(bubbles),
    )
    return "imported"


def _import_cli_agents(
    conn: sqlite3.Connection,
    cursor_home: Path,
    *,
    target: str | None,
    project: str | None,
    since: date | None,
) -> dict[str, Any]:
    counts = _counts()
    agents = CLI.list_cli_agents(cursor_home)
    for start in range(0, len(agents), BATCH_SIZE):
        for agent in agents[start : start + BATCH_SIZE]:
            try:
                if not _matches_cli_filters(agent, target=target, project=project, since=since):
                    continue
                result = _import_cli_agent(conn, agent)
            except Exception as exc:
                counts["failed"] += 1
                counts["errors"].append({"session_id": agent.session_id, "error": str(exc)})
                continue
            counts[result] += 1
        conn.commit()
    return counts


def _import_cli_agent(conn: sqlite3.Connection, agent: Any) -> str:
    if DB.should_skip(conn, agent.store_db_path, PARSER_VERSION):
        return "skipped"
    messages = CLI.walk_messages(agent.store_db_path, root_blob_id=agent.latest_root_blob_id)
    DB.delete_session(conn, agent.session_id)
    first_user = _first_cli_user_message(messages)
    assistant_messages = [message for message in messages if message.role == "assistant"]
    user_messages = [message for message in messages if message.role == "user"]
    raw_json = DB.json_dumps(agent.meta)
    _insert_row(
        conn,
        "sessions",
        {
            "session_id": agent.session_id,
            "source": SOURCE,
            "source_type": "cli_agent",
            "file_path": str(agent.store_db_path),
            "workspace": agent.workspace_hash,
            "project": None,
            "cwd": None,
            "title": agent.name or first_user,
            "display_name": agent.name or agent.agent_id,
            "model": agent.last_used_model,
            "first_user_message": _preview(first_user),
            "raw_first_user_message": first_user,
            "delegated_task": None,
            "start_timestamp": _ms_to_iso(agent.created_at),
            "last_updated_at": _mtime_iso(agent.store_db_path),
            "is_subagent": 0,
            "parent_session_id": None,
            "record_count": len(messages),
            "parse_errors": 0,
            "turn_count": len(assistant_messages),
            "completed_turn_count": len(assistant_messages),
            "user_message_count": len(user_messages),
            "tool_call_count": _cli_tool_call_count(messages),
            "tool_error_count": 0,
            "thinking_block_count": 0,
            "total_turn_duration_ms": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_tokens": 0,
            "models_used": DB.json_dumps([agent.last_used_model] if agent.last_used_model else []),
            "unified_mode": agent.mode,
            "force_mode": None,
            "agent_backend": "cursor-agent",
            "raw_json": raw_json,
        },
    )
    user_index = 0
    turn_index = 0
    for message in messages:
        if message.role == "user":
            user_index += 1
            _insert_row(
                conn,
                "user_messages",
                {
                    "session_id": agent.session_id,
                    "message_index": user_index,
                    "timestamp": None,
                    "text": message.content,
                    "word_count": len((message.content or "").split()),
                    "char_count": len(message.content or ""),
                    "raw_json": DB.json_dumps(message.payload) if message.payload else message.raw_text,
                },
            )
        elif message.role == "assistant":
            turn_index += 1
            cursor = _insert_row(
                conn,
                "turns",
                {
                    "session_id": agent.session_id,
                    "turn_index": turn_index,
                    "bubble_id": message.blob_id,
                    "message_id": message.blob_id,
                    "role": message.role,
                    "timestamp": None,
                    "text": message.content,
                    "model": agent.last_used_model,
                    "raw_json": DB.json_dumps(message.payload) if message.payload else message.raw_text,
                },
            )
            _insert_cli_tool_calls(conn, agent.session_id, int(cursor.lastrowid), message)
    DB.record_import(conn, agent.store_db_path, session_id=agent.session_id, parser_version=PARSER_VERSION, record_count=len(messages))
    return "imported"


def _import_transcripts(
    conn: sqlite3.Connection,
    cursor_home: Path,
    *,
    target: str | None,
    project: str | None,
    since: date | None,
) -> dict[str, Any]:
    counts = _counts()
    for transcript in TRANSCRIPTS.iter_transcripts(cursor_home, include_subagents=True):
        try:
            if not _matches_transcript_filters(transcript, target=target, project=project, since=since):
                continue
            if DB.session_exists(conn, transcript.session_id):
                counts["skipped"] += 1
                continue
            if DB.should_skip(conn, transcript.path, PARSER_VERSION):
                counts["skipped"] += 1
                continue
            records, parse_errors = TRANSCRIPTS.load_records(transcript.path)
            _insert_transcript_session(conn, transcript, records, parse_errors)
            DB.record_import(
                conn,
                transcript.path,
                session_id=transcript.session_id,
                parser_version=PARSER_VERSION,
                record_count=len(records),
            )
        except Exception as exc:
            counts["failed"] += 1
            counts["errors"].append({"path": str(transcript.path), "error": str(exc)})
            continue
        counts["imported"] += 1
    return counts


def _import_ai_tracking(conn: sqlite3.Connection, cursor_home: Path) -> dict[str, Any]:
    counts = _counts()
    source_db = cursor_home.expanduser() / "ai-tracking" / "ai-code-tracking.db"
    if not source_db.exists():
        counts["skipped"] += 1
        return counts
    snapshot_path: Path | None = None
    try:
        snapshot_path = AI.snapshot_ai_tracking_db(source_db)
        conn.execute("DELETE FROM ai_code_chunks")
        conn.execute("DELETE FROM commit_scores")
        conn.execute("DELETE FROM conversation_summaries")
        chunk_count = 0
        for chunk in AI.iter_ai_code_chunks(snapshot_path):
            _insert_row(conn, "ai_code_chunks", chunk, or_replace=True)
            chunk_count += 1
        commit_count = 0
        for score in AI.iter_commit_scores(snapshot_path):
            _insert_row(conn, "commit_scores", score, or_replace=True)
            commit_count += 1
        summary_count = 0
        for summary in AI.iter_conversation_summaries(snapshot_path):
            _insert_row(conn, "conversation_summaries", summary, or_replace=True)
            summary_count += 1
        _update_ai_session_counts(conn)
        counts["imported"] = chunk_count + commit_count + summary_count
        counts["record_count"] = counts["imported"]
    except Exception as exc:
        counts["failed"] += 1
        counts["errors"].append({"path": str(source_db), "error": str(exc)})
    finally:
        if snapshot_path is not None:
            snapshot_path.unlink(missing_ok=True)
    return counts


def _import_hook_token_captures(conn: sqlite3.Connection, cursor_home: Path) -> dict[str, Any]:
    counts = _counts()
    capture_dir = cursor_home.expanduser() / "inspector" / "payload-captures"
    if not capture_dir.exists():
        counts["skipped"] += 1
        return counts
    for capture_path in sorted(capture_dir.glob("*.json")):
        try:
            payload = json.loads(capture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            counts["failed"] += 1
            counts["errors"].append({"path": str(capture_path), "error": str(exc)})
            continue
        if not isinstance(payload, dict):
            counts["skipped"] += 1
            continue
        event = DB.hook_token_event_from_payload(
            payload,
            received_at=_mtime_iso(capture_path),
            raw_payload_path=str(capture_path),
        )
        if event is None:
            counts["skipped"] += 1
            continue
        DB.record_hook_token_event(conn, event)
        counts["imported"] += 1
    return counts


def _insert_transcript_session(
    conn: sqlite3.Connection,
    transcript: Any,
    records: list[dict[str, Any]],
    parse_errors: int,
) -> None:
    first_user = TRANSCRIPTS.first_user_message(records)
    assistant_records = [record for record in records if record.get("role") == "assistant"]
    user_records = [record for record in records if record.get("role") == "user"]
    DB.delete_session(conn, transcript.session_id)
    _insert_row(
        conn,
        "sessions",
        {
            "session_id": transcript.session_id,
            "source": SOURCE,
            "source_type": "transcript_only",
            "file_path": str(transcript.path),
            "workspace": transcript.project_slug,
            "project": transcript.project_slug,
            "cwd": None,
            "title": _preview(first_user) or transcript.session_id,
            "display_name": _preview(first_user) or transcript.session_id,
            "model": None,
            "first_user_message": _preview(first_user),
            "raw_first_user_message": first_user,
            "delegated_task": first_user if transcript.is_subagent else None,
            "start_timestamp": _mtime_iso(transcript.path),
            "last_updated_at": _mtime_iso(transcript.path),
            "is_subagent": 1 if transcript.is_subagent else 0,
            "parent_session_id": transcript.parent_session_id,
            "record_count": len(records),
            "parse_errors": parse_errors,
            "turn_count": len(assistant_records),
            "completed_turn_count": len(assistant_records),
            "user_message_count": len(user_records),
            "tool_call_count": _transcript_tool_count(records),
            "raw_json": DB.json_dumps({"project_slug": transcript.project_slug}),
        },
    )
    if transcript.is_subagent and transcript.parent_session_id:
        conn.execute(
            """
            INSERT OR IGNORE INTO subagent_links(parent_session_id, child_session_id, first_task)
            VALUES(?, ?, ?)
            """,
            (transcript.parent_session_id, transcript.session_id, first_user),
        )
    user_index = 0
    turn_index = 0
    tool_order = 0
    for record in records:
        text = TRANSCRIPTS.message_text(record.get("message"))
        if record.get("role") == "user":
            user_index += 1
            _insert_row(
                conn,
                "user_messages",
                {
                    "session_id": transcript.session_id,
                    "message_index": user_index,
                    "text": text,
                    "word_count": len((text or "").split()),
                    "char_count": len(text or ""),
                    "raw_json": DB.json_dumps(record),
                },
            )
        elif record.get("role") == "assistant":
            turn_index += 1
            cursor = _insert_row(
                conn,
                "turns",
                {
                    "session_id": transcript.session_id,
                    "turn_index": turn_index,
                    "role": "assistant",
                    "text": text,
                    "raw_json": DB.json_dumps(record),
                },
            )
            turn_id = int(cursor.lastrowid)
            for block in _transcript_tool_blocks(record):
                tool_order += 1
                _insert_row(
                    conn,
                    "tool_calls",
                    {
                        "turn_id": turn_id,
                        "session_id": transcript.session_id,
                        "tool_name": _string(block.get("name")) or "tool_use",
                        "call_order": tool_order,
                        "raw_json": DB.json_dumps(block),
                    },
                )


def _ui_session_row(
    composer: Any,
    bubbles: list[tuple[dict[str, Any], Any | None]],
    state_db_path: Path,
) -> dict[str, Any]:
    payload = composer.payload
    header = composer.header or {}
    workspace_identifier = _dict(payload.get("workspaceIdentifier"))
    model_config = _dict(payload.get("modelConfig"))
    tracked_repo = _first_dict(payload.get("trackedGitRepos"))
    branches = _list(tracked_repo.get("branches") if tracked_repo else None)
    bubble_payloads = [bubble.payload for _, bubble in bubbles if bubble is not None]
    first_user = _first_ui_user_message(bubble_payloads)
    assistant_bubbles = [item for item in bubble_payloads if _int(item.get("type")) == 2]
    user_bubbles = [item for item in bubble_payloads if _int(item.get("type")) == 1]
    token_input = sum(_nested_int(item, "tokenCount", "inputTokens") or 0 for item in bubble_payloads)
    token_output = sum(_nested_int(item, "tokenCount", "outputTokens") or 0 for item in bubble_payloads)
    usage_tokens = _usage_total_tokens(payload.get("usageData"))
    bubble_versions = [_int(item.get("_v")) for item in bubble_payloads if _int(item.get("_v")) is not None]
    subagent_ids = _string_list(payload.get("subagentComposerIds"))
    return {
        "session_id": composer.composer_id,
        "source": SOURCE,
        "source_type": "ui_composer",
        "file_path": str(state_db_path),
        "workspace": _string(workspace_identifier.get("id")),
        "project": _project_from_path(_string(workspace_identifier.get("uri", {}).get("fsPath")) if isinstance(workspace_identifier.get("uri"), dict) else _string(workspace_identifier.get("fsPath"))),
        "cwd": _string(workspace_identifier.get("uri", {}).get("fsPath")) if isinstance(workspace_identifier.get("uri"), dict) else _string(workspace_identifier.get("fsPath")),
        "title": _string(payload.get("name")) or _string(header.get("name")) or _preview(first_user),
        "display_name": _string(payload.get("name")) or _string(header.get("name")) or composer.composer_id,
        "model": _string(model_config.get("modelName")),
        "first_user_message": _preview(first_user),
        "raw_first_user_message": first_user,
        "delegated_task": None,
        "start_timestamp": _ms_to_iso(_int(payload.get("createdAt")) or _int(header.get("createdAt"))),
        "last_updated_at": _ms_to_iso(_int(payload.get("lastUpdatedAt")) or _int(header.get("lastUpdatedAt"))),
        "is_subagent": 1 if _bool(payload.get("isBestOfNSubcomposer")) else 0,
        "parent_session_id": None,
        "record_count": len(bubble_payloads),
        "parse_errors": len([1 for _, bubble in bubbles if bubble is None]),
        "turn_count": len(assistant_bubbles),
        "completed_turn_count": len(assistant_bubbles),
        "user_message_count": len(user_bubbles),
        "tool_call_count": (
            sum(len(_list(item.get("toolResults"))) for item in bubble_payloads)
            + sum(1 for item in bubble_payloads if isinstance(item.get("toolFormerData"), dict) and item.get("toolFormerData"))
        ),
        "tool_error_count": (
            sum(_tool_result_is_error(tool) for item in bubble_payloads for tool in _list(item.get("toolResults")))
            + sum(
                _tool_former_is_error(item["toolFormerData"])
                for item in bubble_payloads
                if isinstance(item.get("toolFormerData"), dict) and item.get("toolFormerData")
            )
        ),
        "thinking_block_count": sum(len(_list(item.get("allThinkingBlocks"))) for item in bubble_payloads),
        "total_turn_duration_ms": sum(_nested_int(header, "grouping", "turnDurationMs") or 0 for header, _ in bubbles),
        "total_input_tokens": max(token_input, usage_tokens.get("input", 0)),
        "total_output_tokens": max(token_output, usage_tokens.get("output", 0)),
        "total_tokens": max(token_input + token_output, usage_tokens.get("total", 0)),
        "models_used": DB.json_dumps(_dedupe(_string_list(model_config.get("selectedModels")) + [_string(model_config.get("modelName"))])),
        "unified_mode": _string(payload.get("unifiedMode")),
        "force_mode": _string(payload.get("forceMode")),
        "agent_backend": _string(payload.get("agentBackend")),
        "is_worktree": 1 if _bool(payload.get("isWorktree")) else 0,
        "is_draft": 1 if _bool(payload.get("isDraft")) else 0,
        "is_archived": 1 if _bool(payload.get("isArchived")) else 0,
        "is_best_of_n_parent": 1 if _bool(payload.get("isBestOfNParent")) else 0,
        "is_best_of_n_subcomposer": 1 if _bool(payload.get("isBestOfNSubcomposer")) else 0,
        "context_tokens_used": _int(payload.get("contextTokensUsed")),
        "context_token_limit": _int(payload.get("contextTokenLimit")),
        "context_usage_percent": _float(payload.get("contextUsagePercent")),
        "tracked_repo_path": _string(tracked_repo.get("repoPath")) if tracked_repo else None,
        "tracked_branch": _branch_name(payload.get("activeBranch")) or _branch_name(branches[0] if branches else None),
        "committed_to_branch": _string(payload.get("committedToBranch")),
        "stop_hook_loop_count": _int(payload.get("stopHookLoopCount")),
        "workspace_identifier_id": _string(workspace_identifier.get("id")),
        "workspace_identifier_fs_path": _string(workspace_identifier.get("uri", {}).get("fsPath")) if isinstance(workspace_identifier.get("uri"), dict) else _string(workspace_identifier.get("fsPath")),
        "composer_row_v": _int(payload.get("_v")),
        "bubble_row_v": max(bubble_versions) if bubble_versions else None,
        "usage_data_json": DB.json_dumps(payload.get("usageData")),
        "model_config_json": DB.json_dumps(model_config),
        "workspace_identifier_json": DB.json_dumps(workspace_identifier),
        "raw_json": DB.json_dumps({**payload, "subagentComposerIds": subagent_ids}),
    }


def _insert_ui_turn(
    conn: sqlite3.Connection,
    session_id: str,
    turn_index: int,
    header: dict[str, Any],
    payload: dict[str, Any],
) -> int:
    grouping = _dict(header.get("grouping"))
    cursor = _insert_row(
        conn,
        "turns",
        {
            "session_id": session_id,
            "turn_index": turn_index,
            "bubble_id": _string(payload.get("bubbleId")) or _string(header.get("bubbleId")),
            "message_id": _string(payload.get("bubbleId")) or _string(header.get("bubbleId")),
            "role": "assistant",
            "timestamp": _ms_to_iso(_int(payload.get("createdAt"))),
            "text": _text_from_bubble(payload),
            "model": _nested_string(payload, "modelInfo", "name") or _nested_string(payload, "modelInfo", "modelName"),
            "request_id": _string(payload.get("requestId")),
            "tool_call_id": _string(grouping.get("toolCallId")),
            "turn_duration_ms": _int(grouping.get("turnDurationMs")),
            "thinking_duration_ms": _int(grouping.get("thinkingDurationMs")),
            "capability_type": _int(grouping.get("capabilityType")),
            "is_renderable": 1 if _bool(grouping.get("isRenderable")) else 0,
            "is_plan_execution": 1 if _bool(payload.get("isPlanExecution")) else 0,
            "bubble_token_input": _nested_int(payload, "tokenCount", "inputTokens") or 0,
            "bubble_token_output": _nested_int(payload, "tokenCount", "outputTokens") or 0,
            "raw_json": DB.json_dumps(payload),
        },
    )
    return int(cursor.lastrowid)


def _insert_ui_tool_call(
    conn: sqlite3.Connection,
    session_id: str,
    turn_id: int,
    tool_result: Any,
    *,
    call_order: int,
) -> None:
    payload = tool_result if isinstance(tool_result, dict) else {"value": tool_result}
    _insert_row(
        conn,
        "tool_calls",
        {
            "turn_id": turn_id,
            "session_id": session_id,
            "tool_name": _tool_name(payload),
            "file_path": _tool_file_path(payload),
            "command": _tool_command(payload),
            "is_error": _tool_result_is_error(payload),
            "error_text": _tool_error_text(payload),
            "call_id": _string(payload.get("toolCallId")) or _string(payload.get("callId")) or _string(payload.get("id")),
            "call_order": call_order,
            "raw_json": DB.json_dumps(payload),
        },
    )


def _insert_cli_tool_calls(conn: sqlite3.Connection, session_id: str, turn_id: int, message: Any) -> None:
    if not isinstance(message.payload, dict):
        return
    content = message.payload.get("content")
    if not isinstance(content, list):
        return
    order = 0
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        order += 1
        _insert_row(
            conn,
            "tool_calls",
            {
                "turn_id": turn_id,
                "session_id": session_id,
                "tool_name": _string(item.get("name")) or "tool_use",
                "call_id": _string(item.get("id")),
                "call_order": order,
                "raw_json": DB.json_dumps(item),
            },
        )


def _import_plans(conn: sqlite3.Connection, snapshot_path: Path) -> None:
    registry = UI.load_plan_registry(snapshot_path)
    for plan_id, payload in registry.items():
        if not isinstance(payload, dict):
            continue
        uri = payload.get("uri")
        plan_path = uri.get("fsPath") if isinstance(uri, dict) else None
        _insert_row(
            conn,
            "plans",
            {
                "plan_id": str(plan_id),
                "plan_path": plan_path,
                "title": _string(payload.get("name")),
                "created_by_session_id": _string(payload.get("createdBy")),
                "edited_by_json": DB.json_dumps(payload.get("editedBy")),
                "updated_at": _ms_to_iso(_int(payload.get("updatedAt"))),
            },
            or_replace=True,
        )


def _update_ai_session_counts(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT session_id FROM sessions").fetchall()
    for row in rows:
        session_id = str(row["session_id"])
        alternate_id = session_id.split(":")[-1]
        chunk_count_row = conn.execute(
            """
            SELECT COUNT(DISTINCT a.hash) AS count
            FROM ai_code_chunks a
            WHERE a.conversation_id IN (?, ?)
               OR a.request_id IN (
                 SELECT request_id FROM turns WHERE session_id = ? AND request_id IS NOT NULL
               )
            """,
            (session_id, alternate_id, session_id),
        ).fetchone()
        chunk_count = int(chunk_count_row["count"]) if chunk_count_row else 0
        conn.execute(
            """
            UPDATE sessions
            SET ai_code_hash_count = ?,
                ai_attribution_json = ?
            WHERE session_id = ?
            """,
            (
                chunk_count,
                DB.json_dumps({"ai_code_hash_count": chunk_count}),
                session_id,
            ),
        )


def _list_rows(
    conn: sqlite3.Connection,
    *,
    source_type: str | None,
    workspace: str | None,
    project: str | None,
    since: date | None,
    limit: int,
    include_subagents: bool,
) -> list[sqlite3.Row]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if not include_subagents:
        clauses.append("is_subagent = 0")
    if source_type:
        clauses.append("source_type = ?")
        params.append(source_type)
    if workspace:
        clauses.append("LOWER(COALESCE(workspace, '')) LIKE ?")
        params.append(f"%{workspace.lower()}%")
    if project:
        like_value = f"%{project.lower()}%"
        clauses.append("(LOWER(COALESCE(project, '')) LIKE ? OR LOWER(COALESCE(cwd, '')) LIKE ?)")
        params.extend([like_value, like_value])
    if since is not None:
        clauses.append("DATE(COALESCE(last_updated_at, start_timestamp, imported_at)) >= DATE(?)")
        params.append(since.isoformat())
    params.append(limit)
    return conn.execute(
        f"""
        SELECT *
        FROM sessions
        WHERE {' AND '.join(clauses)}
        ORDER BY COALESCE(last_updated_at, start_timestamp, imported_at) DESC
        LIMIT ?
        """,
        params,
    ).fetchall()


def _row_to_descriptor(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "source_type": row["source_type"],
        "path": row["file_path"],
        "workspace": row["workspace"],
        "project": row["project"],
        "cwd": row["cwd"],
        "title": row["title"],
        "display_name": row["display_name"],
        "timestamp": row["start_timestamp"],
        "last_updated_at": row["last_updated_at"],
        "model": row["model"],
        "first_user_message": row["first_user_message"],
        "turn_count": row["turn_count"],
        "tool_call_count": row["tool_call_count"],
        "total_tokens": row["total_tokens"],
        "ai_code_hash_count": row["ai_code_hash_count"],
    }


def _row_to_ingestion_stub(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "session_inspector_v2",
        "source": SOURCE,
        "kind": "session_stub",
        "session": _ingestion_session(row),
        "content": {
            "first_user_message": row["first_user_message"],
            "raw_first_user_message": row["raw_first_user_message"],
            "delegated_task": row["delegated_task"],
        },
    }


def _row_to_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    tool_usage = {
        str(tool_row["tool_name"]): int(tool_row["count"])
        for tool_row in conn.execute(
            """
            SELECT tool_name, COUNT(*) AS count
            FROM tool_calls
            WHERE session_id = ?
            GROUP BY tool_name
            ORDER BY count DESC, tool_name
            """,
            (row["session_id"],),
        ).fetchall()
    }
    turns = [
        dict(item)
        for item in conn.execute(
            """
            SELECT turn_index, bubble_id, role, request_id, tool_call_id, turn_duration_ms,
                   thinking_duration_ms, capability_type, bubble_token_input, bubble_token_output
            FROM turns
            WHERE session_id = ?
            ORDER BY turn_index
            """,
            (row["session_id"],),
        ).fetchall()
    ]
    user_messages = [
        dict(item)
        for item in conn.execute(
            """
            SELECT message_index, text, word_count, char_count
            FROM user_messages
            WHERE session_id = ?
            ORDER BY message_index
            LIMIT 20
            """,
            (row["session_id"],),
        ).fetchall()
    ]
    pr_links = [
        item["url"]
        for item in conn.execute(
            "SELECT url FROM pr_links WHERE session_id = ? ORDER BY id",
            (row["session_id"],),
        ).fetchall()
        if item["url"]
    ]
    subagents = subagents_payload_for_conn(conn, str(row["session_id"]))
    store_token_usage = {
        "input_tokens": row["total_input_tokens"],
        "output_tokens": row["total_output_tokens"],
        "total_tokens": row["total_tokens"],
    }
    hook_token_usage = DB.hook_token_summary(conn, str(row["session_id"]))
    token_source = "hook" if hook_token_usage["event_count"] > 0 else (
        "store" if int(row["total_tokens"] or 0) > 0 else "none"
    )
    effective_token_usage = hook_token_usage if token_source == "hook" else store_token_usage
    return {
        **_row_to_descriptor(row),
        "total_tokens": effective_token_usage["total_tokens"],
        "raw_first_user_message": row["raw_first_user_message"],
        "delegated_task": row["delegated_task"],
        "unified_mode": row["unified_mode"],
        "force_mode": row["force_mode"],
        "agent_backend": row["agent_backend"],
        "is_subagent": bool(row["is_subagent"]),
        "parent_session_id": row["parent_session_id"],
        "context": {
            "context_tokens_used": row["context_tokens_used"],
            "context_token_limit": row["context_token_limit"],
            "context_usage_percent": row["context_usage_percent"],
        },
        "git": {
            "tracked_repo_path": row["tracked_repo_path"],
            "tracked_branch": row["tracked_branch"],
            "committed_to_branch": row["committed_to_branch"],
            "is_worktree": bool(row["is_worktree"]),
        },
        "execution": {
            "record_count": row["record_count"],
            "parse_errors": row["parse_errors"],
            "turn_count": row["turn_count"],
            "user_message_count": row["user_message_count"],
            "tool_call_count": row["tool_call_count"],
            "tool_error_count": row["tool_error_count"],
            "thinking_block_count": row["thinking_block_count"],
            "total_turn_duration_ms": row["total_turn_duration_ms"],
            "token_usage": {
                "input_tokens": effective_token_usage["input_tokens"],
                "output_tokens": effective_token_usage["output_tokens"],
                "total_tokens": effective_token_usage["total_tokens"],
                "token_source": token_source,
                "store": store_token_usage,
                "hook": hook_token_usage,
            },
            "tool_usage": tool_usage,
        },
        "turns": turns,
        "user_messages": user_messages,
        "links": {"prs": pr_links},
        "subagents": {
            "count": len(subagents),
            "children": subagents,
        },
        "ai_attribution": {
            "ai_code_hash_count": row["ai_code_hash_count"],
            "details": DB.json_loads(row["ai_attribution_json"]),
        },
        "metadata": {
            "models_used": DB.json_loads(row["models_used"]) or [],
            "composer_row_v": row["composer_row_v"],
            "bubble_row_v": row["bubble_row_v"],
            "workspace_identifier": DB.json_loads(row["workspace_identifier_json"]),
        },
    }


def subagents_payload_for_conn(conn: sqlite3.Connection, parent_session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
          sal.*,
          s.session_id AS child_row_session_id,
          s.title AS child_title,
          s.display_name AS child_display_name,
          s.model AS child_model,
          s.first_user_message AS child_first_user_message,
          s.turn_count AS child_turn_count,
          s.total_tokens AS child_total_tokens,
          COALESCE(hte.event_count, 0) AS child_hook_event_count,
          COALESCE(hte.input_tokens, 0) AS child_hook_input_tokens,
          COALESCE(hte.output_tokens, 0) AS child_hook_output_tokens,
          COALESCE(hte.cache_read_tokens, 0) AS child_hook_cache_read_tokens,
          COALESCE(hte.cache_write_tokens, 0) AS child_hook_cache_write_tokens,
          s.agent_backend AS child_agent_backend,
          s.source_type AS child_source_type
        FROM subagent_links sal
        LEFT JOIN sessions s ON s.session_id = sal.child_session_id
        LEFT JOIN (
          SELECT
            session_id,
            COUNT(*) AS event_count,
            COALESCE(SUM(input_tokens), 0) AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
            COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens
          FROM hook_token_events
          GROUP BY session_id
        ) hte ON hte.session_id = sal.child_session_id
        WHERE sal.parent_session_id = ?
        ORDER BY sal.id
        """,
        (parent_session_id,),
    ).fetchall()
    return [_subagent_row_to_payload(row) for row in rows]


def _subagent_row_to_payload(row: sqlite3.Row) -> dict[str, Any]:
    hook_total = int(row["child_hook_input_tokens"] or 0) + int(row["child_hook_output_tokens"] or 0)
    store_total = row["child_total_tokens"] or 0
    token_source = "hook" if row["child_hook_event_count"] else ("store" if store_total else "none")
    return {
        "composerId": row["child_session_id"],
        "session_id": row["child_session_id"],
        "name": row["child_display_name"] or row["agent_nickname"],
        "model": row["child_model"] or row["model"],
        "first_user_message": row["child_first_user_message"],
        "first_task": row["child_first_user_message"] or row["first_task"],
        "token_total": hook_total if token_source == "hook" else store_total,
        "token_source": token_source,
        "token_usage": {
            "input_tokens": int(row["child_hook_input_tokens"] or 0) if token_source == "hook" else 0,
            "output_tokens": int(row["child_hook_output_tokens"] or 0) if token_source == "hook" else 0,
            "cache_read_tokens": int(row["child_hook_cache_read_tokens"] or 0) if token_source == "hook" else 0,
            "cache_write_tokens": int(row["child_hook_cache_write_tokens"] or 0) if token_source == "hook" else 0,
            "event_count": int(row["child_hook_event_count"] or 0),
        },
        "turn_count": row["child_turn_count"],
        "agent_backend": row["child_agent_backend"],
        "source_type": row["child_source_type"],
        "agent_role": row["agent_role"],
    }


def _summary_to_ingestion(summary: dict[str, Any], *, kind: str) -> dict[str, Any]:
    return {
        "schema_version": "session_inspector_v2",
        "source": SOURCE,
        "kind": kind,
        "session": {
            "id": summary["session_id"],
            "path": summary["path"],
            "project": summary["project"],
            "cwd": summary["cwd"],
            "timestamp": summary["timestamp"],
            "title": summary["title"],
            "display_name": summary["display_name"],
            "source_type": summary["source_type"],
            "unified_mode": summary.get("unified_mode"),
            "agent_backend": summary.get("agent_backend"),
            "workspace_identifier": summary.get("metadata", {}).get("workspace_identifier"),
            "is_subagent": summary.get("is_subagent"),
            "parent_session_id": summary.get("parent_session_id"),
        },
        "content": {
            "first_user_message": summary["first_user_message"],
            "raw_first_user_message": summary.get("raw_first_user_message"),
            "delegated_task": summary.get("delegated_task"),
        },
        "execution": summary["execution"],
        "metadata": {
            "git": summary["git"],
            "models_used": summary["metadata"]["models_used"],
            "ai_attribution": summary["ai_attribution"],
        },
        "links": summary["links"],
        "subagents": summary["subagents"],
    }


def _ingestion_session(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["session_id"],
        "path": row["file_path"],
        "project": row["project"],
        "cwd": row["cwd"],
        "timestamp": row["start_timestamp"],
        "title": row["title"],
        "display_name": row["display_name"],
        "source_type": row["source_type"],
        "unified_mode": row["unified_mode"],
        "agent_backend": row["agent_backend"],
        "workspace_identifier": DB.json_loads(row["workspace_identifier_json"]),
        "model": row["model"],
        "is_subagent": bool(row["is_subagent"]),
        "parent_session_id": row["parent_session_id"],
    }


def _insert_row(
    conn: sqlite3.Connection,
    table: str,
    values: dict[str, Any],
    *,
    or_replace: bool = False,
) -> sqlite3.Cursor:
    clean = {key: value for key, value in values.items() if value is not None}
    columns = ", ".join(clean)
    placeholders = ", ".join(f":{column}" for column in clean)
    verb = "INSERT OR REPLACE" if or_replace else "INSERT"
    return conn.execute(f"{verb} INTO {table} ({columns}) VALUES ({placeholders})", clean)


def _merge_counts(parent: dict[str, Any], key: str, child: dict[str, Any]) -> None:
    parent[key] = child
    for field in ("imported", "skipped", "failed"):
        parent[field] += int(child.get(field, 0))
    parent["errors"].extend(child.get("errors", []))


def _counts() -> dict[str, Any]:
    return {"imported": 0, "skipped": 0, "failed": 0, "errors": []}


def _commit_maybe(conn: sqlite3.Connection) -> None:
    conn.commit()


def _matches_ui_filters(composer: Any, *, target: str | None, project: str | None, since: date | None) -> bool:
    payload = composer.payload
    haystack = json.dumps(
        {
            "composer_id": composer.composer_id,
            "name": payload.get("name"),
            "header": composer.header,
            "workspaceIdentifier": payload.get("workspaceIdentifier"),
        },
        sort_keys=True,
    ).lower()
    if target and target.lower() not in haystack:
        return False
    if project and project.lower() not in haystack:
        return False
    if since is not None:
        updated = _ms_to_datetime(_int(payload.get("lastUpdatedAt")))
        if updated is None or updated.date() < since:
            return False
    return True


def _matches_cli_filters(agent: Any, *, target: str | None, project: str | None, since: date | None) -> bool:
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
    if target and target.lower() not in haystack:
        return False
    if project and project.lower() not in haystack:
        return False
    if since is not None:
        created = _ms_to_datetime(agent.created_at)
        if created is None or created.date() < since:
            return False
    return True


def _matches_transcript_filters(transcript: Any, *, target: str | None, project: str | None, since: date | None) -> bool:
    haystack = f"{transcript.session_id} {transcript.path} {transcript.project_slug}".lower()
    if target and target.lower() not in haystack:
        target_lower = target.lower()
        parent_session_id = getattr(transcript, "parent_session_id", None)
        if not (parent_session_id and parent_session_id.lower() in target_lower):
            return False
    if project and project.lower() not in haystack:
        return False
    if since is not None and datetime.fromtimestamp(transcript.path.stat().st_mtime, UTC).date() < since:
        return False
    return True


def _first_ui_user_message(bubbles: Sequence[dict[str, Any]]) -> str | None:
    for bubble in bubbles:
        if _int(bubble.get("type")) == 1:
            text = _text_from_bubble(bubble)
            if text:
                return text
    return None


def _first_cli_user_message(messages: Sequence[Any]) -> str | None:
    for message in messages:
        if message.role == "user" and message.content:
            return message.content
    return None


def _insert_pr_links(conn: sqlite3.Connection, session_id: str, payloads: Sequence[Any]) -> None:
    seen: set[str] = set()
    for payload in payloads:
        for match in GITHUB_PR_RE.findall(json.dumps(payload, sort_keys=True)):
            url = match.rstrip('",}')
            if url in seen:
                continue
            seen.add(url)
            parts = url.split("/")
            number = _int(parts[-1])
            repository = "/".join(parts[-4:-2]) if len(parts) >= 5 else None
            _insert_row(
                conn,
                "pr_links",
                {
                    "session_id": session_id,
                    "url": url,
                    "number": number,
                    "repository": repository,
                },
            )


def _text_from_bubble(payload: dict[str, Any]) -> str | None:
    for key in ("text", "richText"):
        value = payload.get(key)
        text = _text_from_any(value)
        if text:
            return text
    return None


def _text_from_any(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_text_from_any(item) for item in value]
        joined = "\n".join(part for part in parts if part)
        return joined or None
    if isinstance(value, dict):
        for key in ("text", "content", "message", "value"):
            text = _text_from_any(value.get(key))
            if text:
                return text
        return json.dumps(value, sort_keys=True)
    return None


def _transcript_tool_blocks(record: dict[str, Any]) -> list[dict[str, Any]]:
    message = record.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [item for item in content if isinstance(item, dict) and item.get("type") == "tool_use"]


def _transcript_tool_count(records: Sequence[dict[str, Any]]) -> int:
    return sum(len(_transcript_tool_blocks(record)) for record in records)


def _cli_tool_call_count(messages: Sequence[Any]) -> int:
    count = 0
    for message in messages:
        if not isinstance(message.payload, dict):
            continue
        content = message.payload.get("content")
        if isinstance(content, list):
            count += sum(1 for item in content if isinstance(item, dict) and item.get("type") == "tool_use")
    return count


def _usage_total_tokens(value: Any) -> dict[str, int]:
    payload = _dict(value)
    input_tokens = _int(payload.get("inputTokens")) or _int(payload.get("input_tokens")) or 0
    output_tokens = _int(payload.get("outputTokens")) or _int(payload.get("output_tokens")) or 0
    total_tokens = _int(payload.get("totalTokens")) or _int(payload.get("total_tokens")) or input_tokens + output_tokens
    return {"input": input_tokens, "output": output_tokens, "total": total_tokens}


def _tool_name(payload: dict[str, Any]) -> str:
    for key in ("toolName", "name", "tool", "commandName"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return "tool"


def _tool_file_path(payload: dict[str, Any]) -> str | None:
    for key in ("filePath", "file_path", "path", "filename"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    input_payload = payload.get("input")
    if isinstance(input_payload, dict):
        return _tool_file_path(input_payload)
    return None


def _tool_command(payload: dict[str, Any]) -> str | None:
    for key in ("command", "cmd", "query"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list):
            return " ".join(str(part) for part in value)
    input_payload = payload.get("input")
    if isinstance(input_payload, dict):
        return _tool_command(input_payload)
    return None


def _tool_result_is_error(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    for key in ("isError", "is_error", "error"):
        value = payload.get(key)
        if isinstance(value, bool):
            return 1 if value else 0
    status = payload.get("status")
    if isinstance(status, str) and status.lower() in {"error", "failed", "failure"}:
        return 1
    return 0


def _tool_error_text(payload: dict[str, Any]) -> str | None:
    for key in ("errorText", "error_text", "error", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


_TOOL_FORMER_ERROR_STATUS = {"error", "failed", "failure", "cancelled", "canceled", "aborted", "timeout"}


def _tool_former_args(tool_former: dict[str, Any]) -> dict[str, Any]:
    """Merge the decoded ``params``/``rawArgs`` of a Cursor ``toolFormerData`` record.

    Cursor stores both as JSON-encoded strings. ``params`` is the normalized
    form (e.g. ``targetFile``, ``command``) so it wins on key collisions.
    """
    merged: dict[str, Any] = {}
    for key in ("rawArgs", "params"):
        value = tool_former.get(key)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
            try:
                value = json.loads(value)
            except (ValueError, TypeError):
                continue
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _tool_former_name(tool_former: dict[str, Any]) -> str:
    name = tool_former.get("name")
    if isinstance(name, str) and name:
        return name
    tool = tool_former.get("tool")
    if isinstance(tool, str) and tool:
        return tool
    if isinstance(tool, int):
        return f"tool_{tool}"
    return "tool"


def _tool_former_file_path(args: dict[str, Any]) -> str | None:
    for key in ("targetFile", "effectiveUri", "path", "targetDirectory", "filename", "file_path", "filePath"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _tool_former_command(args: dict[str, Any]) -> str | None:
    for key in ("command", "pattern", "globPattern", "query", "cmd"):
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list):
            return " ".join(str(part) for part in value)
    return None


def _tool_former_is_error(tool_former: dict[str, Any]) -> int:
    status = tool_former.get("status")
    if isinstance(status, str) and status.lower() in _TOOL_FORMER_ERROR_STATUS:
        return 1
    if isinstance(tool_former.get("error"), (str, dict)) and tool_former.get("error"):
        return 1
    return 0


def _insert_ui_tool_former_call(
    conn: sqlite3.Connection,
    session_id: str,
    turn_id: int,
    tool_former: dict[str, Any],
    *,
    call_order: int,
) -> None:
    args = _tool_former_args(tool_former)
    _insert_row(
        conn,
        "tool_calls",
        {
            "turn_id": turn_id,
            "session_id": session_id,
            "tool_name": _tool_former_name(tool_former),
            "file_path": _tool_former_file_path(args),
            "command": _tool_former_command(args),
            "is_error": _tool_former_is_error(tool_former),
            "error_text": _tool_error_text(tool_former),
            "call_id": _string(tool_former.get("toolCallId")) or _string(tool_former.get("modelCallId")),
            "call_order": call_order,
            "raw_json": DB.json_dumps(tool_former),
        },
    )


def _branch_name(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        return _string(value.get("branchName")) or _string(value.get("name"))
    return None


def _ms_to_iso(value: int | None) -> str | None:
    parsed = _ms_to_datetime(value)
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") if parsed else None


def _ms_to_datetime(value: int | None) -> datetime | None:
    if value is None or value <= 0:
        return None
    seconds = value / 1000
    return datetime.fromtimestamp(seconds, UTC)


def _mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except OSError:
        return None


def _project_from_path(value: str | None) -> str | None:
    if not value:
        return None
    return Path(value).name


def _preview(value: str | None, *, limit: int = 240) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _dedupe(values: Sequence[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return None


def _nested_int(payload: dict[str, Any], *keys: str) -> int | None:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _int(current)


def _nested_string(payload: dict[str, Any], *keys: str) -> str | None:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _string(current)


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _bool(value: Any) -> bool:
    return bool(value) if isinstance(value, bool) else False
