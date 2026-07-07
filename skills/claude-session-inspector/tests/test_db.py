from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "scripts" / "db.py"
IMPORTER_PATH = ROOT / "scripts" / "importer.py"
SYNC_PATH = ROOT / "scripts" / "sync_session.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


db = load_module("test_claude_db_module", DB_PATH)
importer = load_module("test_claude_importer_module", IMPORTER_PATH)


class ClaudeDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.claude_home = self.root / ".claude"
        self.db_path = importer.resolve_db_path(self.claude_home)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_pending_marker_reconciliation_deletes_successful_markers(self) -> None:
        db.write_pending_marker(
            self.db_path,
            "session-123",
            {"session_id": "session-123", "target": "session-123"},
        )
        seen: list[str] = []

        reconciled = db.reconcile_pending_markers(
            self.db_path,
            lambda payload: seen.append(payload["session_id"]) or True,
        )

        self.assertEqual(reconciled, ["session-123"])
        self.assertEqual(seen, ["session-123"])
        self.assertEqual(list(db.pending_dir(self.db_path).glob("*.json")), [])

    def test_sync_session_writes_pending_marker_when_target_is_missing(self) -> None:
        env = {**os.environ, "CLAUDE_HOME": str(self.claude_home)}
        process = subprocess.run(
            ["uv", "run", "--script", str(SYNC_PATH)],
            input=json.dumps(
                {
                    "hook_event_name": "Stop",
                    "session_id": "missing-session",
                    "cwd": "/tmp/project",
                }
            ),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

        self.assertEqual(process.returncode, 0)
        markers = list(db.pending_dir(self.db_path).glob("*.json"))
        self.assertEqual(len(markers), 1)
        payload = json.loads(markers[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["target"], "missing-session")
        self.assertEqual(payload["hook_event_name"], "Stop")
        self.assertEqual(payload["marker_kind"], "import_failed")
        self.assertEqual(payload["reason"], "unresolved_hook_session_id")
        self.assertFalse(payload["retryable"])

    def test_sync_session_imports_existing_transcript_and_schedules_reconcile(self) -> None:
        env = {**os.environ, "CLAUDE_HOME": str(self.claude_home)}
        session_id = "11111111-1111-1111-1111-111111111111"
        transcript_path = (
            self.claude_home
            / "projects"
            / "-tmp-project"
            / f"{session_id}.jsonl"
        )
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(
            "\n".join(
                json.dumps(row)
                for row in [
                    {
                        "type": "user",
                        "parentUuid": None,
                        "sessionId": session_id,
                        "timestamp": "2026-04-01T10:00:00Z",
                        "cwd": "/tmp/project",
                        "message": {"content": "hello"},
                    },
                    {
                        "type": "assistant",
                        "requestId": "req-1",
                        "timestamp": "2026-04-01T10:00:01Z",
                        "message": {
                            "id": "msg-1",
                            "model": "claude-sonnet-4-5",
                            "stop_reason": "end_turn",
                            "content": [],
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        },
                    },
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        process = subprocess.run(
            ["uv", "run", "--script", str(SYNC_PATH)],
            input=json.dumps(
                {
                    "hook_event_name": "Stop",
                    "session_id": session_id,
                    "cwd": "/tmp/project",
                    "transcript_path": str(transcript_path),
                    "stop_reason": "end_turn",
                }
            ),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

        self.assertEqual(process.returncode, 0)
        markers = list(db.pending_dir(self.db_path).glob("*.json"))
        self.assertEqual(len(markers), 1)
        payload = json.loads(markers[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["marker_kind"], "reconcile")
        self.assertEqual(payload["reason"], "post_stop_final_flush")
        self.assertEqual(payload["target"], str(transcript_path))
        self.assertTrue(payload["retryable"])
        self.assertTrue(payload["transcript_path_exists"])
        with closing(db.open_db(self.db_path)) as conn:
            row = conn.execute(
                "SELECT record_count FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["record_count"], 2)

    def test_pending_marker_stats_reports_due_and_newest_markers(self) -> None:
        db.write_pending_marker(
            self.db_path,
            "retryable",
            {
                "session_id": "retryable",
                "target": "/tmp/session.jsonl",
                "marker_kind": "reconcile",
                "reason": "post_stop_final_flush",
                "retryable": True,
            },
        )
        db.write_pending_marker(
            self.db_path,
            "terminal",
            {
                "session_id": "terminal",
                "target": "terminal",
                "marker_kind": "import_failed",
                "reason": "unresolved_hook_session_id",
                "retryable": False,
            },
        )

        stats = db.pending_marker_stats(self.db_path)

        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["retryable_count"], 1)
        self.assertEqual(stats["due_count"], 1)
        self.assertEqual(stats["kinds"]["reconcile"], 1)
        self.assertEqual(stats["reasons"]["unresolved_hook_session_id"], 1)


if __name__ == "__main__":
    unittest.main()
