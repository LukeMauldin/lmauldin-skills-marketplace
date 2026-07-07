from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS import_log (
  id              INTEGER PRIMARY KEY,
  file_path       TEXT UNIQUE NOT NULL,
  mtime_ns        INTEGER NOT NULL,
  size_bytes      INTEGER NOT NULL,
  parser_version  INTEGER NOT NULL,
  session_id      TEXT NOT NULL,
  record_count    INTEGER DEFAULT 0,
  imported_at     TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_import_log_session ON import_log(session_id);

CREATE TABLE IF NOT EXISTS sessions (
  session_id              TEXT PRIMARY KEY,
  source                  TEXT NOT NULL,
  source_type             TEXT NOT NULL,
  file_path               TEXT,
  workspace               TEXT,
  project                 TEXT,
  cwd                     TEXT,
  title                   TEXT,
  display_name            TEXT,
  model                   TEXT,
  first_user_message      TEXT,
  raw_first_user_message  TEXT,
  delegated_task          TEXT,
  start_timestamp         TEXT,
  last_updated_at         TEXT,
  is_subagent             INTEGER DEFAULT 0,
  parent_session_id       TEXT,
  record_count            INTEGER DEFAULT 0,
  parse_errors            INTEGER DEFAULT 0,
  turn_count              INTEGER DEFAULT 0,
  completed_turn_count    INTEGER DEFAULT 0,
  user_message_count      INTEGER DEFAULT 0,
  tool_call_count         INTEGER DEFAULT 0,
  tool_error_count        INTEGER DEFAULT 0,
  thinking_block_count    INTEGER DEFAULT 0,
  total_turn_duration_ms  INTEGER DEFAULT 0,
  total_input_tokens      INTEGER DEFAULT 0,
  total_output_tokens     INTEGER DEFAULT 0,
  total_tokens            INTEGER DEFAULT 0,
  models_used             TEXT,
  imported_at             TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),

  unified_mode            TEXT,
  force_mode              TEXT,
  agent_backend           TEXT,
  is_worktree             INTEGER DEFAULT 0,
  is_draft                INTEGER DEFAULT 0,
  is_archived             INTEGER DEFAULT 0,
  is_best_of_n_parent     INTEGER DEFAULT 0,
  is_best_of_n_subcomposer INTEGER DEFAULT 0,
  context_tokens_used     INTEGER,
  context_token_limit     INTEGER,
  context_usage_percent   REAL,
  tracked_repo_path       TEXT,
  tracked_branch          TEXT,
  committed_to_branch     TEXT,
  stop_hook_loop_count    INTEGER,
  workspace_identifier_id TEXT,
  workspace_identifier_fs_path TEXT,
  composer_row_v          INTEGER,
  bubble_row_v            INTEGER,
  usage_data_json         TEXT,
  model_config_json       TEXT,
  workspace_identifier_json TEXT,
  raw_json                TEXT,
  ai_code_hash_count      INTEGER DEFAULT 0,
  ai_attribution_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_source_type ON sessions(source_type);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(last_updated_at);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project);
CREATE INDEX IF NOT EXISTS idx_sessions_parent ON sessions(parent_session_id);

