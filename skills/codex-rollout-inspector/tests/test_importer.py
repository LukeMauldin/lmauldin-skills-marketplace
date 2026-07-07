from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "scripts" / "db.py"
IMPORTER_PATH = ROOT / "scripts" / "importer.py"

THREAD_ID = "019d2494-6c37-7c93-9df6-7ed84372b136"
CHILD_THREAD_ID = "019d2494-6c37-7c93-9df6-7ed84372b137"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


db = load_module("test_codex_importer_db", DB_PATH)
importer = load_module("test_codex_importer_runtime", IMPORTER_PATH)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class CodexImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.codex_home = self.root / ".codex"
        self.sessions_dir = self.codex_home / "sessions" / "2026" / "04" / "06"
        self.sessions_dir.mkdir(parents=True)
        self.rollout_path = self.sessions_dir / f"rollout-2026-04-06T12-00-00-{THREAD_ID}.jsonl"
        self.child_rollout_path = self.sessions_dir / f"rollout-2026-04-06T12-10-00-{CHILD_THREAD_ID}.jsonl"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_refresh_populates_db_and_summary_queries(self) -> None:
        self.write_rollouts()

        result = importer.refresh_rollouts(self.codex_home)

        self.assertEqual(result["imported"], 2)
        with closing(db.open_db(importer.resolve_db_path(self.codex_home))) as conn:
            session_count = conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]
            link_count = conn.execute("SELECT COUNT(*) AS count FROM subagent_links").fetchone()["count"]
            pr_count = conn.execute("SELECT COUNT(*) AS count FROM pr_links").fetchone()["count"]
            first_task = conn.execute(
                """
                SELECT first_task
                FROM subagent_links
                WHERE parent_session_id = ? AND child_session_id = ?
                """,
                (THREAD_ID, CHILD_THREAD_ID),
            ).fetchone()["first_task"]
            tool_call_files = conn.execute(
                """
                SELECT file_path
                FROM tool_call_files
                ORDER BY file_path
                """
            ).fetchall()
            tool_rows = conn.execute(
                """
                SELECT tool_name, command, file_path
                FROM tool_calls
                ORDER BY id
                """
            ).fetchall()
        self.assertEqual(session_count, 2)
        self.assertEqual(link_count, 1)
        self.assertEqual(pr_count, 1)
        self.assertEqual(first_task, "child task")
        self.assertEqual([dict(row) for row in tool_call_files], [{"file_path": "main.go"}])
        self.assertEqual(
            [dict(row) for row in tool_rows],
            [
                {
                    "tool_name": "exec_command",
                    "command": "go test ./...",
                    "file_path": None,
                },
                {
                    "tool_name": "apply_patch",
                    "command": None,
                    "file_path": "main.go",
                },
            ],
        )

        summary = importer.summary_payload(self.codex_home, THREAD_ID, profile="default")
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["raw_first_user_message"], "run the failing command")
        self.assertIsNone(summary["delegated_task"])
        self.assertEqual(summary["tool_error_count"], 1)
        self.assertEqual(summary["tool_usage"]["tool_error_count"], 1)
        self.assertEqual(summary["subagents"]["count"], 1)
        self.assertEqual(summary["pr_links"][0], "https://github.com/example/repo/pull/44")

        subagents = importer.subagents_payload(self.codex_home, THREAD_ID, profile="default")
        self.assertIsInstance(subagents, list)
        assert isinstance(subagents, list)
        self.assertEqual(len(subagents), 1)
        self.assertEqual(subagents[0]["thread_id"], CHILD_THREAD_ID)
        self.assertEqual(subagents[0]["raw_first_user_message"], "run the failing command")
        self.assertEqual(subagents[0]["delegated_task"], "child task")

    def test_refresh_skips_unchanged_and_reimports_on_change(self) -> None:
        self.write_rollouts(include_child=False)

        first = importer.refresh_rollouts(self.codex_home, archived=False)
        second = importer.refresh_rollouts(self.codex_home, archived=False)
        self.write_rollouts(include_child=False, token_total=300)
        third = importer.refresh_rollouts(self.codex_home, archived=False)

        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(third["imported"], 1)

    def test_user_messages_extracted(self) -> None:
        self.write_rollouts(include_child=False)

        importer.refresh_rollouts(self.codex_home, archived=False)

        with closing(db.open_db(importer.resolve_db_path(self.codex_home))) as conn:
            rows = conn.execute(
                """
                SELECT message_index, is_first, is_interrupt, word_count, char_count, preceding_turn_index
                FROM user_messages
                WHERE session_id = ?
                ORDER BY message_index
                """,
                (THREAD_ID,),
            ).fetchall()

        self.assertEqual(
            [dict(row) for row in rows],
            [
                {
                    "message_index": 1,
                    "is_first": 1,
                    "is_interrupt": 0,
                    "word_count": 4,
                    "char_count": 23,
                    "preceding_turn_index": None,
                },
                {
                    "message_index": 2,
                    "is_first": 0,
                    "is_interrupt": 1,
                    "word_count": 3,
                    "char_count": 20,
                    "preceding_turn_index": 1,
                },
            ],
        )

    def test_tool_call_order_sequential(self) -> None:
        self.write_rollouts(include_child=False)

        importer.refresh_rollouts(self.codex_home, archived=False)

        with closing(db.open_db(importer.resolve_db_path(self.codex_home))) as conn:
            rows = conn.execute(
                """
                SELECT tool_name, call_order
                FROM tool_calls
                WHERE session_id = ?
                ORDER BY call_order
                """,
                (THREAD_ID,),
            ).fetchall()

        self.assertEqual(
            [dict(row) for row in rows],
            [
                {"tool_name": "exec_command", "call_order": 1},
                {"tool_name": "apply_patch", "call_order": 2},
            ],
        )

    def test_reasoning_tokens_on_session(self) -> None:
        self.write_rollouts(include_child=False)

        importer.refresh_rollouts(self.codex_home, archived=False)

        with closing(db.open_db(importer.resolve_db_path(self.codex_home))) as conn:
            session_row = conn.execute(
                """
                SELECT total_reasoning_tokens
                FROM sessions
                WHERE session_id = ?
                """,
                (THREAD_ID,),
            ).fetchone()
            turn_row = conn.execute(
                """
                SELECT input_tokens, cached_input_tokens, output_tokens, total_tokens, reasoning_output_tokens
                FROM turns
                WHERE session_id = ?
                ORDER BY turn_index
                """,
                (THREAD_ID,),
            ).fetchone()

        self.assertEqual(session_row["total_reasoning_tokens"], 30)
        self.assertEqual(
            dict(turn_row),
            {
                "input_tokens": 100,
                "cached_input_tokens": 25,
                "output_tokens": 100,
                "total_tokens": 200,
                "reasoning_output_tokens": 30,
            },
        )

    def test_token_usage_events_persisted(self) -> None:
        self.write_rollouts(include_child=False)

        importer.refresh_rollouts(self.codex_home, archived=False)

        with closing(db.open_db(importer.resolve_db_path(self.codex_home))) as conn:
            rows = conn.execute(
                """
                SELECT
                    turn_index,
                    timestamp,
                    raw_model,
                    model_provider,
                    model_context_window,
                    usage_source,
                    is_approximate,
                    input_tokens,
                    cached_input_tokens,
                    output_tokens,
                    reasoning_output_tokens,
                    total_tokens,
                    cumulative_input_tokens,
                    cumulative_cached_input_tokens,
                    cumulative_output_tokens,
                    cumulative_reasoning_output_tokens,
                    cumulative_total_tokens
                FROM token_usage_events
                WHERE session_id = ?
                ORDER BY id
                """,
                (THREAD_ID,),
            ).fetchall()

        self.assertEqual(
            [dict(row) for row in rows],
            [
                {
                    "turn_index": 1,
                    "timestamp": "2026-04-06T12:00:06Z",
                    "raw_model": "gpt-5-codex",
                    "model_provider": "openai",
                    "model_context_window": 258400,
                    "usage_source": "last_token_usage",
                    "is_approximate": 0,
                    "input_tokens": 100,
                    "cached_input_tokens": 25,
                    "output_tokens": 100,
                    "reasoning_output_tokens": 30,
                    "total_tokens": 200,
                    "cumulative_input_tokens": 100,
                    "cumulative_cached_input_tokens": 25,
                    "cumulative_output_tokens": 100,
                    "cumulative_reasoning_output_tokens": 30,
                    "cumulative_total_tokens": 200,
                }
            ],
        )

    def test_reasoning_items_persisted(self) -> None:
        self.write_rollouts(include_child=False)

        importer.refresh_rollouts(self.codex_home, archived=False)

        with closing(db.open_db(importer.resolve_db_path(self.codex_home))) as conn:
            rows = conn.execute(
                """
                SELECT
                    block_type,
                    is_redacted,
                    content_length,
                    encrypted_content_length,
                    summary_item_count,
                    has_plaintext_content
                FROM reasoning_items
                ORDER BY id
                """
            ).fetchall()
            session_row = conn.execute(
                """
                SELECT total_reasoning_items, total_encrypted_reasoning_items, total_reasoning_content_len
                FROM sessions
                WHERE session_id = ?
                """,
                (THREAD_ID,),
            ).fetchone()
            turn_row = conn.execute(
                """
                SELECT reasoning_item_count
                FROM turns
                WHERE session_id = ?
                ORDER BY turn_index
                """,
                (THREAD_ID,),
            ).fetchone()

        self.assertEqual(
            [dict(row) for row in rows],
            [
                {
                    "block_type": "reasoning",
                    "is_redacted": 1,
                    "content_length": 12,
                    "encrypted_content_length": 12,
                    "summary_item_count": 1,
                    "has_plaintext_content": 0,
                },
                {
                    "block_type": "reasoning",
                    "is_redacted": 0,
                    "content_length": 15,
                    "encrypted_content_length": 6,
                    "summary_item_count": 0,
                    "has_plaintext_content": 1,
                },
            ],
        )
        self.assertEqual(
            dict(session_row),
            {
                "total_reasoning_items": 2,
                "total_encrypted_reasoning_items": 2,
                "total_reasoning_content_len": 27,
            },
        )
        self.assertEqual(turn_row["reasoning_item_count"], 2)

    def test_refreshing_child_target_imports_parent_tree(self) -> None:
        self.write_rollouts()

        result = importer.refresh_rollouts(self.codex_home, target=CHILD_THREAD_ID, archived=False)

        self.assertEqual(result["imported"], 2)
        with closing(db.open_db(importer.resolve_db_path(self.codex_home))) as conn:
            session_count = conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]
            link_count = conn.execute("SELECT COUNT(*) AS count FROM subagent_links").fetchone()["count"]
        self.assertEqual(session_count, 2)
        self.assertEqual(link_count, 1)

    def test_parent_reimport_replaces_orphan_child_session(self) -> None:
        self.write_rollouts()
        parser = importer._load_parser()
        paths = parser.resolve_paths(self.codex_home)
        thread_names = parser.load_session_index(paths.session_index_path)

        with closing(db.open_db(importer.resolve_db_path(self.codex_home))) as conn:
            child_result = importer.import_rollout_tree(
                conn,
                self.child_rollout_path,
                paths,
                parser,
                thread_names,
            )
            conn.commit()
            parent_result = importer.import_rollout_tree(
                conn,
                self.rollout_path,
                paths,
                parser,
                thread_names,
            )
            conn.commit()
            session_rows = conn.execute(
                """
                SELECT session_id, parent_session_id
                FROM sessions
                ORDER BY session_id
                """
            ).fetchall()
            link_rows = conn.execute(
                """
                SELECT parent_session_id, child_session_id
                FROM subagent_links
                ORDER BY child_session_id
                """
            ).fetchall()

        self.assertEqual(child_result, {"imported": 1, "skipped": 0})
        self.assertEqual(parent_result, {"imported": 2, "skipped": 0})
        self.assertEqual(
            [dict(row) for row in session_rows],
            [
                {"session_id": THREAD_ID, "parent_session_id": None},
                {"session_id": CHILD_THREAD_ID, "parent_session_id": THREAD_ID},
            ],
        )
        self.assertEqual(
            [dict(row) for row in link_rows],
            [{"parent_session_id": THREAD_ID, "child_session_id": CHILD_THREAD_ID}],
        )

    def write_rollouts(self, *, include_child: bool = True, token_total: int = 200) -> None:
        write_jsonl(
            self.rollout_path,
            [
                {
                    "timestamp": "2026-04-06T12:00:00Z",
                    "type": "session_meta",
                    "payload": {
                        "cwd": "/tmp/demo-project",
                        "timestamp": "2026-04-06T12:00:00Z",
                        "model_provider": "openai",
                        "cli_version": "1.2.3",
                        "git": {"branch": "main", "commit_hash": "abc123"},
                        "source": {},
                    },
                },
                {
                    "timestamp": "2026-04-06T12:00:01Z",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "run the failing command"},
                },
                {
                    "timestamp": "2026-04-06T12:00:02Z",
                    "type": "turn_context",
                    "payload": {"cwd": "/tmp/demo-project", "model": "gpt-5-codex"},
                },
                {
                    "timestamp": "2026-04-06T12:00:03Z",
                    "type": "event_msg",
                    "payload": {"type": "task_started", "turn_id": "turn-1"},
                },
                {
                    "timestamp": "2026-04-06T12:00:04Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "name": "exec_command",
                        "call_id": "call-1",
                        "arguments": json.dumps({"cmd": "go test ./..."}),
                    },
                },
                {
                    "timestamp": "2026-04-06T12:00:04.500Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call",
                        "name": "apply_patch",
                        "call_id": "call-2",
                        "input": "*** Begin Patch\n*** Update File: main.go\n@@\n-hello\n+hello world\n*** End Patch\n",
                    },
                },
                {
                    "timestamp": "2026-04-06T12:00:05Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call_output",
                        "call_id": "call-1",
                        "output": {"content": "permission denied", "success": False},
                    },
                },
                {
                    "timestamp": "2026-04-06T12:00:05.500Z",
                    "type": "response_item",
                    "payload": {
                        "type": "custom_tool_call_output",
                        "call_id": "call-2",
                        "output": {"content": "patched", "success": True},
                    },
                },
                {
                    "timestamp": "2026-04-06T12:00:05.700Z",
                    "type": "response_item",
                    "payload": {
                        "type": "reasoning",
                        "summary": [{"text": "inspect failure"}],
                        "content": None,
                        "encrypted_content": "secret-bytes",
                    },
                },
                {
                    "timestamp": "2026-04-06T12:00:05.800Z",
                    "type": "response_item",
                    "payload": {
                        "type": "reasoning",
                        "summary": [],
                        "content": "plain reasoning",
                        "encrypted_content": "cipher",
                    },
                },
                {
                    "timestamp": "2026-04-06T12:00:06Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "model_context_window": 258400,
                            "total_token_usage": {
                                "input_tokens": 100,
                                "cached_input_tokens": 25,
                                "output_tokens": 100,
                                "reasoning_output_tokens": 30,
                                "total_tokens": token_total,
                            },
                            "last_token_usage": {
                                "input_tokens": 100,
                                "cached_input_tokens": 25,
                                "output_tokens": 100,
                                "reasoning_output_tokens": 30,
                                "total_tokens": token_total,
                            },
                        },
                    },
                },
                {
                    "timestamp": "2026-04-06T12:00:06.500Z",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "please patch main.go"},
                },
                {
                    "timestamp": "2026-04-06T12:00:07Z",
                    "type": "event_msg",
                    "payload": {"type": "task_complete", "turn_id": "turn-1"},
                },
                {
                    "timestamp": "2026-04-06T12:00:08Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "See https://github.com/example/repo/pull/44"}],
                    },
                },
            ],
        )
        write_jsonl(
            self.codex_home / "session_index.jsonl",
            [
                {"id": THREAD_ID, "thread_name": "Parent rollout"},
                {"id": CHILD_THREAD_ID, "thread_name": "Child rollout"},
            ],
        )
        if include_child:
            write_jsonl(
                self.child_rollout_path,
                [
                    {
                        "timestamp": "2026-04-06T12:10:00Z",
                        "type": "session_meta",
                        "payload": {
                            "cwd": "/tmp/demo-project",
                            "timestamp": "2026-04-06T12:10:00Z",
                            "model_provider": "openai",
                            "cli_version": "1.2.3",
                            "forked_from_id": THREAD_ID,
                            "source": {},
                            "agent_nickname": "worker",
                            "agent_role": "implementation",
                            "agent_path": "repo/tests",
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:10:01Z",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "run the failing command"},
                    },
                    {
                        "timestamp": "2026-04-06T12:10:01.500Z",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "child task"},
                    },
                    {
                        "timestamp": "2026-04-06T12:10:02Z",
                        "type": "turn_context",
                        "payload": {"cwd": "/tmp/demo-project", "model": "gpt-5-mini"},
                    },
                ],
            )


if __name__ == "__main__":
    unittest.main()
