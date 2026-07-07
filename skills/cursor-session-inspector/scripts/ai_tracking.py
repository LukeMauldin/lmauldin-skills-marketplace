from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any


def snapshot_ai_tracking_db(src: Path, dst: Path | None = None) -> Path:
    src = src.expanduser()
    if not src.exists():
        raise FileNotFoundError(src)
    if dst is None:
        fd, name = tempfile.mkstemp(prefix="cursor-ai-tracking-", suffix=".db")
        os.close(fd)
        Path(name).unlink(missing_ok=True)
        target = Path(name)
    elif dst.is_dir():
        target = dst / "cursor-ai-tracking.db"
    else:
        target = dst
        target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return target


def iter_ai_code_chunks(db_path: Path) -> Iterator[dict[str, Any]]:
    if not db_path.exists():
        return
    with closing(_connect(db_path)) as conn:
        for row in conn.execute(
            """
            SELECT
              hash,
              source,
              fileExtension AS file_extension,
              fileName AS file_name,
              requestId AS request_id,
              conversationId AS conversation_id,
              timestamp,
              model,
              createdAt AS created_at
            FROM ai_code_hashes
            """
        ):
            yield dict(row)


def iter_commit_scores(db_path: Path) -> Iterator[dict[str, Any]]:
    if not db_path.exists():
        return
    with closing(_connect(db_path)) as conn:
        for row in conn.execute(
            """
            SELECT
              commitHash AS commit_hash,
              branchName AS branch_name,
              scoredAt AS scored_at,
              linesAdded AS lines_added,
              linesDeleted AS lines_deleted,
              tabLinesAdded AS tab_lines_added,
              tabLinesDeleted AS tab_lines_deleted,
              composerLinesAdded AS composer_lines_added,
              composerLinesDeleted AS composer_lines_deleted,
              humanLinesAdded AS human_lines_added,
              humanLinesDeleted AS human_lines_deleted,
              blankLinesAdded AS blank_lines_added,
              blankLinesDeleted AS blank_lines_deleted,
              commitMessage AS commit_message,
              commitDate AS commit_date,
              v1AiPercentage AS v1_ai_percentage,
              v2AiPercentage AS v2_ai_percentage
            FROM scored_commits
            """
        ):
            yield dict(row)


def iter_conversation_summaries(db_path: Path) -> Iterator[dict[str, Any]]:
    if not db_path.exists():
        return
    with closing(_connect(db_path)) as conn:
        try:
            rows = conn.execute(
                """
                SELECT
                  conversationId AS conversation_id,
                  title,
                  tldr,
                  overview,
                  summaryBullets AS summary_bullets,
                  model,
                  mode,
                  updatedAt AS updated_at
                FROM conversation_summaries
                """
            )
        except sqlite3.Error:
            return
        for row in rows:
            yield dict(row)


def database_counts(db_path: Path) -> dict[str, int]:
    if not db_path.exists():
        return {"ai_code_chunks": 0, "commit_scores": 0, "conversation_summaries": 0}
    counts: dict[str, int] = {}
    with closing(_connect(db_path)) as conn:
        for table in ("ai_code_hashes", "scored_commits", "conversation_summaries"):
            try:
                row = conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()
            except sqlite3.Error:
                counts[table] = 0
            else:
                counts[table] = int(row["count"]) if row else 0
    return {
        "ai_code_chunks": counts.get("ai_code_hashes", 0),
        "commit_scores": counts.get("scored_commits", 0),
        "conversation_summaries": counts.get("conversation_summaries", 0),
    }


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn
