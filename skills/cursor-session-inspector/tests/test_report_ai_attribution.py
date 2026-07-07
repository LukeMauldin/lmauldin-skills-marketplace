from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


report = load_module("test_cursor_report_ai", ROOT / "scripts" / "report_ai_attribution.py")


class ReportAiAttributionTests(unittest.TestCase):
    def test_reports_commits_from_raw_ai_db(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cursor_home = Path(temp) / ".cursor"
            write_ai_db(cursor_home / "ai-tracking" / "ai-code-tracking.db")

            rows = report.load_report_rows(cursor_home, begin=None, end=None, group_by="commit", limit=10)

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["commit_hash"], "abc")
            self.assertEqual(rows[0]["v2_ai_percentage"], "91.67")


def write_ai_db(path: Path) -> None:
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE ai_code_hashes (hash TEXT PRIMARY KEY, source TEXT NOT NULL, fileExtension TEXT, fileName TEXT, requestId TEXT, conversationId TEXT, timestamp INTEGER, model TEXT, createdAt INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE scored_commits (commitHash TEXT, branchName TEXT, scoredAt INTEGER, linesAdded INTEGER, linesDeleted INTEGER, tabLinesAdded INTEGER, tabLinesDeleted INTEGER, composerLinesAdded INTEGER, composerLinesDeleted INTEGER, humanLinesAdded INTEGER, humanLinesDeleted INTEGER, blankLinesAdded INTEGER, blankLinesDeleted INTEGER, commitMessage TEXT, commitDate TEXT, v1AiPercentage TEXT, v2AiPercentage TEXT, PRIMARY KEY(commitHash, branchName))"
    )
    conn.execute(
        "CREATE TABLE conversation_summaries (conversationId TEXT PRIMARY KEY, title TEXT, tldr TEXT, overview TEXT, summaryBullets TEXT, model TEXT, mode TEXT, updatedAt INTEGER NOT NULL)"
    )
    conn.execute(
        "INSERT INTO ai_code_hashes VALUES('hash-1', 'composer', '.py', 'app.py', 'req-1', 'composer-1', 1770000000000, 'composer-2', 1770000000000)"
    )
    conn.execute(
        "INSERT INTO scored_commits VALUES('abc', 'main', 1770000000000, 10, 2, 1, 0, 8, 1, 1, 1, 0, 0, 'message', 'Wed Mar 25 13:42:14 2026 -0500', '90.00', '91.67')"
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    unittest.main()
