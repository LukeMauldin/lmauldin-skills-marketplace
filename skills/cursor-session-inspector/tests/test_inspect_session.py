from __future__ import annotations

import importlib.util
import json
import os
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


inspect_session = load_module("test_cursor_inspect_session", ROOT / "scripts" / "inspect_session.py")


class InspectSessionTests(unittest.TestCase):
    def test_locate_surfaces_hook_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cursor_home = Path(temp) / ".cursor"
            app_support = Path(temp) / "Application Support" / "Cursor"
            paths = inspect_session.resolve_paths(cursor_home, app_support)

            payload = inspect_session.locate_payload(paths)

            self.assertIn("sync_session.py", payload["recommended_hook_command"])
            self.assertNotIn("payload-captures", payload["recommended_hook_command"])
            self.assertNotIn("tee", payload["recommended_hook_command"])
            self.assertFalse(payload["hook_configured"])
            self.assertEqual(payload["ui_composer_count"], 0)

    def test_resolve_paths_uses_cursor_app_support_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cursor_home = Path(temp) / ".cursor"
            app_support = Path(temp) / "split-user-data"
            old_value = os.environ.get("CURSOR_APP_SUPPORT")
            os.environ["CURSOR_APP_SUPPORT"] = str(app_support)
            try:
                paths = inspect_session.resolve_paths(cursor_home, None)
            finally:
                if old_value is None:
                    os.environ.pop("CURSOR_APP_SUPPORT", None)
                else:
                    os.environ["CURSOR_APP_SUPPORT"] = old_value

            self.assertEqual(paths.cursor_app_support, app_support)
            self.assertEqual(
                paths.ui_store_path,
                app_support / "User" / "globalStorage" / "state.vscdb",
            )

    def test_resolve_paths_uses_cursor_profile_override(self) -> None:
        old_real_home = os.environ.get("CURSOR_REAL_HOME")
        old_cursor_home = os.environ.get("CURSOR_HOME")
        old_cursor_app_support = os.environ.get("CURSOR_APP_SUPPORT")
        with tempfile.TemporaryDirectory() as temp:
            os.environ["CURSOR_REAL_HOME"] = temp
            os.environ.pop("CURSOR_HOME", None)
            os.environ.pop("CURSOR_APP_SUPPORT", None)
            try:
                paths = inspect_session.resolve_paths(None, None, "ks")
            finally:
                if old_real_home is None:
                    os.environ.pop("CURSOR_REAL_HOME", None)
                else:
                    os.environ["CURSOR_REAL_HOME"] = old_real_home
                if old_cursor_home is None:
                    os.environ.pop("CURSOR_HOME", None)
                else:
                    os.environ["CURSOR_HOME"] = old_cursor_home
                if old_cursor_app_support is None:
                    os.environ.pop("CURSOR_APP_SUPPORT", None)
                else:
                    os.environ["CURSOR_APP_SUPPORT"] = old_cursor_app_support

        self.assertEqual(paths.cursor_profile, "ks")
        self.assertEqual(paths.cursor_home, Path(temp) / ".cursor-homes" / "ks" / ".cursor")
        self.assertEqual(paths.cursor_app_support, Path(temp) / ".cursor-instances" / "ks")

    def test_infer_cursor_profile_from_repo_root(self) -> None:
        old_real_home = os.environ.get("CURSOR_REAL_HOME")
        old_cursor_home = os.environ.get("CURSOR_HOME")
        old_cursor_app_support = os.environ.get("CURSOR_APP_SUPPORT")
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            os.environ["CURSOR_REAL_HOME"] = str(home)
            os.environ.pop("CURSOR_HOME", None)
            os.environ.pop("CURSOR_APP_SUPPORT", None)
            try:
                profile = inspect_session.infer_cursor_profile(
                    home / "code" / "github.com" / "KidStrong" / "KidStrongBedrock",
                )
            finally:
                if old_real_home is None:
                    os.environ.pop("CURSOR_REAL_HOME", None)
                else:
                    os.environ["CURSOR_REAL_HOME"] = old_real_home
                if old_cursor_home is None:
                    os.environ.pop("CURSOR_HOME", None)
                else:
                    os.environ["CURSOR_HOME"] = old_cursor_home
                if old_cursor_app_support is None:
                    os.environ.pop("CURSOR_APP_SUPPORT", None)
                else:
                    os.environ["CURSOR_APP_SUPPORT"] = old_cursor_app_support

        self.assertEqual(profile, "ks")

    def test_hook_config_status_detects_installed_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hook_path = Path(temp) / "hooks.json"
            hook_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "hooks": {
                            "stop": [
                                {
                                    "command": "uv run /tmp/cursor-session-inspector/skills/cursor-session-inspector/scripts/sync_session.py"
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            status = inspect_session.hook_config_status(hook_path)

            self.assertTrue(status["configured"])
            self.assertEqual(status["stop_command_count"], 1)

    def test_hook_config_status_recognizes_debug_hook(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hook_path = Path(temp) / "hooks.json"
            hook_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "hooks": {
                            "stop": [
                                {
                                    "command": "uv run /tmp/cursor-session-inspector/skills/cursor-session-inspector/scripts/debug_hook.py"
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            status = inspect_session.hook_config_status(hook_path)

            self.assertTrue(status["configured"])
            self.assertEqual(status["stop_command_count"], 1)


if __name__ == "__main__":
    unittest.main()
