from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 7

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
CREATE INDEX IF NOT EXISTS idx_il_session ON import_log(session_id);

CREATE TABLE IF NOT EXISTS sessions (
  session_id              TEXT PRIMARY KEY,
  source                  TEXT NOT NULL,
  file_path               TEXT NOT NULL,
  project                 TEXT,
  cwd                     TEXT,
  title                   TEXT,
  display_name            TEXT,
  model                   TEXT,
  git_branch              TEXT,
  git_commit              TEXT,
  version                 TEXT,
  first_user_message      TEXT,
  raw_first_user_message  TEXT,
  delegated_task          TEXT,
  start_timestamp         TEXT,
  archived                INTEGER DEFAULT 0,
  is_subagent             INTEGER DEFAULT 0,
  parent_session_id       TEXT,
  forked_from_id          TEXT,
  agent_nickname          TEXT,
  agent_role              TEXT,
  record_count            INTEGER DEFAULT 0,
  parse_errors            INTEGER DEFAULT 0,
  turn_count              INTEGER DEFAULT 0,
  completed_turn_count    INTEGER DEFAULT 0,
  total_turn_duration_ms  INTEGER DEFAULT 0,
  total_input_tokens      INTEGER DEFAULT 0,
  total_output_tokens     INTEGER DEFAULT 0,
  total_cache_read        INTEGER DEFAULT 0,
  total_cache_write       INTEGER,
  tool_call_count         INTEGER DEFAULT 0,
  tool_error_count        INTEGER DEFAULT 0,
  total_reasoning_items   INTEGER DEFAULT 0,
  total_encrypted_reasoning_items INTEGER DEFAULT 0,
  total_reasoning_content_len INTEGER DEFAULT 0,
  total_reasoning_tokens  INTEGER DEFAULT 0,
  user_message_count      INTEGER DEFAULT 0,
  user_interrupt_count    INTEGER DEFAULT 0,
  total_user_char_count   INTEGER DEFAULT 0,
  models_used             TEXT,
  imported_at             TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  thread_name             TEXT,
  filename_timestamp      TEXT,
  model_provider          TEXT,
  token_mode              TEXT,
  record_counts_json      TEXT,
  event_counts_json       TEXT,
  response_item_counts_json TEXT,
  session_meta_json       TEXT,
  git_json                TEXT,
  latest_turn_context_json TEXT,
  token_usage_json        TEXT,
  tool_usage_json         TEXT,
  turn_durations_json     TEXT,
  current_subagent_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_s_project ON sessions(project);
CREATE INDEX IF NOT EXISTS idx_s_start ON sessions(start_timestamp);
CREATE INDEX IF NOT EXISTS idx_s_parent ON sessions(parent_session_id);

CREATE TABLE IF NOT EXISTS turns (
  id              INTEGER PRIMARY KEY,
  session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  turn_index      INTEGER NOT NULL,
  message_id      TEXT,
  timestamp       TEXT,
  model           TEXT,
  duration_ms     INTEGER,
  input_tokens    INTEGER DEFAULT 0,
  cached_input_tokens INTEGER DEFAULT 0,
  cache_write_tokens INTEGER,
  output_tokens   INTEGER DEFAULT 0,
  total_tokens    INTEGER DEFAULT 0,
  reasoning_item_count INTEGER DEFAULT 0,
  tool_use_block_count INTEGER DEFAULT 0,
  reasoning_output_tokens INTEGER DEFAULT 0,
  UNIQUE(session_id, turn_index)
);
CREATE INDEX IF NOT EXISTS idx_t_session ON turns(session_id);

CREATE TABLE IF NOT EXISTS token_usage_events (
  id                      INTEGER PRIMARY KEY,
  session_id              TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  turn_id                 INTEGER REFERENCES turns(id) ON DELETE CASCADE,
  turn_index              INTEGER NOT NULL,
  timestamp               TEXT NOT NULL,
  raw_model               TEXT,
  model_provider          TEXT,
  model_context_window    INTEGER,
  usage_source            TEXT NOT NULL,
  is_approximate          INTEGER DEFAULT 0,
  input_tokens            INTEGER DEFAULT 0,
  cached_input_tokens     INTEGER DEFAULT 0,
  cache_write_tokens      INTEGER,
  output_tokens           INTEGER DEFAULT 0,
  reasoning_output_tokens INTEGER DEFAULT 0,
  total_tokens            INTEGER DEFAULT 0,
  cumulative_input_tokens INTEGER DEFAULT 0,
  cumulative_cached_input_tokens INTEGER DEFAULT 0,
  cumulative_cache_write_tokens INTEGER,
  cumulative_output_tokens INTEGER DEFAULT 0,
  cumulative_reasoning_output_tokens INTEGER DEFAULT 0,
  cumulative_total_tokens INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tue_session ON token_usage_events(session_id);
CREATE INDEX IF NOT EXISTS idx_tue_turn ON token_usage_events(turn_id);
CREATE INDEX IF NOT EXISTS idx_tue_timestamp ON token_usage_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_tue_session_ts ON token_usage_events(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_tue_model_ts ON token_usage_events(raw_model, timestamp);

CREATE TABLE IF NOT EXISTS tool_calls (
  id              INTEGER PRIMARY KEY,
  turn_id         INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  session_id      TEXT NOT NULL,
  tool_name       TEXT NOT NULL,
  file_path       TEXT,
  command         TEXT,
  is_error        INTEGER DEFAULT 0,
  error_text      TEXT,
  call_type       TEXT,
  call_id         TEXT,
  call_order      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tc_turn ON tool_calls(turn_id);
CREATE INDEX IF NOT EXISTS idx_tc_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tc_tool ON tool_calls(tool_name);

CREATE TABLE IF NOT EXISTS reasoning_items (
  id                INTEGER PRIMARY KEY,
  turn_id           INTEGER NOT NULL REFERENCES turns(id) ON DELETE CASCADE,
  session_id        TEXT NOT NULL,
  block_index       INTEGER NOT NULL,
  block_type        TEXT NOT NULL DEFAULT 'reasoning',
  is_redacted       INTEGER DEFAULT 0,
  content_length    INTEGER DEFAULT 0,
  encrypted_content_length INTEGER DEFAULT 0,
  summary_item_count INTEGER DEFAULT 0,
  has_plaintext_content INTEGER DEFAULT 0,
  UNIQUE(turn_id, block_index)
);
CREATE INDEX IF NOT EXISTS idx_ri_turn ON reasoning_items(turn_id);
CREATE INDEX IF NOT EXISTS idx_ri_session ON reasoning_items(session_id);

CREATE TABLE IF NOT EXISTS user_messages (
  id                    INTEGER PRIMARY KEY,
  session_id            TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  message_index         INTEGER NOT NULL,
  timestamp             TEXT,
  is_first              INTEGER DEFAULT 0,
  is_interrupt          INTEGER DEFAULT 0,
  word_count            INTEGER DEFAULT 0,
  char_count            INTEGER DEFAULT 0,
  preceding_turn_index  INTEGER,
  UNIQUE(session_id, message_index)
);
CREATE INDEX IF NOT EXISTS idx_um_session ON user_messages(session_id);

CREATE TABLE IF NOT EXISTS tool_call_files (
  id              INTEGER PRIMARY KEY,
  tool_call_id    INTEGER NOT NULL REFERENCES tool_calls(id) ON DELETE CASCADE,
  session_id      TEXT NOT NULL,
  file_path       TEXT NOT NULL,
  UNIQUE(tool_call_id, file_path)
);
CREATE INDEX IF NOT EXISTS idx_tcf_tool_call ON tool_call_files(tool_call_id);
CREATE INDEX IF NOT EXISTS idx_tcf_session ON tool_call_files(session_id);

CREATE TABLE IF NOT EXISTS hook_executions (
  id              INTEGER PRIMARY KEY,
  session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  hook_command    TEXT NOT NULL,
  duration_ms     INTEGER DEFAULT 0,
  is_error        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_he_session ON hook_executions(session_id);

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
CREATE INDEX IF NOT EXISTS idx_sal_parent ON subagent_links(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_sal_child ON subagent_links(child_session_id);

CREATE TABLE IF NOT EXISTS pr_links (
  id              INTEGER PRIMARY KEY,
  session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  url             TEXT,
  number          INTEGER,
  repository      TEXT
);
CREATE INDEX IF NOT EXISTS idx_pr_session ON pr_links(session_id);
"""


def default_db_path(home: Path) -> Path:
    return home / "inspector" / "session_inspector.db"


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
    for table_name in (
        "pr_links",
        "subagent_links",
        "hook_executions",
        "tool_call_files",
        "token_usage_events",
        "reasoning_items",
        "tool_calls",
        "turns",
        "user_messages",
        "sessions",
        "import_log",
    ):
        conn.execute(f"DELETE FROM {table_name}")


def rebuild_schema(conn: sqlite3.Connection) -> None:
    for table_name in (
        "pr_links",
        "subagent_links",
        "hook_executions",
        "tool_call_files",
        "token_usage_events",
        "reasoning_items",
        "tool_calls",
        "turns",
        "user_messages",
        "sessions",
        "import_log",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
    conn.executescript(SCHEMA_SQL)


def remove_db_files(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{db_path}{suffix}")
        if candidate.exists():
            candidate.unlink()


def should_skip(conn: sqlite3.Connection, file_path: Path, parser_version: int) -> bool:
    try:
        stat = file_path.stat()
    except OSError:
        return False
    row = conn.execute(
        """
        SELECT mtime_ns, size_bytes, parser_version
        FROM import_log
        WHERE file_path = ?
        """,
        (str(file_path),),
    ).fetchone()
    if row is None:
        return False
    return (
        int(row["mtime_ns"]) == stat.st_mtime_ns
        and int(row["size_bytes"]) == stat.st_size
        and int(row["parser_version"]) == parser_version
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
            str(file_path),
            stat.st_mtime_ns,
            stat.st_size,
            parser_version,
            session_id,
            record_count,
        ),
    )


def delete_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        "DELETE FROM subagent_links WHERE parent_session_id = ? OR child_session_id = ?",
        (session_id, session_id),
    )
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM import_log WHERE session_id = ?", (session_id,))


def child_session_ids(conn: sqlite3.Connection, parent_session_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT child_session_id
        FROM (
            SELECT child_session_id
            FROM subagent_links
            WHERE parent_session_id = ?
            UNION
            SELECT session_id AS child_session_id
            FROM sessions
            WHERE parent_session_id = ?
        )
        ORDER BY child_session_id
        """,
        (parent_session_id, parent_session_id),
    ).fetchall()
    return [str(row["child_session_id"]) for row in rows]


def session_row(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()


def last_import_timestamp(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(imported_at) AS imported_at FROM import_log").fetchone()
    if row is None:
        return None
    return row["imported_at"]


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
    reasons: dict[str, int] = {}
    legacy_count = 0
    retryable_count = 0
    due_count = 0
    now = datetime.now(timezone.utc)
    for marker_path, payload in markers:
        if not isinstance(payload.get("marker_kind"), str):
            legacy_count += 1
        marker_kind = payload.get("marker_kind")
        if isinstance(marker_kind, str) and marker_kind:
            kinds[marker_kind] = kinds.get(marker_kind, 0) + 1
        reason = payload.get("reason")
        if isinstance(reason, str) and reason:
            reasons[reason] = reasons.get(reason, 0) + 1
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
        "legacy_count": legacy_count,
        "retryable_count": retryable_count,
        "due_count": due_count,
        "kinds": kinds,
        "reasons": reasons,
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
    if isinstance(payload.get("marker_kind"), str):
        return True

    # Legacy markers predate marker_kind/retryable. Only retry legacy markers
    # that target an explicit rollout path; old hook session-id markers often
    # do not map to rollout ids and are kept as diagnostics.
    target = payload.get("target") or payload.get("transcript_path")
    if not isinstance(target, str) or not target:
        return False
    target_path = Path(target).expanduser()
    return target_path.is_absolute() or target_path.suffix == ".jsonl"


def json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def json_loads(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return None
    return json.loads(value)


def safe_marker_name(value: str) -> str:
    return value.replace("/", "_").replace("\\", "_")
