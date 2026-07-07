from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "inspect_session.py"
)
SPEC = importlib.util.spec_from_file_location("inspect_session", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load inspect_session module")
inspect_session = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inspect_session
SPEC.loader.exec_module(inspect_session)


class InspectSessionTests(unittest.TestCase):
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

    def test_summary_normalizes_turns_and_correlates_tool_results(self) -> None:
        self.write_jsonl(
            self.session_path,
            self.primary_session_records(),
            broken_lines=["{not json"],
        )

        loaded = inspect_session.load_session(self.session_path)
        summary = inspect_session.summarize_session(
            loaded,
            inspect_session.resolve_paths(self.claude_home),
        )

        self.assertEqual(summary["parse_errors"], 1)
        self.assertEqual(summary["turn_count"], 2)
        self.assertEqual(summary["completed_turn_count"], 2)
        self.assertEqual(summary["incomplete_turn_count"], 0)
        self.assertEqual(summary["max_tokens_stop_count"], 1)
        self.assertEqual(summary["tool_error_count"], 1)
        self.assertEqual(summary["tool_errors_by_name"], {"Bash": 1})
        self.assertEqual(summary["api_error_count"], 1)
        self.assertEqual(
            summary["token_usage"],
            {
                "input_tokens": 160,
                "output_tokens": 105,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 15,
                "total_tokens": 265,
                "api_calls": 2,
            },
        )
        self.assertEqual(summary["models"], {"claude-sonnet-4-5": 2})
        self.assertEqual(summary["tool_usage"], {"Read": 1, "Bash": 1})
        self.assertEqual(summary["hook_summary"]["count"], 2)
        self.assertEqual(summary["hook_summary"]["total_duration_ms"], 350)
        self.assertEqual(summary["hook_summary"]["errors"], 1)
        self.assertEqual(summary["hook_summary"]["by_command"][0]["command"], "lint")
        self.assertEqual(summary["latest_git_branch"], "main")
        self.assertEqual(summary["custom_title"], "Bug Investigation")
        self.assertEqual(summary["agent_name"], "Inspector")
        self.assertEqual(summary["timestamp"], "2026-04-01T10:00:00Z")
        self.assertEqual(summary["project_cwd"], "/Users/test/code/demo/repo")
        self.assertEqual(summary["pr_links"][0]["prNumber"], 12)

        turn_one = summary["turns"][0]
        turn_two = summary["turns"][1]
        self.assertEqual(turn_one["token_usage"]["input_tokens"], 110)
        self.assertEqual(turn_one["tool_calls"][0]["name"], "Read")
        self.assertFalse(turn_one["tool_calls"][0]["is_error"])
        self.assertEqual(turn_two["tool_calls"][0]["name"], "Bash")
        self.assertTrue(turn_two["tool_calls"][0]["is_error"])
        self.assertEqual(turn_two["tool_calls"][0]["error_text"], "command failed")
        self.assertEqual(turn_two["user_gap_ms"], 64_000)

    def test_parse_thinking_block_metrics(self) -> None:
        self.write_jsonl(self.session_path, self.primary_session_records())

        loaded = inspect_session.load_session(self.session_path)
        parsed = inspect_session.parse_loaded_session(loaded)

        self.assertEqual(len(parsed.turns), 2)
        first_turn = parsed.turns[0]
        second_turn = parsed.turns[1]

        self.assertEqual(first_turn.thinking_block_count, 1)
        self.assertEqual(len(first_turn.thinking_blocks), 1)
        self.assertEqual(first_turn.thinking_blocks[0].block_index, 1)
        self.assertFalse(first_turn.thinking_blocks[0].is_redacted)
        self.assertEqual(first_turn.thinking_blocks[0].content_length, 20)
        self.assertEqual(first_turn.thinking_blocks[0].signature_length, 5)
        self.assertTrue(first_turn.thinking_blocks[0].has_signature)

        self.assertEqual(second_turn.thinking_block_count, 1)
        self.assertEqual(len(second_turn.thinking_blocks), 1)
        self.assertEqual(second_turn.thinking_blocks[0].block_index, 1)
        self.assertTrue(second_turn.thinking_blocks[0].is_redacted)
        self.assertEqual(second_turn.thinking_blocks[0].content_length, 0)
        self.assertEqual(second_turn.thinking_blocks[0].signature_length, 5)
        self.assertTrue(second_turn.thinking_blocks[0].has_signature)

    def test_parse_user_messages_excludes_tool_results(self) -> None:
        self.write_jsonl(self.session_path, self.primary_session_records())

        loaded = inspect_session.load_session(self.session_path)
        parsed = inspect_session.parse_loaded_session(loaded)

        self.assertEqual(len(parsed.user_messages), 2)
        self.assertEqual(parsed.user_messages[0].message_index, 1)
        self.assertTrue(parsed.user_messages[0].is_first)
        self.assertFalse(parsed.user_messages[0].is_interrupt)
        self.assertEqual(parsed.user_messages[0].word_count, 4)
        self.assertEqual(parsed.user_messages[0].char_count, 25)
        self.assertIsNone(parsed.user_messages[0].preceding_turn_index)

        self.assertEqual(parsed.user_messages[1].message_index, 2)
        self.assertFalse(parsed.user_messages[1].is_first)
        self.assertFalse(parsed.user_messages[1].is_interrupt)
        self.assertEqual(parsed.user_messages[1].word_count, 7)
        self.assertEqual(parsed.user_messages[1].char_count, 31)
        self.assertEqual(parsed.user_messages[1].preceding_turn_index, 1)

    def test_content_block_type_counts(self) -> None:
        self.write_jsonl(self.session_path, self.primary_session_records())

        loaded = inspect_session.load_session(self.session_path)
        parsed = inspect_session.parse_loaded_session(loaded)

        self.assertEqual(parsed.turns[0].text_block_count, 1)
        self.assertEqual(parsed.turns[0].thinking_block_count, 1)
        self.assertEqual(parsed.turns[0].tool_use_block_count, 1)
        self.assertEqual(parsed.turns[1].text_block_count, 1)
        self.assertEqual(parsed.turns[1].thinking_block_count, 1)
        self.assertEqual(parsed.turns[1].tool_use_block_count, 1)

    def test_extract_quick_metadata_keeps_scanning_for_titles(self) -> None:
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
                {"type": "assistant", "message": {"id": "msg-1"}},
                {"type": "assistant", "message": {"id": "msg-2"}},
                {"type": "custom-title", "customTitle": "Late Title"},
                {"type": "agent-name", "agentName": "Late Agent"},
            ],
        )

        meta = inspect_session.extract_quick_metadata(self.session_path)

        self.assertEqual(meta["custom_title"], "Late Title")
        self.assertEqual(meta["agent_name"], "Late Agent")
        self.assertEqual(meta["timestamp"].isoformat(), "2026-04-01T10:00:00+00:00")

    def test_collect_sessions_matches_decoded_project_path(self) -> None:
        self.write_jsonl(
            self.session_path,
            [
                {
                    "type": "user",
                    "parentUuid": None,
                    "sessionId": self.session_id,
                    "timestamp": "2026-04-01T10:00:00Z",
                    "message": {"content": "hello"},
                }
            ],
        )

        paths = inspect_session.resolve_paths(self.claude_home)
        sessions = inspect_session.collect_sessions(
            paths,
            project="/Users/test/code/demo/repo",
            since=None,
        )

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].project, self.project_name)
        self.assertEqual(sessions[0].project_cwd, "/Users/test/code/demo/repo")

    def test_collect_sessions_matches_project_path_with_dots(self) -> None:
        self.project_name = "-Users-test-code-github-com-demo-repo"
        self.project_dir = self.projects_dir / self.project_name
        self.project_dir.mkdir(parents=True)
        self.session_path = self.project_dir / f"{self.session_id}.jsonl"
        self.write_jsonl(
            self.session_path,
            [
                {
                    "type": "user",
                    "parentUuid": None,
                    "sessionId": self.session_id,
                    "timestamp": "2026-04-01T10:00:00Z",
                    "message": {"content": "hello"},
                }
            ],
        )

        paths = inspect_session.resolve_paths(self.claude_home)
        sessions = inspect_session.collect_sessions(
            paths,
            project="/Users/test/code/github.com/demo/repo",
            since=None,
        )

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].project, self.project_name)

    def test_inspect_subagent_uses_agent_filename_as_identity(self) -> None:
        self.write_jsonl(
            self.session_path,
            [
                {
                    "type": "user",
                    "parentUuid": None,
                    "sessionId": self.session_id,
                    "timestamp": "2026-04-01T10:00:00Z",
                    "message": {"content": "parent"},
                }
            ],
        )
        subagent_dir = self.project_dir / self.session_id / "subagents"
        subagent_dir.mkdir(parents=True)
        subagent_path = subagent_dir / "agent-abc123.jsonl"
        self.write_jsonl(
            subagent_path,
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
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "sub-tool-1",
                                "name": "Read",
                                "input": {"file_path": "worker.py"},
                            }
                        ],
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 5,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0,
                        },
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "sub-tool-1",
                                "is_error": False,
                                "content": "ok",
                            }
                        ]
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

        summary = inspect_session.inspect_subagent(self.session_path, "abc123")

        self.assertEqual(summary["agent_id"], "abc123")
        self.assertEqual(summary["parent_session_id"], self.session_id)
        self.assertEqual(summary["model"], "claude-haiku-4-5")
        self.assertEqual(summary["turn_count"], 1)
        self.assertEqual(summary["completed_turn_count"], 1)
        self.assertEqual(summary["token_usage"]["total_tokens"], 15)
        self.assertEqual(summary["tool_usage"], {"Read": 1})
        self.assertEqual(summary["first_task"], "inspect just the subagent work")

    def write_jsonl(
        self,
        path: Path,
        records: list[dict[str, object]],
        *,
        broken_lines: list[str] | None = None,
    ) -> None:
        lines = [json.dumps(record) for record in records]
        lines.extend(broken_lines or [])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def primary_session_records(self) -> list[dict[str, object]]:
        return [
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
                        },
                    ],
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 40,
                        "cache_creation_input_tokens": 10,
                        "cache_read_input_tokens": 5,
                    },
                },
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
                        },
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
                        },
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
                "subtype": "api_error",
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
        ]


if __name__ == "__main__":
    unittest.main()