CREATE TABLE IF NOT EXISTS turns (
  id                    INTEGER PRIMARY KEY,
  session_id            TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  turn_index            INTEGER NOT NULL,
  bubble_id             TEXT,
  message_id            TEXT,
  role                  TEXT,
  timestamp             TEXT,
  text                  TEXT,
  model                 TEXT,
  request_id            TEXT,
  tool_call_id          TEXT,
  turn_duration_ms      INTEGER,
  thinking_duration_ms  INTEGER,
  capability_type       INTEGER,
  is_renderable         INTEGER DEFAULT 0,
  is_plan_execution     INTEGER DEFAULT 0,
  bubble_token_input    INTEGER DEFAULT 0,
  bubble_token_output   INTEGER DEFAULT 0,
  raw_json              TEXT,
  UNIQUE(session_id, turn_index)
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_turns_request ON turns(request_id);

CREATE TABLE IF NOT EXISTS tool_calls (
  id              INTEGER PRIMARY KEY,
  turn_id         INTEGER REFERENCES turns(id) ON DELETE CASCADE,
  session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  tool_name       TEXT NOT NULL,
  file_path       TEXT,
  command         TEXT,
  is_error        INTEGER DEFAULT 0,
  error_text      TEXT,
  call_id         TEXT,
  call_order      INTEGER DEFAULT 0,
  raw_json        TEXT
);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_turn ON tool_calls(turn_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_name ON tool_calls(tool_name);

CREATE TABLE IF NOT EXISTS user_messages (
  id              INTEGER PRIMARY KEY,
  session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  message_index   INTEGER NOT NULL,
  timestamp       TEXT,
  text            TEXT,
  word_count      INTEGER DEFAULT 0,
  char_count      INTEGER DEFAULT 0,
  raw_json        TEXT,
  UNIQUE(session_id, message_index)
);
CREATE INDEX IF NOT EXISTS idx_user_messages_session ON user_messages(session_id);

CREATE TABLE IF NOT EXISTS thinking_blocks (
  id              INTEGER PRIMARY KEY,
  turn_id         INTEGER REFERENCES turns(id) ON DELETE CASCADE,
  session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  block_index     INTEGER NOT NULL,
  text            TEXT,
  duration_ms     INTEGER,
  raw_json        TEXT,
  UNIQUE(session_id, turn_id, block_index)
);
CREATE INDEX IF NOT EXISTS idx_thinking_blocks_session ON thinking_blocks(session_id);

CREATE TABLE IF NOT EXISTS subagent_links (
  id                  INTEGER PRIMARY KEY,
  parent_session_id   TEXT NOT NULL,
  child_session_id    TEXT NOT NULL,
  agent_nickname      TEXT,
  agent_role          TEXT,
  model               TEXT,
  first_task          TEXT,
  UNIQUE(parent_session_id, child_session_id)
);
CREATE INDEX IF NOT EXISTS idx_subagent_links_parent ON subagent_links(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_subagent_links_child ON subagent_links(child_session_id);

CREATE TABLE IF NOT EXISTS pr_links (
  id              INTEGER PRIMARY KEY,
  session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  url             TEXT,
  number          INTEGER,
  repository      TEXT
);
CREATE INDEX IF NOT EXISTS idx_pr_links_session ON pr_links(session_id);

CREATE TABLE IF NOT EXISTS hook_executions (
  id              INTEGER PRIMARY KEY,
  session_id      TEXT REFERENCES sessions(session_id) ON DELETE CASCADE,
  hook_command    TEXT NOT NULL,
  duration_ms     INTEGER DEFAULT 0,
  is_error        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_hook_executions_session ON hook_executions(session_id);

CREATE TABLE IF NOT EXISTS hook_token_events (
  id                 INTEGER PRIMARY KEY,
  session_id         TEXT NOT NULL,
  conversation_id    TEXT,
  generation_id      TEXT,
  hook_event_name    TEXT,
  status             TEXT,
  model              TEXT,
  cursor_version     TEXT,
  loop_count         INTEGER,
  transcript_path    TEXT,
  input_tokens       INTEGER DEFAULT 0,
  output_tokens      INTEGER DEFAULT 0,
  cache_read_tokens  INTEGER DEFAULT 0,
  cache_write_tokens INTEGER DEFAULT 0,
  received_at        TEXT NOT NULL,
  raw_payload_path   TEXT,
  UNIQUE(session_id, generation_id)
);
CREATE INDEX IF NOT EXISTS idx_hook_token_events_session ON hook_token_events(session_id);
CREATE INDEX IF NOT EXISTS idx_hook_token_events_generation ON hook_token_events(generation_id);
CREATE INDEX IF NOT EXISTS idx_hook_token_events_received ON hook_token_events(received_at);

CREATE TABLE IF NOT EXISTS ai_code_chunks (
  hash            TEXT PRIMARY KEY,
  source          TEXT,
  file_extension  TEXT,
  file_name       TEXT,
  request_id      TEXT,
  conversation_id TEXT,
  timestamp       INTEGER,
  model           TEXT,
  created_at      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ai_code_chunks_conversation ON ai_code_chunks(conversation_id);
CREATE INDEX IF NOT EXISTS idx_ai_code_chunks_request ON ai_code_chunks(request_id);
CREATE INDEX IF NOT EXISTS idx_ai_code_chunks_timestamp ON ai_code_chunks(timestamp);

CREATE TABLE IF NOT EXISTS commit_scores (
  commit_hash           TEXT NOT NULL,
  branch_name           TEXT NOT NULL,
  scored_at             INTEGER,
  lines_added           INTEGER,
  lines_deleted         INTEGER,
  tab_lines_added       INTEGER,
  tab_lines_deleted     INTEGER,
  composer_lines_added  INTEGER,
  composer_lines_deleted INTEGER,
  human_lines_added     INTEGER,
  human_lines_deleted   INTEGER,
  blank_lines_added     INTEGER,
  blank_lines_deleted   INTEGER,
  commit_message        TEXT,
  commit_date           TEXT,
  v1_ai_percentage      TEXT,
  v2_ai_percentage      TEXT,
  PRIMARY KEY(commit_hash, branch_name)
);
CREATE INDEX IF NOT EXISTS idx_commit_scores_branch ON commit_scores(branch_name);
CREATE INDEX IF NOT EXISTS idx_commit_scores_scored ON commit_scores(scored_at);

CREATE TABLE IF NOT EXISTS conversation_summaries (
  conversation_id   TEXT PRIMARY KEY,
  title             TEXT,
  tldr              TEXT,
  overview          TEXT,
  summary_bullets   TEXT,
  model             TEXT,
  mode              TEXT,
  updated_at        INTEGER
);

CREATE TABLE IF NOT EXISTS plans (
  plan_id               TEXT PRIMARY KEY,
  plan_path             TEXT,
  title                 TEXT,
  created_by_session_id TEXT,
  edited_by_json        TEXT,
  updated_at            TEXT
);
"""


IMPORTED_TABLES = (
    "pr_links",
    "subagent_links",
    "hook_token_events",
    "hook_executions",
    "thinking_blocks",
    "tool_calls",
    "turns",
    "user_messages",
    "sessions",
    "import_log",
    "plans",
    "conversation_summaries",
    "commit_scores",
    "ai_code_chunks",
)


def default_db_path(cursor_home: Path) -> Path:
    return cursor_home.expanduser() / "inspector" / "session_inspector.db"


def pending_dir(db_path: Path) -> Path:
    return db_path.parent / "pending"


def ensure_state_dirs(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    pending_dir(db_path).mkdir(parents=True, exist_ok=True)


def apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")


def open_db(db_path: Path) -> sqlite3.Connection:
    ensure_state_dirs(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    apply_pragmas(conn)
    ensure_schema(conn)
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
        return
    current = int(row["version"])
    if current < SCHEMA_VERSION:
        rebuild_schema(conn)
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        conn.commit()


def clear_imported_content(conn: sqlite3.Connection) -> None:
    for table_name in IMPORTED_TABLES:
        conn.execute(f"DELETE FROM {table_name}")


def rebuild_schema(conn: sqlite3.Connection) -> None:
    for table_name in IMPORTED_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.execute("DROP TABLE IF EXISTS schema_version")
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))


def remove_db_files(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{db_path}{suffix}")
        if candidate.exists():
            candidate.unlink()


def hook_token_event_from_payload(
    payload: dict[str, Any],
    *,
    received_at: str | None = None,
    raw_payload_path: str | None = None,
) -> dict[str, Any] | None:
    session_id = string_field(payload, "session_id")
    if session_id is None:
        return None
    token_fields = (
        int_field(payload, "input_tokens"),
        int_field(payload, "output_tokens"),
        int_field(payload, "cache_read_tokens"),
        int_field(payload, "cache_write_tokens"),
    )
    if all(value is None for value in token_fields):
        return None
    return {
        "session_id": session_id,
        "conversation_id": string_field(payload, "conversation_id"),
        "generation_id": string_field(payload, "generation_id"),
        "hook_event_name": string_field(payload, "hook_event_name"),
        "status": string_field(payload, "status"),
        "model": string_field(payload, "model"),
        "cursor_version": string_field(payload, "cursor_version"),
        "loop_count": int_field(payload, "loop_count"),
        "transcript_path": string_field(payload, "transcript_path"),
        "input_tokens": token_fields[0] or 0,
        "output_tokens": token_fields[1] or 0,
        "cache_read_tokens": token_fields[2] or 0,
        "cache_write_tokens": token_fields[3] or 0,
        "received_at": received_at or iso_now(),
        "raw_payload_path": raw_payload_path,
    }


def record_hook_token_event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    clean = {key: value for key, value in event.items() if value is not None}
    if clean.get("generation_id"):
        columns = ", ".join(clean)
        placeholders = ", ".join(f":{column}" for column in clean)
        updates = ", ".join(
            f"{column} = excluded.{column}"
            for column in clean
            if column not in {"session_id", "generation_id"}
        )
        conn.execute(
            f"""
            INSERT INTO hook_token_events ({columns})
            VALUES ({placeholders})
            ON CONFLICT(session_id, generation_id) DO UPDATE SET {updates}
            """,
            clean,
        )
        return

    columns = ", ".join(clean)
    placeholders = ", ".join(f":{column}" for column in clean)
    conn.execute(f"INSERT INTO hook_token_events ({columns}) VALUES ({placeholders})", clean)


def hook_token_summary(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    totals = conn.execute(
        """
        SELECT
          COUNT(*) AS event_count,
          COALESCE(SUM(input_tokens), 0) AS input_tokens,
          COALESCE(SUM(output_tokens), 0) AS output_tokens,
          COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
          COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
          MAX(received_at) AS latest_received_at
        FROM hook_token_events
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()
    latest = conn.execute(
        """
        SELECT model, cursor_version, status, hook_event_name
        FROM hook_token_events
        WHERE session_id = ?
        ORDER BY received_at DESC, id DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    event_count = int(totals["event_count"]) if totals else 0
    return {
        "event_count": event_count,
        "input_tokens": int(totals["input_tokens"]) if totals else 0,
        "output_tokens": int(totals["output_tokens"]) if totals else 0,
        "total_tokens": (int(totals["input_tokens"]) + int(totals["output_tokens"])) if totals else 0,
        "cache_read_tokens": int(totals["cache_read_tokens"]) if totals else 0,
        "cache_write_tokens": int(totals["cache_write_tokens"]) if totals else 0,
        "latest_received_at": str(totals["latest_received_at"]) if totals and totals["latest_received_at"] else None,
        "latest_model": str(latest["model"]) if latest and latest["model"] else None,
        "latest_cursor_version": str(latest["cursor_version"]) if latest and latest["cursor_version"] else None,
        "latest_status": str(latest["status"]) if latest and latest["status"] else None,
        "latest_hook_event_name": str(latest["hook_event_name"]) if latest and latest["hook_event_name"] else None,
    }


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def string_field(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    return value if isinstance(value, str) and value else None


def int_field(payload: dict[str, Any], field: str) -> int | None:
    value = payload.get(field)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def should_skip_stats(
    conn: sqlite3.Connection,
    file_path: str,
    *,
    mtime_ns: int,
    size_bytes: int,
    parser_version: int,
) -> bool:
    row = conn.execute(
        """
        SELECT mtime_ns, size_bytes, parser_version
        FROM import_log
        WHERE file_path = ?
        """,
        (file_path,),
    ).fetchone()
    if row is None:
        return False
    return (
        int(row["mtime_ns"]) == mtime_ns
        and int(row["size_bytes"]) == size_bytes
        and int(row["parser_version"]) == parser_version
    )


def should_skip(conn: sqlite3.Connection, file_path: Path, parser_version: int) -> bool:
    try:
        stat = file_path.stat()
    except OSError:
        return False
    return should_skip_stats(
        conn,
        str(file_path),
        mtime_ns=stat.st_mtime_ns,
        size_bytes=stat.st_size,
        parser_version=parser_version,
    )


def record_import_stats(
    conn: sqlite3.Connection,
    file_path: str,
    *,
    mtime_ns: int,
    size_bytes: int,
    session_id: str,
    parser_version: int,
    record_count: int,
) -> None:
    conn.execute(
        """
        INSERT INTO import_log(
            file_path,
            mtime_ns,
            size_bytes,
            parser_version,
            session_id,
            record_count,
            imported_at
        )
        VALUES(?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        ON CONFLICT(file_path) DO UPDATE SET
            mtime_ns = excluded.mtime_ns,
            size_bytes = excluded.size_bytes,
            parser_version = excluded.parser_version,
            session_id = excluded.session_id,
            record_count = excluded.record_count,
            imported_at = excluded.imported_at
        """,
        (
            file_path,
            mtime_ns,
            size_bytes,
            parser_version,
            session_id,
            record_count,
        ),
    )


def record_import(
    conn: sqlite3.Connection,
    file_path: Path,
    *,
    session_id: str,
    parser_version: int,
    record_count: int,
) -> None:
    stat = file_path.stat()
    record_import_stats(
        conn,
        str(file_path),
        mtime_ns=stat.st_mtime_ns,
        size_bytes=stat.st_size,
        session_id=session_id,
        parser_version=parser_version,
        record_count=record_count,
    )


def delete_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("DELETE FROM subagent_links WHERE parent_session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM import_log WHERE session_id = ?", (session_id,))


def session_exists(conn: sqlite3.Connection, session_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sessions WHERE session_id = ? LIMIT 1",
        (session_id,),
    ).fetchone()
    return row is not None


def session_row(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()


def latest_session_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        """
        SELECT session_id
        FROM sessions
        WHERE is_subagent = 0
        ORDER BY COALESCE(last_updated_at, start_timestamp, imported_at) DESC
        LIMIT 1
        """
    ).fetchone()
    return str(row["session_id"]) if row else None


def last_import_timestamp(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(imported_at) AS imported_at FROM import_log").fetchone()
    return str(row["imported_at"]) if row and row["imported_at"] is not None else None


def database_stats(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "exists": False,
            "path": str(db_path),
            "session_count": 0,
            "subagent_count": 0,
            "last_import_at": None,
        }
    with closing(open_db(db_path)) as conn:
        session_row_count = conn.execute(
            "SELECT COUNT(*) AS count FROM sessions WHERE is_subagent = 0"
        ).fetchone()
        subagent_row_count = conn.execute(
            "SELECT COUNT(*) AS count FROM sessions WHERE is_subagent = 1"
        ).fetchone()
        return {
            "exists": True,
            "path": str(db_path),
            "session_count": int(session_row_count["count"]) if session_row_count else 0,
            "subagent_count": int(subagent_row_count["count"]) if subagent_row_count else 0,
            "last_import_at": last_import_timestamp(conn),
        }


def write_pending_marker(db_path: Path, session_id: str, payload: dict[str, Any]) -> Path:
    ensure_state_dirs(db_path)
    marker_path = pending_dir(db_path) / f"{safe_marker_name(session_id)}.json"
    marker_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return marker_path


def iter_pending_markers(db_path: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    marker_dir = pending_dir(db_path)
    if not marker_dir.exists():
        return
    for marker_path in sorted(marker_dir.glob("*.json")):
        try:
            payload = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            yield marker_path, payload


def reconcile_pending_markers(
    db_path: Path,
    handler: Callable[[dict[str, Any]], bool],
) -> list[str]:
    reconciled: list[str] = []
    for marker_path, payload in iter_pending_markers(db_path):
        if handler(payload):
            marker_path.unlink(missing_ok=True)
            session_id = payload.get("session_id")
            if isinstance(session_id, str) and session_id:
                reconciled.append(session_id)
    return reconciled


def pending_marker_stats(db_path: Path) -> dict[str, Any]:
    marker_dir = pending_dir(db_path)
    markers = list(iter_pending_markers(db_path))
    newest: dict[str, Any] | None = None
    kinds: dict[str, int] = {}
    retryable_count = 0
    due_count = 0
    now = datetime.now(timezone.utc)
    for marker_path, payload in markers:
        marker_kind = payload.get("marker_kind")
        if isinstance(marker_kind, str) and marker_kind:
            kinds[marker_kind] = kinds.get(marker_kind, 0) + 1
        retryable = is_retryable_pending_marker(payload)
        if retryable:
            retryable_count += 1
        not_before = parse_marker_timestamp(payload.get("not_before"))
        if retryable and (not_before is None or not_before <= now):
            due_count += 1
        try:
            mtime_ns = marker_path.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0
        if newest is None or mtime_ns > newest["mtime_ns"]:
            newest = {
                "path": str(marker_path),
                "mtime_ns": mtime_ns,
                "payload": payload,
            }
    return {
        "dir": str(marker_dir),
        "count": len(markers),
        "retryable_count": retryable_count,
        "due_count": due_count,
        "kinds": kinds,
        "newest": newest,
    }


def parse_marker_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def is_retryable_pending_marker(payload: dict[str, Any]) -> bool:
    if payload.get("retryable") is False:
        return False
    return isinstance(payload.get("marker_kind"), str)


def json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def json_loads(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return None
    return json.loads(value)


def safe_marker_name(value: str) -> str:
    return value.replace("/", "_").replace("\\", "_").replace(":", "_")
