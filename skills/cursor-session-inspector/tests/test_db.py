from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import closing
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


db = load_module("test_cursor_db", ROOT / "scripts" / "db.py")


class CursorDbTests(unittest.TestCase):
    def test_pending_marker_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / ".cursor" / "inspector" / "session_inspector.db"
            db.write_pending_marker(
                db_path,
                "session:1",
                {
                    "session_id": "session:1",
                    "target": "session:1",
                    "marker_kind": "reconcile",
                    "retryable": True,
                },
            )

            markers = list(db.iter_pending_markers(db_path))
            self.assertEqual(len(markers), 1)
            self.assertEqual(markers[0][1]["session_id"], "session:1")

            reconciled = db.reconcile_pending_markers(db_path, lambda payload: True)
            self.assertEqual(reconciled, ["session:1"])
            self.assertEqual(list(db.iter_pending_markers(db_path)), [])

    def test_import_log_stats_skip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "session_inspector.db"
            with closing(db.open_db(db_path)) as conn:
                db.record_import_stats(
                    conn,
                    "ui_composer:abc",
                    mtime_ns=10,
                    size_bytes=20,
                    session_id="abc",
                    parser_version=1,
                    record_count=3,
                )
                self.assertTrue(
                    db.should_skip_stats(
                        conn,
                        "ui_composer:abc",
                        mtime_ns=10,
                        size_bytes=20,
                        parser_version=1,
                    )
                )
                self.assertFalse(
                    db.should_skip_stats(
                        conn,
                        "ui_composer:abc",
                        mtime_ns=11,
                        size_bytes=20,
                        parser_version=1,
                    )
                )

    def test_hook_token_event_upsert_omits_user_email(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "session_inspector.db"
            payload = {
                "session_id": "session-1",
                "conversation_id": "conversation-1",
                "generation_id": "generation-1",
                "hook_event_name": "stop",
                "status": "completed",
                "model": "composer-2.5-fast",
                "cursor_version": "3.4.20",
                "loop_count": 0,
                "transcript_path": "/tmp/session.jsonl",
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_tokens": 7,
                "cache_write_tokens": 2,
                "user_email": "user@example.com",
            }
            with closing(db.open_db(db_path)) as conn:
                event = db.hook_token_event_from_payload(payload, received_at="2026-05-19T10:00:00.000Z")
                self.assertIsNotNone(event)
                assert event is not None
                self.assertNotIn("user_email", event)
                db.record_hook_token_event(conn, event)

                updated = dict(payload)
                updated["input_tokens"] = 20
                updated_event = db.hook_token_event_from_payload(
                    updated,
                    received_at="2026-05-19T10:01:00.000Z",
                )
                self.assertIsNotNone(updated_event)
                assert updated_event is not None
                db.record_hook_token_event(conn, updated_event)

                row = conn.execute(
                    """
                    SELECT COUNT(*) AS count, SUM(input_tokens) AS input_tokens
                    FROM hook_token_events
                    WHERE session_id = ?
                    """,
                    ("session-1",),
                ).fetchone()
                summary = db.hook_token_summary(conn, "session-1")

            self.assertEqual(row["count"], 1)
            self.assertEqual(row["input_tokens"], 20)
            self.assertEqual(summary["event_count"], 1)
            self.assertEqual(summary["input_tokens"], 20)
            self.assertEqual(summary["cache_read_tokens"], 7)


if __name__ == "__main__":
    unittest.main()
