from __future__ import annotations

import importlib.util
import json
import sqlite3
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


importer = load_module("test_cursor_importer", ROOT / "scripts" / "importer.py")
db = load_module("test_cursor_importer_db", ROOT / "scripts" / "db.py")


class CursorImporterTests(unittest.TestCase):
    def test_refresh_imports_ui_cli_transcript_and_ai(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cursor_home = root / ".cursor"
            app_support = root / "Application Support" / "Cursor"
            write_state_db(app_support / "User" / "globalStorage" / "state.vscdb")
            write_store_db(cursor_home / "chats" / "workspace" / "agent-1" / "store.db")
            write_transcript(cursor_home / "projects" / "proj" / "agent-transcripts" / "transcript-1" / "transcript-1.jsonl")
            write_ai_db(cursor_home / "ai-tracking" / "ai-code-tracking.db")

            result = importer.refresh_sessions(cursor_home, app_support=app_support, reconcile=False)

            self.assertGreaterEqual(result["imported"], 4)
            summary = importer.summary_payload(cursor_home, "composer-1", profile="default")
            self.assertIsNotNone(summary)
            assert summary is not None
            self.assertEqual(summary["source_type"], "ui_composer")
            self.assertEqual(summary["execution"]["tool_usage"], {"Shell": 1})
            self.assertEqual(summary["ai_attribution"]["ai_code_hash_count"], 1)

            cli_summary = importer.summary_payload(cursor_home, "agent-1", profile="default")
            self.assertIsNotNone(cli_summary)
            assert cli_summary is not None
            self.assertEqual(cli_summary["source_type"], "cli_agent")

            with closing(db.open_db(importer.resolve_db_path(cursor_home))) as conn:
                session_count = conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]
                self.assertEqual(session_count, 3)

    def test_subagents_payload_uses_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cursor_home = root / ".cursor"
            app_support = root / "Application Support" / "Cursor"
            write_state_db(app_support / "User" / "globalStorage" / "state.vscdb", include_child=True)

            importer.refresh_sessions(cursor_home, app_support=app_support, reconcile=False)
            subagents = importer.subagents_payload(cursor_home, "composer-1", profile="default")

            self.assertIsNotNone(subagents)
            assert subagents is not None
            self.assertEqual(subagents[0]["session_id"], "child-1")

    def test_refresh_backfills_hook_token_captures_and_summary_prefers_hook_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cursor_home = root / ".cursor"
            app_support = root / "Application Support" / "Cursor"
            write_state_db(app_support / "User" / "globalStorage" / "state.vscdb")
            capture_dir = cursor_home / "inspector" / "payload-captures"
            capture_dir.mkdir(parents=True)
            (capture_dir / "20260519T100000-1.json").write_text(
                json.dumps(
                    {
                        "session_id": "composer-1",
                        "conversation_id": "composer-1",
                        "generation_id": "generation-1",
                        "hook_event_name": "stop",
                        "status": "completed",
                        "model": "composer-2.5-fast",
                        "cursor_version": "3.4.20",
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "cache_read_tokens": 80,
                        "cache_write_tokens": 3,
                        "user_email": "user@example.com",
                    }
                ),
                encoding="utf-8",
            )

            result = importer.refresh_sessions(cursor_home, app_support=app_support, reconcile=False)
            summary = importer.summary_payload(cursor_home, "composer-1", profile="default")

            self.assertEqual(result["hook_token_events"]["imported"], 1)
            self.assertIsNotNone(summary)
            assert summary is not None
            token_usage = summary["execution"]["token_usage"]
            self.assertEqual(token_usage["token_source"], "hook")
            self.assertEqual(token_usage["input_tokens"], 100)
            self.assertEqual(token_usage["output_tokens"], 20)
            self.assertEqual(token_usage["total_tokens"], 120)
            self.assertEqual(token_usage["hook"]["cache_read_tokens"], 80)
            self.assertEqual(token_usage["hook"]["cache_write_tokens"], 3)
            self.assertEqual(token_usage["store"]["total_tokens"], 15)

            with closing(db.open_db(importer.resolve_db_path(cursor_home))) as conn:
                columns = [row["name"] for row in conn.execute("PRAGMA table_info(hook_token_events)")]
                self.assertNotIn("user_email", columns)

    def test_parent_transcript_target_imports_subagent_transcripts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cursor_home = root / ".cursor"
            app_support = root / "Application Support" / "Cursor"
            parent_path = cursor_home / "projects" / "proj" / "agent-transcripts" / "parent-1" / "parent-1.jsonl"
            child_path = parent_path.parent / "subagents" / "child-1.jsonl"
            write_transcript(parent_path)
            write_transcript(child_path)

            importer.refresh_sessions(
                cursor_home,
                app_support=app_support,
                target=str(parent_path),
                reconcile=False,
            )
            subagents = importer.subagents_payload(cursor_home, "parent-1", profile="default")

            self.assertIsNotNone(subagents)
            assert subagents is not None
            self.assertEqual([item["session_id"] for item in subagents], ["child-1"])
            child_summary = importer.summary_payload(cursor_home, "child-1", profile="default")
            self.assertIsNotNone(child_summary)
            assert child_summary is not None
            self.assertTrue(child_summary["is_subagent"])
            self.assertEqual(child_summary["parent_session_id"], "parent-1")

    def test_reconcile_pending_uses_split_app_support(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cursor_home = root / ".cursor"
            app_support = root / "split-user-data"
            db_path = importer.resolve_db_path(cursor_home)
            db.write_pending_marker(
                db_path,
                "session-1",
                {
                    "marker_kind": "reconcile",
                    "session_id": "session-1",
                    "target": "session-1",
                    "retryable": True,
                },
            )
            captured: list[Path | None] = []
            original_refresh = importer.refresh_sessions

            def fake_refresh_sessions(
                cursor_home_arg: Path,
                *,
                app_support: Path | None = None,
                **_: object,
            ) -> dict[str, object]:
                self.assertEqual(cursor_home_arg, cursor_home)
                captured.append(app_support)
                return {}

            importer.refresh_sessions = fake_refresh_sessions
            try:
                reconciled = importer.reconcile_pending(cursor_home, app_support=app_support)
            finally:
                importer.refresh_sessions = original_refresh

            self.assertEqual(reconciled, ["session-1"])
            self.assertEqual(captured, [app_support])


def write_state_db(path: Path, *, include_child: bool = False) -> None:
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    headers = [{"composerId": "composer-1", "name": "Fixture Composer"}]
    composers = [
        {
            "_v": 14,
            "composerId": "composer-1",
            "name": "Fixture Composer",
            "createdAt": 1770000000000,
            "lastUpdatedAt": 1770000001000,
            "unifiedMode": "agent",
            "modelConfig": {"modelName": "composer-2", "selectedModels": ["composer-2"]},
            "usageData": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
            "workspaceIdentifier": {"id": "workspace", "uri": {"fsPath": "/tmp/project"}},
            "subagentComposerIds": ["child-1"] if include_child else [],
            "fullConversationHeadersOnly": [
                {"bubbleId": "u1", "type": 1, "grouping": {}},
                {
                    "bubbleId": "a1",
                    "type": 2,
                    "grouping": {
                        "toolCallId": "tool-1",
                        "turnDurationMs": 25,
                        "thinkingDurationMs": 3,
                        "capabilityType": 15,
                        "isRenderable": True,
                    },
                },
            ],
        }
    ]
    if include_child:
        headers.append({"composerId": "child-1", "name": "Child Composer"})
        composers.append(
            {
                "_v": 14,
                "composerId": "child-1",
                "name": "Child Composer",
                "createdAt": 1770000000001,
                "lastUpdatedAt": 1770000001001,
                "modelConfig": {"modelName": "composer-2-fast"},
                "fullConversationHeadersOnly": [
                    {"bubbleId": "cu1", "type": 1, "grouping": {}},
                ],
            }
        )
        conn.execute(
            "INSERT INTO cursorDiskKV(key, value) VALUES(?, ?)",
            ("bubbleId:child-1:cu1", json.dumps({"_v": 3, "bubbleId": "cu1", "type": 1, "text": "child task"}).encode()),
        )
    conn.execute(
        "INSERT INTO ItemTable(key, value) VALUES(?, ?)",
        ("composer.composerHeaders", json.dumps({"allComposers": headers}).encode()),
    )
    conn.execute("INSERT INTO ItemTable(key, value) VALUES(?, ?)", ("composer.planRegistry", json.dumps({}).encode()))
    for composer in composers:
        conn.execute(
            "INSERT INTO cursorDiskKV(key, value) VALUES(?, ?)",
            (f"composerData:{composer['composerId']}", json.dumps(composer).encode()),
        )
    conn.execute(
        "INSERT INTO cursorDiskKV(key, value) VALUES(?, ?)",
        ("bubbleId:composer-1:u1", json.dumps({"_v": 3, "bubbleId": "u1", "type": 1, "text": "hello"}).encode()),
    )
    conn.execute(
        "INSERT INTO cursorDiskKV(key, value) VALUES(?, ?)",
        (
            "bubbleId:composer-1:a1",
            json.dumps(
                {
                    "_v": 3,
                    "bubbleId": "a1",
                    "type": 2,
                    "requestId": "req-1",
                    "text": "world",
                    "tokenCount": {"inputTokens": 4, "outputTokens": 2},
                    "toolResults": [{"toolName": "Shell", "command": "echo ok"}],
                    "allThinkingBlocks": [{"text": "think"}],
                }
            ).encode(),
        ),
    )
    conn.commit()
    conn.close()


def write_store_db(path: Path) -> None:
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB)")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    user_id = "11" * 32
    assistant_id = "22" * 32
    root_id = "33" * 32
    meta = {
        "agentId": "agent-1",
        "latestRootBlobId": root_id,
        "name": "Fixture Agent",
        "mode": "auto-run",
        "createdAt": 1770000000000,
        "lastUsedModel": "composer-2",
    }
    conn.execute("INSERT INTO meta(key, value) VALUES('0', ?)", (json.dumps(meta).encode().hex(),))
    conn.execute("INSERT INTO blobs(id, data) VALUES(?, ?)", (user_id, json.dumps({"role": "user", "content": "cli hello"}).encode()))
    conn.execute("INSERT INTO blobs(id, data) VALUES(?, ?)", (assistant_id, json.dumps({"role": "assistant", "content": "cli world"}).encode()))
    conn.execute("INSERT INTO blobs(id, data) VALUES(?, ?)", (root_id, b"\x0a\x20" + bytes.fromhex(user_id) + b"\x0a\x20" + bytes.fromhex(assistant_id)))
    conn.commit()
    conn.close()


def write_transcript(path: Path) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"role": "user", "message": {"content": [{"type": "text", "text": "transcript hello"}]}},
                {"role": "assistant", "message": {"content": [{"type": "text", "text": "transcript world"}]}},
            ]
        )
        + "\n",
        encoding="utf-8",
    )


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
