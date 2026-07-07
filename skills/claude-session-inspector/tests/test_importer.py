from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "scripts" / "db.py"
IMPORTER_PATH = ROOT / "scripts" / "importer.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


db = load_module("test_claude_importer_db", DB_PATH)
importer = load_module("test_claude_importer_runtime", IMPORTER_PATH)


class ClaudeImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.claude_home = self.root / ".claude"
        self.projects_dir = self.claude_home / "projects"
        self.project_name = "-Users-test-code-demo-repo"
        self.project_dir = self.projects_dir / self.project_name
        self.project_dir.mkdir(parents=True)
        self.session_id = "11111111-1111-1111-1111-111111111111"
        self.session_path = self.project_dir / f"{self.session_id}.jsonl"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_refresh_populates_db_and_subagent_queries(self) -> None:
        self.write_parent_session(with_subagent=True)

        result = importer.refresh_sessions(self.claude_home)

        self.assertEqual(result["imported"], 2)
        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            session_count = conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"]
            link_count = conn.execute("SELECT COUNT(*) AS count FROM subagent_links").fetchone()["count"]
            pr_count = conn.execute("SELECT COUNT(*) AS count FROM pr_links").fetchone()["count"]
        self.assertEqual(session_count, 2)
        self.assertEqual(link_count, 1)
        self.assertEqual(pr_count, 1)

        summary = importer.summary_payload(self.claude_home, self.session_id, profile="default")
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["tool_error_count"], 1)
        self.assertEqual(summary["hook_summary"]["count"], 2)
        self.assertEqual(summary["pr_links"][0]["prNumber"], 12)

        subagents = importer.subagents_payload(self.claude_home, self.session_id, profile="default")
        self.assertIsInstance(subagents, list)
        assert isinstance(subagents, list)
        self.assertEqual(len(subagents), 1)
        self.assertEqual(subagents[0]["agent_id"], "abc123")
        self.assertEqual(subagents[0]["parent_session_id"], self.session_id)

    def test_refresh_skips_unchanged_and_reimports_on_change(self) -> None:
        self.write_parent_session(with_subagent=False)

        first = importer.refresh_sessions(self.claude_home)
        second = importer.refresh_sessions(self.claude_home)
        self.write_jsonl(
            self.session_path,
            [
                {
                    "type": "user",
                    "parentUuid": None,
                    "sessionId": self.session_id,
                    "timestamp": "2026-04-01T10:00:00Z",
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
            ],
        )
        third = importer.refresh_sessions(self.claude_home)

        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(third["imported"], 1)

    def test_usage_speed_persisted_to_turns(self) -> None:
        """usage.speed from the assistant message is captured into turns.speed."""
        self.write_jsonl(
            self.session_path,
            [
                {
                    "type": "user",
                    "parentUuid": None,
                    "sessionId": self.session_id,
                    "timestamp": "2026-05-28T10:00:00Z",
                    "message": {"content": "hello"},
                },
                {
                    "type": "assistant",
                    "requestId": "req-fast",
                    "timestamp": "2026-05-28T10:00:01Z",
                    "message": {
                        "id": "msg-fast",
                        "model": "claude-opus-4-8",
                        "stop_reason": "end_turn",
                        "content": [],
                        "usage": {"input_tokens": 10, "output_tokens": 5, "speed": "fast"},
                    },
                },
                {
                    "type": "assistant",
                    "requestId": "req-std",
                    "timestamp": "2026-05-28T10:00:02Z",
                    "message": {
                        "id": "msg-std",
                        "model": "claude-opus-4-8",
                        "stop_reason": "end_turn",
                        "content": [],
                        "usage": {"input_tokens": 10, "output_tokens": 5, "speed": "standard"},
                    },
                },
            ],
        )

        importer.refresh_sessions(self.claude_home)

        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            speeds = [
                row["speed"]
                for row in conn.execute(
                    "SELECT speed FROM turns ORDER BY turn_index"
                ).fetchall()
            ]
        self.assertEqual(speeds, ["fast", "standard"])

    def test_reconcile_pending_ignores_cwd_project_scope_for_retryable_uuid_targets(self) -> None:
        self.project_name = "-Users-test-code-github-com-demo-repo"
        self.project_dir = self.projects_dir / self.project_name
        self.project_dir.mkdir(parents=True)
        self.session_path = self.project_dir / f"{self.session_id}.jsonl"
        self.write_parent_session(with_subagent=False)

        db.write_pending_marker(
            importer.resolve_db_path(self.claude_home),
            self.session_id,
            {
                "session_id": self.session_id,
                "target": self.session_id,
                "project": "/Users/test/code/github.com/demo/repo",
                "cwd": "/Users/test/code/github.com/demo/repo",
                "marker_kind": "reconcile",
                "retryable": True,
            },
        )

        reconciled = importer.reconcile_pending(self.claude_home)

        self.assertEqual(reconciled, [self.session_id])
        self.assertEqual(
            list(db.pending_dir(importer.resolve_db_path(self.claude_home)).glob("*.json")),
            [],
        )
        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            row = conn.execute(
                "SELECT session_id FROM sessions WHERE session_id = ?",
                (self.session_id,),
            ).fetchone()
        self.assertIsNotNone(row)

    def test_thinking_blocks_persisted(self) -> None:
        self.write_parent_session(with_subagent=False)

        importer.refresh_sessions(self.claude_home)

        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            rows = conn.execute(
                """
                SELECT session_id, block_index, is_redacted, content_length, signature_length, has_signature
                FROM thinking_blocks
                ORDER BY id
                """
            ).fetchall()

        self.assertEqual(
            [dict(row) for row in rows],
            [
                {
                    "session_id": self.session_id,
                    "block_index": 1,
                    "is_redacted": 0,
                    "content_length": 20,
                    "signature_length": 5,
                    "has_signature": 1,
                },
                {
                    "session_id": self.session_id,
                    "block_index": 1,
                    "is_redacted": 1,
                    "content_length": 0,
                    "signature_length": 5,
                    "has_signature": 1,
                },
            ],
        )

    def test_user_messages_persisted(self) -> None:
        self.write_parent_session(with_subagent=False)

        importer.refresh_sessions(self.claude_home)

        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            rows = conn.execute(
                """
                SELECT message_index, is_first, is_interrupt, word_count, char_count, preceding_turn_index
                FROM user_messages
                WHERE session_id = ?
                ORDER BY message_index
                """,
                (self.session_id,),
            ).fetchall()

        self.assertEqual(
            [dict(row) for row in rows],
            [
                {
                    "message_index": 1,
                    "is_first": 1,
                    "is_interrupt": 0,
                    "word_count": 4,
                    "char_count": 25,
                    "preceding_turn_index": None,
                },
                {
                    "message_index": 2,
                    "is_first": 0,
                    "is_interrupt": 0,
                    "word_count": 7,
                    "char_count": 31,
                    "preceding_turn_index": 1,
                },
            ],
        )

    def test_tool_call_order_sequential(self) -> None:
        self.write_parent_session(with_subagent=False)

        importer.refresh_sessions(self.claude_home)

        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            rows = conn.execute(
                """
                SELECT tool_name, call_order
                FROM tool_calls
                WHERE session_id = ?
                ORDER BY call_order
                """,
                (self.session_id,),
            ).fetchall()

        self.assertEqual(
            [dict(row) for row in rows],
            [
                {"tool_name": "Read", "call_order": 1},
                {"tool_name": "Bash", "call_order": 2},
            ],
        )

    def test_session_aggregates_include_new_columns(self) -> None:
        self.write_parent_session(with_subagent=False)

        importer.refresh_sessions(self.claude_home)

        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            row = conn.execute(
                """
                SELECT
                    total_thinking_blocks,
                    total_redacted_blocks,
                    total_thinking_content_len,
                    total_reasoning_tokens,
                    user_message_count,
                    user_interrupt_count,
                    total_user_char_count
                FROM sessions
                WHERE session_id = ?
                """,
                (self.session_id,),
            ).fetchone()

        self.assertEqual(
            dict(row),
            {
                "total_thinking_blocks": 2,
                "total_redacted_blocks": 1,
                "total_thinking_content_len": 20,
                "total_reasoning_tokens": 0,
                "user_message_count": 2,
                "user_interrupt_count": 0,
                "total_user_char_count": 56,
            },
        )

    def test_schema_v2_rebuild(self) -> None:
        db_path = importer.resolve_db_path(self.claude_home)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_version (
                  version INTEGER NOT NULL
                );
                INSERT INTO schema_version(version) VALUES (1);

                CREATE TABLE sessions (
                  session_id TEXT PRIMARY KEY,
                  source TEXT NOT NULL,
                  file_path TEXT NOT NULL,
                  project TEXT,
                  cwd TEXT,
                  title TEXT,
                  display_name TEXT,
                  model TEXT,
                  git_branch TEXT,
                  git_commit TEXT,
                  version TEXT,
                  first_user_message TEXT,
                  start_timestamp TEXT,
                  archived INTEGER DEFAULT 0,
                  is_subagent INTEGER DEFAULT 0,
                  parent_session_id TEXT,
                  forked_from_id TEXT,
                  agent_nickname TEXT,
                  agent_role TEXT,
                  record_count INTEGER DEFAULT 0,
                  parse_errors INTEGER DEFAULT 0,
                  turn_count INTEGER DEFAULT 0,
                  completed_turn_count INTEGER DEFAULT 0,
                  total_turn_duration_ms INTEGER DEFAULT 0,
                  total_input_tokens INTEGER DEFAULT 0,
                  total_output_tokens INTEGER DEFAULT 0,
                  total_cache_read INTEGER DEFAULT 0,
                  total_cache_create INTEGER DEFAULT 0,
                  tool_call_count INTEGER DEFAULT 0,
                  tool_error_count INTEGER DEFAULT 0,
                  api_error_count INTEGER DEFAULT 0,
                  max_tokens_stops INTEGER DEFAULT 0,
                  total_hook_ms INTEGER DEFAULT 0,
                  models_used TEXT,
                  imported_at TEXT,
                  slug TEXT,
                  custom_title TEXT,
                  agent_name TEXT,
                  permission_mode TEXT,
                  entrypoint TEXT,
                  api_call_count INTEGER,
                  thread_name TEXT,
                  filename_timestamp TEXT,
                  model_provider TEXT,
                  token_mode TEXT,
                  record_counts_json TEXT,
                  system_subtypes_json TEXT,
                  event_counts_json TEXT,
                  response_item_counts_json TEXT,
                  session_meta_json TEXT,
                  git_json TEXT,
                  latest_turn_context_json TEXT,
                  token_usage_json TEXT,
                  tool_usage_json TEXT,
                  turn_durations_json TEXT,
                  current_subagent_json TEXT
                );

                CREATE TABLE turns (
                  id INTEGER PRIMARY KEY,
                  session_id TEXT NOT NULL,
                  turn_index INTEGER NOT NULL,
                  message_id TEXT,
                  timestamp TEXT,
                  model TEXT,
                  stop_reason TEXT,
                  duration_ms INTEGER,
                  user_gap_ms INTEGER,
                  input_tokens INTEGER DEFAULT 0,
                  output_tokens INTEGER DEFAULT 0,
                  cache_read INTEGER DEFAULT 0,
                  cache_create INTEGER DEFAULT 0
                );

                CREATE TABLE tool_calls (
                  id INTEGER PRIMARY KEY,
                  turn_id INTEGER NOT NULL,
                  session_id TEXT NOT NULL,
                  tool_name TEXT NOT NULL,
                  tool_use_id TEXT,
                  file_path TEXT,
                  command TEXT,
                  is_error INTEGER DEFAULT 0,
                  error_text TEXT,
                  call_type TEXT,
                  call_id TEXT
                );
                """
            )

        with db.open_db(db_path) as conn:
            table_names = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            turns_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(turns)").fetchall()
            }

        self.assertIn("thinking_blocks", table_names)
        self.assertIn("user_messages", table_names)
        self.assertIn("reasoning_output_tokens", turns_columns)

    def write_parent_session(self, *, with_subagent: bool) -> None:
        self.write_jsonl(
            self.session_path,
            [
                {
                    "type": "user",
                    "parentUuid": None,
                    "sessionId": self.session_id,
                    "cwd": "/Users/test/code/demo-repo",
                    "version": "1.0.0",
                    "gitBranch": "main",
                    "permissionMode": "plan",
                    "entrypoint": "cli",
                    "timestamp": "2026-04-01T10:00:00Z",
                    "message": {"content": "Investigate a parsing bug"},
                },
                {
                    "type": "assistant",
                    "requestId": "req-1",
                    "timestamp": "2026-04-01T10:00:05Z",
                    "message": {
                        "id": "msg-1",
                        "model": "claude-sonnet-4-5",
                        "stop_reason": "tool_use",
                        "content": [
                            {"type": "text", "text": "I'll inspect app.py"},
                            {
                                "type": "thinking",
                                "thinking": "Inspect parser state",
                                "signature": "sig-1",
                            },
                            {
                                "type": "tool_use",
                                "id": "tool-1",
                                "name": "Read",
                                "input": {"file_path": "app.py"},
                            }
                        ],
                        "usage": {
                            "input_tokens": 110,
                            "output_tokens": 45,
                            "cache_creation_input_tokens": 10,
                            "cache_read_input_tokens": 5,
                        },
                    },
                },
                {
                    "type": "user",
                    "timestamp": "2026-04-01T10:00:06Z",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "tool-1",
                                "is_error": False,
                                "content": "file contents",
                            }
                        ]
                    },
                },
                {
                    "type": "system",
                    "subtype": "turn_duration",
                    "timestamp": "2026-04-01T10:00:06Z",
                    "durationMs": 1200,
                },
                {
                    "type": "user",
                    "timestamp": "2026-04-01T10:01:09Z",
                    "message": {"content": "Now check the TODOs in the repo"},
                },
                {
                    "type": "assistant",
                    "requestId": "req-2",
                    "timestamp": "2026-04-01T10:01:10Z",
                    "message": {
                        "id": "msg-2",
                        "model": "claude-sonnet-4-5",
                        "stop_reason": "max_tokens",
                        "content": [
                            {"type": "text", "text": "I need to search the repo"},
                            {
                                "type": "thinking",
                                "thinking": "",
                                "signature": "sig-2",
                            },
                            {
                                "type": "tool_use",
                                "id": "tool-2",
                                "name": "Bash",
                                "input": {"command": "rg todo"},
                            }
                        ],
                        "usage": {
                            "input_tokens": 50,
                            "output_tokens": 60,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 10,
                        },
                    },
                },
                {
                    "type": "user",
                    "timestamp": "2026-04-01T10:01:11Z",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "tool-2",
                                "is_error": True,
                                "content": [{"type": "text", "text": "command failed"}],
                            }
                        ]
                    },
                },
                {
                    "type": "system",
                    "subtype": "hook_summary",
                    "hookInfos": [
                        {"command": "lint", "durationMs": 250},
                        {"command": "format", "durationMs": 100},
                    ],
                    "hookErrors": [{"command": "lint"}],
                },
                {
                    "type": "system",
                    "subtype": "turn_duration",
                    "timestamp": "2026-04-01T10:01:11Z",
                    "durationMs": 2000,
                },
                {"type": "custom-title", "customTitle": "Bug Investigation"},
                {"type": "agent-name", "agentName": "Inspector"},
                {
                    "type": "pr-link",
                    "prNumber": 12,
                    "prUrl": "https://example.com/pr/12",
                    "prRepository": "example/repo",
                },
            ],
        )
        if with_subagent:
            subagent_dir = self.project_dir / self.session_id / "subagents"
            subagent_dir.mkdir(parents=True)
            self.write_jsonl(
                subagent_dir / "agent-abc123.jsonl",
                [
                    {
                        "type": "user",
                        "parentUuid": None,
                        "sessionId": self.session_id,
                        "timestamp": "2026-04-01T10:05:00Z",
                        "message": {"content": "inspect just the subagent work"},
                    },
                    {
                        "type": "assistant",
                        "requestId": "sub-req-1",
                        "timestamp": "2026-04-01T10:05:05Z",
                        "message": {
                            "id": "sub-msg-1",
                            "model": "claude-haiku-4-5",
                            "stop_reason": "end_turn",
                            "content": [],
                            "usage": {
                                "input_tokens": 10,
                                "output_tokens": 5,
                            },
                        },
                    },
                    {
                        "type": "system",
                        "subtype": "turn_duration",
                        "timestamp": "2026-04-01T10:05:06Z",
                        "durationMs": 500,
                    },
                ],
            )

    def write_session_with_server_tools(self) -> None:
        """Write a session with a completed advisor call and an aborted advisor call."""
        self.write_jsonl(
            self.session_path,
            [
                {
                    "type": "user",
                    "parentUuid": None,
                    "sessionId": self.session_id,
                    "cwd": "/Users/test/code/demo-repo",
                    "version": "2.1.92",
                    "timestamp": "2026-04-01T10:00:00Z",
                    "message": {"content": "Help me design a feature"},
                },
                # Turn 1: completed advisor call — emit chunk
                {
                    "type": "assistant",
                    "requestId": "req-1",
                    "timestamp": "2026-04-01T10:00:05Z",
                    "message": {
                        "id": "msg-1",
                        "model": "claude-opus-4-6",
                        "content": [
                            {"type": "text", "text": "Let me consult advisor."},
                            {
                                "type": "server_tool_use",
                                "id": "srvtoolu_001",
                                "name": "advisor",
                                "input": {},
                            },
                        ],
                        "usage": {"input_tokens": 100, "output_tokens": 50},
                    },
                },
                # Turn 1: completed advisor call — result chunk
                {
                    "type": "assistant",
                    "requestId": "req-1",
                    "timestamp": "2026-04-01T10:01:07Z",
                    "message": {
                        "id": "msg-1",
                        "model": "claude-opus-4-6",
                        "stop_reason": "end_turn",
                        "content": [
                            {
                                "type": "advisor_tool_result",
                                "tool_use_id": "srvtoolu_001",
                                "content": "Advisor says: looks good.",
                            },
                            {"type": "text", "text": "Based on the advice..."},
                        ],
                        "usage": {
                            "input_tokens": 200,
                            "output_tokens": 300,
                            "cache_read_input_tokens": 50,
                            "cache_creation_input_tokens": 10,
                            "iterations": [
                                {
                                    "type": "message",
                                    "input_tokens": 1,
                                    "output_tokens": 50,
                                    "cache_read_input_tokens": 50,
                                    "cache_creation_input_tokens": 10,
                                },
                                {
                                    "type": "advisor_message",
                                    "model": "claude-opus-4-6",
                                    "input_tokens": 48000,
                                    "output_tokens": 2500,
                                    "cache_read_input_tokens": 0,
                                    "cache_creation_input_tokens": 0,
                                },
                                {
                                    "type": "message",
                                    "input_tokens": 1,
                                    "output_tokens": 250,
                                    "cache_read_input_tokens": 0,
                                    "cache_creation_input_tokens": 0,
                                },
                            ],
                        },
                    },
                },
                {
                    "type": "system",
                    "subtype": "turn_duration",
                    "timestamp": "2026-04-01T10:01:08Z",
                    "durationMs": 63000,
                },
                # Turn 2: aborted advisor call — only emit, no result, no iterations
                {
                    "type": "assistant",
                    "requestId": "req-2",
                    "timestamp": "2026-04-01T10:02:00Z",
                    "message": {
                        "id": "msg-2",
                        "model": "claude-opus-4-6",
                        "stop_reason": None,
                        "content": [
                            {"type": "thinking", "thinking": "About to call advisor"},
                            {
                                "type": "server_tool_use",
                                "id": "srvtoolu_002",
                                "name": "advisor",
                                "input": {},
                            },
                        ],
                        "usage": {"input_tokens": 300, "output_tokens": 40},
                    },
                },
            ],
        )

    def test_server_tool_calls_persisted(self) -> None:
        self.write_session_with_server_tools()

        importer.refresh_sessions(self.claude_home)

        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            rows = conn.execute(
                """
                SELECT
                    tool_name, tool_use_id, call_order, is_aborted,
                    emit_timestamp, result_timestamp, latency_ms,
                    iteration_type, iteration_model,
                    iteration_input_tokens, iteration_output_tokens
                FROM server_tool_calls
                WHERE session_id = ?
                ORDER BY call_order
                """,
                (self.session_id,),
            ).fetchall()

        self.assertEqual(len(rows), 2)
        # Completed call
        completed = dict(rows[0])
        self.assertEqual(completed["tool_name"], "advisor")
        self.assertEqual(completed["tool_use_id"], "srvtoolu_001")
        self.assertEqual(completed["is_aborted"], 0)
        self.assertEqual(completed["iteration_type"], "advisor_message")
        self.assertEqual(completed["iteration_model"], "claude-opus-4-6")
        self.assertEqual(completed["iteration_input_tokens"], 48000)
        self.assertEqual(completed["iteration_output_tokens"], 2500)
        self.assertIsNotNone(completed["emit_timestamp"])
        self.assertIsNotNone(completed["result_timestamp"])
        self.assertIsNotNone(completed["latency_ms"])
        self.assertGreater(completed["latency_ms"], 0)

        # Aborted call
        aborted = dict(rows[1])
        self.assertEqual(aborted["tool_name"], "advisor")
        self.assertEqual(aborted["tool_use_id"], "srvtoolu_002")
        self.assertEqual(aborted["is_aborted"], 1)
        self.assertIsNone(aborted["latency_ms"])
        self.assertEqual(aborted["iteration_input_tokens"], 0)
        self.assertEqual(aborted["iteration_output_tokens"], 0)

    def test_server_tool_session_aggregates(self) -> None:
        self.write_session_with_server_tools()

        importer.refresh_sessions(self.claude_home)

        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            row = conn.execute(
                """
                SELECT
                    server_tool_call_count,
                    server_tool_aborted_count,
                    server_tool_input_tokens,
                    server_tool_output_tokens,
                    server_tool_total_latency_ms
                FROM sessions
                WHERE session_id = ?
                """,
                (self.session_id,),
            ).fetchone()

        self.assertEqual(row["server_tool_call_count"], 2)
        self.assertEqual(row["server_tool_aborted_count"], 1)
        self.assertEqual(row["server_tool_input_tokens"], 48000)
        self.assertEqual(row["server_tool_output_tokens"], 2500)
        self.assertGreater(row["server_tool_total_latency_ms"], 0)

    def test_server_tool_summary_output(self) -> None:
        self.write_session_with_server_tools()

        importer.refresh_sessions(self.claude_home)

        summary = importer.summary_payload(self.claude_home, self.session_id, profile="default")
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["server_tool_call_count"], 2)
        self.assertEqual(summary["server_tool_aborted_count"], 1)
        self.assertEqual(summary["server_tool_usage"], {"advisor": 2})
        self.assertEqual(summary["server_tool_input_tokens"], 48000)
        self.assertEqual(summary["server_tool_output_tokens"], 2500)

        # Check turn-level server_tool_calls
        turn1 = summary["turns"][0]
        self.assertEqual(len(turn1["server_tool_calls"]), 1)
        self.assertEqual(turn1["server_tool_calls"][0]["name"], "advisor")
        self.assertFalse(turn1["server_tool_calls"][0]["is_aborted"])

        turn2 = summary["turns"][1]
        self.assertEqual(len(turn2["server_tool_calls"]), 1)
        self.assertTrue(turn2["server_tool_calls"][0]["is_aborted"])

    def test_schema_rebuild_migrates_to_current_version(self) -> None:
        """Verify a stale schema rebuilds to the current version, creating the
        server_tool_calls table and the turns.speed column."""
        db_path = importer.resolve_db_path(self.claude_home)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create a v2 database with enough columns to survive the initial
        # CREATE TABLE IF NOT EXISTS + CREATE INDEX pass in ensure_schema.
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_version (
                  version INTEGER NOT NULL
                );
                INSERT INTO schema_version(version) VALUES (2);

                CREATE TABLE sessions (
                  session_id TEXT PRIMARY KEY,
                  source TEXT NOT NULL,
                  file_path TEXT NOT NULL,
                  project TEXT,
                  start_timestamp TEXT,
                  parent_session_id TEXT,
                  is_subagent INTEGER DEFAULT 0
                );

                CREATE TABLE turns (
                  id INTEGER PRIMARY KEY,
                  session_id TEXT NOT NULL,
                  turn_index INTEGER NOT NULL
                );

                CREATE TABLE tool_calls (
                  id INTEGER PRIMARY KEY,
                  turn_id INTEGER NOT NULL,
                  session_id TEXT NOT NULL,
                  tool_name TEXT NOT NULL,
                  tool_use_id TEXT
                );
                """
            )

        with db.open_db(db_path) as conn:
            table_names = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            version_row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()

            # Verify server_tool_calls table was created with expected columns
            stc_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(server_tool_calls)").fetchall()
            }

            # Verify new session columns exist
            session_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
            }

            turn_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(turns)").fetchall()
            }

        self.assertIn("server_tool_calls", table_names)
        self.assertEqual(version_row["version"], db.SCHEMA_VERSION)
        self.assertIn("iteration_input_tokens", stc_columns)
        self.assertIn("latency_ms", stc_columns)
        self.assertIn("server_tool_call_count", session_columns)
        self.assertIn("speed", turn_columns)

    def write_jsonl(self, path: Path, records: list[dict[str, object]]) -> None:
        lines = [json.dumps(record) for record in records]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class NestedSubagentAndCacheTtlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.claude_home = self.root / ".claude"
        self.project_name = "-Users-test-code-demo-repo"
        self.project_dir = self.claude_home / "projects" / self.project_name
        self.project_dir.mkdir(parents=True)
        self.session_id = "22222222-2222-2222-2222-222222222222"
        self.session_path = self.project_dir / f"{self.session_id}.jsonl"
        self.subagents_dir = self.project_dir / self.session_id / "subagents"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_jsonl(self, path: Path, records: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

    def _agent_records(self, hint: str, *, cache_creation: dict[str, object] | None = None) -> list[dict[str, object]]:
        usage: dict[str, object] = {"input_tokens": 10, "output_tokens": 5}
        if cache_creation is not None:
            usage.update(cache_creation)
        return [
            {
                "type": "user",
                "parentUuid": None,
                "sessionId": self.session_id,
                "timestamp": "2026-04-01T10:05:00Z",
                "message": {"content": f"task {hint}"},
            },
            {
                "type": "assistant",
                "requestId": f"req-{hint}",
                "timestamp": "2026-04-01T10:05:05Z",
                "message": {
                    "id": f"msg-{hint}",
                    "model": "claude-haiku-4-5",
                    "stop_reason": "end_turn",
                    "content": [],
                    "usage": usage,
                },
            },
        ]

    def write_parent(self, *, cache_creation: dict[str, object] | None = None) -> None:
        self.write_jsonl(self.session_path, self._agent_records("parent", cache_creation=cache_creation))

    def test_nested_workflow_subagents_imported_and_journal_skipped(self) -> None:
        self.write_parent()
        # Direct subagent.
        self.write_jsonl(self.subagents_dir / "agent-aaa111.jsonl", self._agent_records("direct"))
        # Nested workflow subagents (two workflow runs).
        wf1 = self.subagents_dir / "workflows" / "wf_test-1"
        wf2 = self.subagents_dir / "workflows" / "wf_test-2"
        self.write_jsonl(wf1 / "agent-bbb222.jsonl", self._agent_records("nested1"))
        # Same hex as the direct subagent — must NOT collide once qualified.
        self.write_jsonl(wf2 / "agent-aaa111.jsonl", self._agent_records("nested2"))
        # Workflow journal + meta sidecar must be ignored.
        self.write_jsonl(wf1 / "journal.jsonl", [{"type": "workflow_event", "event": "phase"}])
        (wf1 / "agent-bbb222.meta.json").write_text("{}", encoding="utf-8")

        result = importer.refresh_sessions(self.claude_home)

        # parent + 3 distinct subagents (direct, nested1, nested2); journal excluded.
        self.assertEqual(result["imported"], 4)
        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            child_ids = {
                row["child_session_id"]
                for row in conn.execute(
                    "SELECT child_session_id FROM subagent_links WHERE parent_session_id = ?",
                    (self.session_id,),
                ).fetchall()
            }
            subagent_count = conn.execute(
                "SELECT COUNT(*) AS c FROM sessions WHERE is_subagent = 1"
            ).fetchone()["c"]
            # No session should have been created from the journal file.
            journal_rows = conn.execute(
                "SELECT COUNT(*) AS c FROM sessions WHERE session_id LIKE '%journal%'"
            ).fetchone()["c"]

        self.assertEqual(subagent_count, 3)
        self.assertEqual(journal_rows, 0)
        sep = importer.SUBAGENT_SESSION_SEPARATOR
        self.assertEqual(
            child_ids,
            {
                f"{self.session_id}{sep}aaa111",
                f"{self.session_id}{sep}workflows/wf_test-1/bbb222",
                f"{self.session_id}{sep}workflows/wf_test-2/aaa111",
            },
        )

    def test_agent_id_contract_matches_across_modules(self) -> None:
        """list_subagents (parser) and session_id_for_path (importer) must agree."""
        self.write_parent()
        nested = self.subagents_dir / "workflows" / "wf_test-1" / "agent-bbb222.jsonl"
        direct = self.subagents_dir / "agent-aaa111.jsonl"
        self.write_jsonl(nested, self._agent_records("nested1"))
        self.write_jsonl(direct, self._agent_records("direct"))

        parser = importer._load_parser()
        by_path = {info.path: info.agent_id for info in parser.list_subagents(self.session_path)}

        for path in (direct, nested):
            with self.subTest(path=str(path)):
                expected_child = importer.build_subagent_session_id(self.session_id, by_path[path])
                self.assertEqual(importer.session_id_for_path(path), expected_child)

        # The importer path helpers recognise the nested transcript too.
        self.assertTrue(importer.is_subagent_path(nested))
        self.assertEqual(importer.subagent_agent_id(nested), "workflows/wf_test-1/bbb222")
        self.assertEqual(
            importer.parent_session_path_for_subagent(nested), self.session_path
        )

    def test_cache_ttl_split_persisted_and_reconciled(self) -> None:
        # Aggregate 1000 with labeled 1h=400, 5m=0 → unlabeled remainder (600)
        # defaults to the 5m bucket; buckets must sum to the aggregate.
        self.write_parent(
            cache_creation={
                "cache_creation_input_tokens": 1000,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 0,
                    "ephemeral_1h_input_tokens": 400,
                },
            }
        )

        importer.refresh_sessions(self.claude_home)

        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            turn = conn.execute(
                "SELECT cache_create, cache_create_5m, cache_create_1h FROM turns "
                "WHERE session_id = ?",
                (self.session_id,),
            ).fetchone()
            sess = conn.execute(
                "SELECT total_cache_create, total_cache_create_5m, total_cache_create_1h "
                "FROM sessions WHERE session_id = ?",
                (self.session_id,),
            ).fetchone()

        self.assertEqual(turn["cache_create"], 1000)
        self.assertEqual(turn["cache_create_1h"], 400)
        self.assertEqual(turn["cache_create_5m"], 600)
        self.assertEqual(turn["cache_create_5m"] + turn["cache_create_1h"], turn["cache_create"])
        self.assertEqual(sess["total_cache_create_1h"], 400)
        self.assertEqual(sess["total_cache_create_5m"], 600)

    def test_subagent_path_passed_directly_normalises_to_parent(self) -> None:
        """Refreshing a nested subagent path imports the whole parent tree."""
        self.write_parent()
        nested = self.subagents_dir / "workflows" / "wf_test-1" / "agent-bbb222.jsonl"
        self.write_jsonl(nested, self._agent_records("nested1"))

        result = importer.refresh_sessions(self.claude_home, session_paths=[nested])

        self.assertEqual(result["imported"], 2)  # parent + nested subagent
        with db.open_db(importer.resolve_db_path(self.claude_home)) as conn:
            child = conn.execute(
                "SELECT child_session_id FROM subagent_links WHERE parent_session_id = ?",
                (self.session_id,),
            ).fetchone()
        self.assertEqual(
            child["child_session_id"],
            f"{self.session_id}{importer.SUBAGENT_SESSION_SEPARATOR}workflows/wf_test-1/bbb222",
        )


if __name__ == "__main__":
    unittest.main()
