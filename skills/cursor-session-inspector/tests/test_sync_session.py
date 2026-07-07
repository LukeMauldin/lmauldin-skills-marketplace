from __future__ import annotations

import importlib.util
import json
import os
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


sync_session = load_module("test_cursor_sync_session", ROOT / "scripts" / "sync_session.py")
db = load_module("test_cursor_sync_db", ROOT / "scripts" / "db.py")


class SyncSessionTests(unittest.TestCase):
    def test_persist_hook_token_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / ".cursor" / "inspector" / "session_inspector.db"
            sync_session.persist_hook_token_event(
                db_path,
                {
                    "session_id": "session-1",
                    "generation_id": "generation-1",
                    "hook_event_name": "stop",
                    "model": "composer-2.5-fast",
                    "input_tokens": 12,
                    "output_tokens": 4,
                    "cache_read_tokens": 8,
                    "cache_write_tokens": 0,
                    "user_email": "user@example.com",
                },
                raw_payload_path=None,
            )

            with closing(db.open_db(db_path)) as conn:
                row = conn.execute(
                    """
                    SELECT session_id, generation_id, input_tokens, output_tokens, cache_read_tokens
                    FROM hook_token_events
                    """
                ).fetchone()

            self.assertEqual(dict(row), {
                "session_id": "session-1",
                "generation_id": "generation-1",
                "input_tokens": 12,
                "output_tokens": 4,
                "cache_read_tokens": 8,
            })

    def test_capture_payload_is_opt_in_and_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cursor_home = Path(temp) / ".cursor"
            payload = {"session_id": "session-1", "input_tokens": 1}

            self.assertIsNone(sync_session.capture_payload_if_enabled(cursor_home, payload))

            old_value = os.environ.get("CURSOR_INSPECTOR_CAPTURE_HOOK_PAYLOAD")
            os.environ["CURSOR_INSPECTOR_CAPTURE_HOOK_PAYLOAD"] = "1"
            try:
                for index in range(3):
                    capture = sync_session.capture_payload_if_enabled(cursor_home, {**payload, "index": index})
                    self.assertIsNotNone(capture)
                capture_dir = cursor_home / "inspector" / "payload-captures"
                sync_session.prune_payload_captures(capture_dir, keep=2)
                captures = sorted(capture_dir.glob("*.json"))
            finally:
                if old_value is None:
                    os.environ.pop("CURSOR_INSPECTOR_CAPTURE_HOOK_PAYLOAD", None)
                else:
                    os.environ["CURSOR_INSPECTOR_CAPTURE_HOOK_PAYLOAD"] = old_value

            self.assertEqual(len(captures), 2)
            loaded = [json.loads(path.read_text(encoding="utf-8")) for path in captures]
            self.assertTrue(all(item["session_id"] == "session-1" for item in loaded))

    def test_optional_path_env(self) -> None:
        old_value = os.environ.get("CURSOR_APP_SUPPORT")
        os.environ["CURSOR_APP_SUPPORT"] = "~/Library/Application Support/Cursor Test"
        try:
            path = sync_session._optional_path_env("CURSOR_APP_SUPPORT")
        finally:
            if old_value is None:
                os.environ.pop("CURSOR_APP_SUPPORT", None)
            else:
                os.environ["CURSOR_APP_SUPPORT"] = old_value

        self.assertIsNotNone(path)
        self.assertTrue(str(path).endswith("Library/Application Support/Cursor Test"))

    def test_resolve_cursor_paths_uses_profile_from_payload_cwd(self) -> None:
        old_real_home = os.environ.get("CURSOR_REAL_HOME")
        old_cursor_profile = os.environ.get("CURSOR_PROFILE")
        old_cursor_home = os.environ.get("CURSOR_HOME")
        old_cursor_app_support = os.environ.get("CURSOR_APP_SUPPORT")
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            os.environ["CURSOR_REAL_HOME"] = str(home)
            os.environ.pop("CURSOR_PROFILE", None)
            os.environ.pop("CURSOR_HOME", None)
            os.environ.pop("CURSOR_APP_SUPPORT", None)
            try:
                cursor_home, app_support = sync_session.resolve_cursor_paths(
                    {"cwd": str(home / "code" / "github.com" / "jb-web-dev" / "site")}
                )
            finally:
                if old_real_home is None:
                    os.environ.pop("CURSOR_REAL_HOME", None)
                else:
                    os.environ["CURSOR_REAL_HOME"] = old_real_home
                if old_cursor_profile is None:
                    os.environ.pop("CURSOR_PROFILE", None)
                else:
                    os.environ["CURSOR_PROFILE"] = old_cursor_profile
                if old_cursor_home is None:
                    os.environ.pop("CURSOR_HOME", None)
                else:
                    os.environ["CURSOR_HOME"] = old_cursor_home
                if old_cursor_app_support is None:
                    os.environ.pop("CURSOR_APP_SUPPORT", None)
                else:
                    os.environ["CURSOR_APP_SUPPORT"] = old_cursor_app_support

        self.assertEqual(cursor_home, Path(temp) / ".cursor-homes" / "jb" / ".cursor")
        self.assertEqual(app_support, Path(temp) / ".cursor-instances" / "jb")


if __name__ == "__main__":
    unittest.main()
