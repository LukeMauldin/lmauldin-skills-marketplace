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
SYNC_PATH = ROOT / "scripts" / "sync_rollout.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


db = load_module("test_codex_db_module", DB_PATH)
importer = load_module("test_codex_importer_module", IMPORTER_PATH)


class CodexDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.codex_home = self.root / ".codex"
        self.db_path = importer.resolve_db_path(self.codex_home)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_pending_marker_reconciliation_deletes_successful_markers(self) -> None:
        db.write_pending_marker(
            self.db_path,
            "thread-123",
            {"session_id": "thread-123", "target": "thread-123"},
        )
        seen: list[str] = []

        reconciled = db.reconcile_pending_markers(
            self.db_path,
            lambda payload: seen.append(payload["session_id"]) or True,
        )

        self.assertEqual(reconciled, ["thread-123"])
        self.assertEqual(seen, ["thread-123"])
        self.assertEqual(list(db.pending_dir(self.db_path).glob("*.json")), [])

    def test_sync_rollout_writes_pending_marker_when_target_is_missing(self) -> None:
        env = {**os.environ, "CODEX_HOME": str(self.codex_home)}
        process = subprocess.run(
            ["uv", "run", "--python", "3.14", "python", str(SYNC_PATH)],
            input=json.dumps(
                {
                    "hook_event_name": "Stop",
                    "session_id": "missing-thread",
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
        self.assertEqual(payload["target"], "missing-thread")
        self.assertEqual(payload["hook_event_name"], "Stop")
        self.assertEqual(payload["marker_kind"], "import_failed")
        self.assertEqual(payload["reason"], "unresolved_hook_session_id")
        self.assertFalse(payload["retryable"])

    def test_sync_rollout_records_missing_transcript_path(self) -> None:
        env = {**os.environ, "CODEX_HOME": str(self.codex_home)}
        transcript_path = self.codex_home / "sessions" / "2026" / "04" / "07" / "rollout-missing.jsonl"
        process = subprocess.run(
            ["uv", "run", "--python", "3.14", "python", str(SYNC_PATH)],
            input=json.dumps(
                {
                    "hook_event_name": "Stop",
                    "session_id": "missing-thread",
                    "turn_id": "turn-123",
                    "cwd": "/tmp/project",
                    "transcript_path": str(transcript_path),
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
        self.assertEqual(payload["target"], str(transcript_path))
        self.assertEqual(payload["transcript_path"], str(transcript_path))
        self.assertEqual(payload["turn_id"], "turn-123")
        self.assertEqual(payload["marker_kind"], "import_failed")
        self.assertEqual(payload["reason"], "missing_transcript_path")
        self.assertTrue(payload["retryable"])
        self.assertFalse(payload["transcript_path_exists"])

    def test_sync_rollout_imports_existing_transcript_and_schedules_reconcile(self) -> None:
        env = {**os.environ, "CODEX_HOME": str(self.codex_home)}
        thread_id = "019d2494-6c37-7c93-9df6-7ed84372b136"
        transcript_path = (
            self.codex_home
            / "sessions"
            / "2026"
            / "04"
            / "07"
            / f"rollout-2026-04-07T12-00-00-{thread_id}.jsonl"
        )
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(
            "\n".join(
                json.dumps(row)
                for row in [
                    {
                        "timestamp": "2026-04-07T12:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "cwd": "/tmp/project",
                            "timestamp": "2026-04-07T12:00:00Z",
                            "cli_version": "1.2.3",
                            "source": {},
                        },
                    },
                    {
                        "timestamp": "2026-04-07T12:00:01Z",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "hello"},
                    },
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        process = subprocess.run(
            ["uv", "run", "--python", "3.14", "python", str(SYNC_PATH)],
            input=json.dumps(
                {
                    "hook_event_name": "Stop",
                    "session_id": thread_id,
                    "turn_id": "turn-123",
                    "cwd": "/tmp/project",
                    "transcript_path": str(transcript_path),
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
                (thread_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["record_count"], 2)

    def test_sync_rollout_ignores_non_stop_events(self) -> None:
        env = {**os.environ, "CODEX_HOME": str(self.codex_home)}
        process = subprocess.run(
            ["uv", "run", "--python", "3.14", "python", str(SYNC_PATH)],
            input=json.dumps(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "missing-thread",
                    "cwd": "/tmp/project",
                }
            ),
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

        self.assertEqual(process.returncode, 0)
        self.assertEqual(list(db.pending_dir(self.db_path).glob("*.json")), [])

    def test_pending_marker_stats_reports_due_and_newest_markers(self) -> None:
        db.write_pending_marker(
            self.db_path,
            "retryable",
            {
                "session_id": "retryable",
                "target": "retryable",
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
        self.assertEqual(stats["legacy_count"], 0)
        self.assertEqual(stats["retryable_count"], 1)
        self.assertEqual(stats["due_count"], 1)
        self.assertEqual(stats["kinds"]["reconcile"], 1)
        self.assertEqual(stats["reasons"]["unresolved_hook_session_id"], 1)
        self.assertIsNotNone(stats["newest"])

    def test_legacy_session_id_marker_is_not_retryable(self) -> None:
        db.write_pending_marker(
            self.db_path,
            "legacy",
            {
                "session_id": "legacy",
                "target": "legacy",
            },
        )

        stats = db.pending_marker_stats(self.db_path)

        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["legacy_count"], 1)
        self.assertEqual(stats["retryable_count"], 0)
        self.assertEqual(stats["due_count"], 0)
        self.assertFalse(
            db.is_retryable_pending_marker({"session_id": "legacy", "target": "legacy"})
        )
        self.assertTrue(
            db.is_retryable_pending_marker(
                {"session_id": "legacy", "target": str(self.codex_home / "sessions" / "x.jsonl")}
            )
        )


if __name__ == "__main__":
    unittest.main()
