from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "inspect_rollout.py"
SPEC = importlib.util.spec_from_file_location("inspect_rollout", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"failed to load module from {SCRIPT_PATH}")
inspect_rollout = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inspect_rollout
SPEC.loader.exec_module(inspect_rollout)


THREAD_ID = "019d2494-6c37-7c93-9df6-7ed84372b136"


def write_jsonl(path: Path, rows: list[dict[str, Any] | str]) -> None:
    lines: list[str] = []
    for row in rows:
        if isinstance(row, str):
            lines.append(row)
        else:
            lines.append(json.dumps(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class InspectRolloutTests(unittest.TestCase):
    def test_locate_payload_reports_hook_candidates_feature_flags_and_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            codex_home = root / ".codex"
            repo_root = root / "repo"
            repo_root.mkdir()
            (repo_root / ".git").mkdir()
            (repo_root / ".codex").mkdir()
            (repo_root / ".codex" / "hooks.json").write_text(
                json.dumps(
                    {
                        "hooks": {
                            "Stop": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python3 /tmp/codex-rollout-inspector/scripts/sync_rollout.py",
                                            "timeout": 30,
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            (codex_home / "config.toml").parent.mkdir(parents=True, exist_ok=True)
            (codex_home / "config.toml").write_text(
                "[features]\ncodex_hooks = true\n",
                encoding="utf-8",
            )
            paths = inspect_rollout.resolve_paths(codex_home)

            payload = inspect_rollout.locate_payload(
                paths,
                db_path=codex_home / "inspector" / "session_inspector.db",
                cwd=repo_root,
            )

            self.assertEqual(payload["hook_config_path"], str(codex_home / "hooks.json"))
            self.assertEqual(
                payload["hook_config_paths"],
                [
                    str(codex_home / "hooks.json"),
                    str((repo_root / ".codex" / "hooks.json").resolve()),
                ],
            )
            self.assertTrue(payload["hook_configured"])
            self.assertEqual(
                payload["hook_configured_paths"],
                [str((repo_root / ".codex" / "hooks.json").resolve())],
            )
            self.assertEqual(payload["hook_discovery_scope"], "config_layers")
            self.assertTrue(payload["codex_hooks_enabled"])
            self.assertFalse(payload["hooks_enabled"])
            self.assertTrue(payload["legacy_codex_hooks_enabled"])
            self.assertEqual(payload["hooks_feature_flag"], "[features]\nhooks = true")
            self.assertEqual(payload["pending_markers"]["count"], 0)
            self.assertEqual(
                payload["config_toml_paths"],
                [
                    str(codex_home / "config.toml"),
                    str((repo_root / ".codex" / "config.toml").resolve()),
                ],
            )
            self.assertEqual(
                payload["hook_config_candidates"][1]["scope"],
                "repo",
            )
            self.assertTrue(
                payload["hook_config_candidates"][1]["codex_rollout_inspector_stop_hook"]
            )
            self.assertIn("python3 -c", payload["hook_command"])
            self.assertIn("sync_rollout.py", payload["hook_command"])
            self.assertIn('codex_home / "skills" / "codex-rollout-inspector"', payload["hook_command"])
            self.assertIn('{ "$script" || python3 "$script"; }', payload["hook_command"])

    def test_quick_rollout_uses_latest_turn_context_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rollout_path = Path(tmpdir) / f"rollout-2026-04-06T12-00-00-{THREAD_ID}.jsonl"
            rows: list[dict[str, Any]] = [
                {
                    "timestamp": "2026-04-06T12:00:00Z",
                    "type": "session_meta",
                    "payload": {
                        "cwd": "/tmp/stale-project",
                        "source": {},
                    },
                },
                {
                    "timestamp": "2026-04-06T12:00:01Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "Investigate rollout parsing",
                    },
                },
            ]
            rows.extend(
                {
                    "timestamp": f"2026-04-06T12:00:{second:02d}Z",
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": second,
                                "cached_input_tokens": 0,
                                "output_tokens": second,
                                "reasoning_output_tokens": 0,
                                "total_tokens": second * 2,
                            }
                        },
                    },
                }
                for second in range(2, 225)
            )
            rows.append(
                {
                    "timestamp": "2026-04-06T12:04:00Z",
                    "type": "turn_context",
                    "payload": {
                        "cwd": "/tmp/latest-project",
                        "model": "gpt-5-codex",
                    },
                }
            )
            write_jsonl(rollout_path, rows)

            quick = inspect_rollout.quick_rollout_info(rollout_path, {})

            self.assertEqual(quick.cwd, "/tmp/latest-project")
            self.assertEqual(quick.project, "latest-project")
            self.assertEqual(quick.model, "gpt-5-codex")
            self.assertTrue(inspect_rollout.matches_project(quick, "latest-project"))
            self.assertFalse(inspect_rollout.matches_project(quick, "stale-project"))

    def test_quick_rollout_prefers_event_user_message_over_response_item_user_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rollout_path = Path(tmpdir) / f"rollout-2026-04-06T12-00-00-{THREAD_ID}.jsonl"
            write_jsonl(
                rollout_path,
                [
                    {
                        "timestamp": "2026-04-06T12:00:00Z",
                        "type": "session_meta",
                        "payload": {"cwd": "/tmp/demo-project", "source": {}},
                    },
                    {
                        "timestamp": "2026-04-06T12:00:00.100Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": "large injected environment block",
                                }
                            ],
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:00:01Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "write a hello world server",
                        },
                    },
                ],
            )

            quick = inspect_rollout.quick_rollout_info(rollout_path, {})

            self.assertEqual(quick.first_user_message, "write a hello world server")
            self.assertEqual(quick.title, "write a hello world server")

    def test_extract_user_message_metrics(self) -> None:
        metrics = inspect_rollout.extract_user_message_metrics(
            [
                {
                    "timestamp": "2026-04-06T12:00:01Z",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "first prompt"},
                },
                {
                    "timestamp": "2026-04-06T12:00:02Z",
                    "type": "turn_context",
                    "payload": {"cwd": "/tmp/demo-project", "model": "gpt-5.4"},
                },
                {
                    "timestamp": "2026-04-06T12:00:03Z",
                    "type": "event_msg",
                    "payload": {"type": "task_started", "turn_id": "turn-1"},
                },
                {
                    "timestamp": "2026-04-06T12:00:04Z",
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": "interrupt now"},
                },
                {
                    "timestamp": "2026-04-06T12:00:05Z",
                    "type": "event_msg",
                    "payload": {"type": "task_complete", "turn_id": "turn-1"},
                },
            ]
        )

        self.assertEqual(
            metrics,
            [
                {
                    "message_index": 1,
                    "timestamp": "2026-04-06T12:00:01Z",
                    "is_first": True,
                    "is_interrupt": False,
                    "word_count": 2,
                    "char_count": 12,
                    "preceding_turn_index": None,
                },
                {
                    "message_index": 2,
                    "timestamp": "2026-04-06T12:00:04Z",
                    "is_first": False,
                    "is_interrupt": True,
                    "word_count": 2,
                    "char_count": 13,
                    "preceding_turn_index": 1,
                },
            ],
        )

    def test_extract_reasoning_block_metrics(self) -> None:
        metrics = inspect_rollout.extract_reasoning_block_metrics(
            [
                {
                    "timestamp": "2026-04-06T12:00:02Z",
                    "type": "turn_context",
                    "payload": {"cwd": "/tmp/demo-project", "model": "gpt-5.4"},
                },
                {
                    "timestamp": "2026-04-06T12:00:03Z",
                    "type": "response_item",
                    "payload": {
                        "type": "reasoning",
                        "summary": [{"text": "step"}],
                        "content": None,
                        "encrypted_content": "secret-bytes",
                    },
                },
                {
                    "timestamp": "2026-04-06T12:00:04Z",
                    "type": "response_item",
                    "payload": {
                        "type": "reasoning",
                        "summary": [],
                        "content": "plain reasoning",
                        "encrypted_content": "cipher",
                    },
                },
            ]
        )

        self.assertEqual(
            metrics,
            [
                {
                    "turn_index": 1,
                    "block_index": 1,
                    "block_type": "reasoning",
                    "is_redacted": 1,
                    "content_length": 12,
                    "encrypted_content_length": 12,
                    "summary_item_count": 1,
                    "has_plaintext_content": 0,
                },
                {
                    "turn_index": 1,
                    "block_index": 2,
                    "block_type": "reasoning",
                    "is_redacted": 0,
                    "content_length": 15,
                    "encrypted_content_length": 6,
                    "summary_item_count": 0,
                    "has_plaintext_content": 1,
                },
            ],
        )

    def test_subagent_summary_uses_child_specific_task_after_parent_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            sessions_dir = codex_home / "sessions" / "2026" / "04" / "06"
            sessions_dir.mkdir(parents=True)
            child_thread_id = "019d2494-6c37-7c93-9df6-7ed84372b137"
            parent_path = sessions_dir / f"rollout-2026-04-06T12-00-00-{THREAD_ID}.jsonl"
            child_path = sessions_dir / f"rollout-2026-04-06T12-10-00-{child_thread_id}.jsonl"
            write_jsonl(
                parent_path,
                [
                    {
                        "timestamp": "2026-04-06T12:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": THREAD_ID,
                            "cwd": "/tmp/demo-project",
                            "timestamp": "2026-04-06T12:00:00Z",
                            "source": {},
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:00:01Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "write a hello world server",
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:00:02Z",
                        "type": "turn_context",
                        "payload": {
                            "cwd": "/tmp/demo-project",
                            "model": "gpt-5.4",
                        },
                    },
                ],
            )
            write_jsonl(
                child_path,
                [
                    {
                        "timestamp": "2026-04-06T12:10:00Z",
                        "type": "session_meta",
                        "payload": {
                            "id": child_thread_id,
                            "cwd": "/tmp/demo-project",
                            "timestamp": "2026-04-06T12:10:00Z",
                            "forked_from_id": THREAD_ID,
                            "source": {
                                "subagent": {
                                    "thread_spawn": {
                                        "parent_thread_id": THREAD_ID,
                                        "agent_nickname": "worker",
                                        "agent_role": "default",
                                    }
                                }
                            },
                            "agent_nickname": "worker",
                            "agent_role": "default",
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:10:01Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "write a hello world server",
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:10:02Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "research Go 1.26 HTTP changes",
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:10:03Z",
                        "type": "turn_context",
                        "payload": {
                            "cwd": "/tmp/demo-project",
                            "model": "gpt-5.4-mini",
                        },
                    },
                ],
            )
            write_jsonl(
                codex_home / "session_index.jsonl",
                [{"id": THREAD_ID, "thread_name": "Parent rollout"}],
            )

            paths = inspect_rollout.resolve_paths(codex_home)
            thread_names = inspect_rollout.load_session_index(paths.session_index_path)
            summary = inspect_rollout.summarize_rollout(
                inspect_rollout.load_rollout(child_path),
                paths,
                thread_names,
                include_subagents=False,
            )

            self.assertEqual(summary["raw_first_user_message"], "write a hello world server")
            self.assertEqual(summary["delegated_task"], "research Go 1.26 HTTP changes")
            self.assertEqual(summary["first_user_message"], "research Go 1.26 HTTP changes")
            self.assertEqual(summary["title"], "research Go 1.26 HTTP changes")

    def test_resolve_target_prefers_latest_parent_when_target_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            sessions_dir = codex_home / "sessions" / "2026" / "04" / "06"
            sessions_dir.mkdir(parents=True)
            child_thread_id = "019d2494-6c37-7c93-9df6-7ed84372b137"
            parent_path = sessions_dir / f"rollout-2026-04-06T12-00-00-{THREAD_ID}.jsonl"
            child_path = sessions_dir / f"rollout-2026-04-06T12-10-00-{child_thread_id}.jsonl"
            write_jsonl(
                parent_path,
                [
                    {
                        "timestamp": "2026-04-06T12:00:00Z",
                        "type": "session_meta",
                        "payload": {"cwd": "/tmp/demo-project", "source": {}},
                    },
                    {
                        "timestamp": "2026-04-06T12:00:01Z",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "parent prompt"},
                    },
                ],
            )
            write_jsonl(
                child_path,
                [
                    {
                        "timestamp": "2026-04-06T12:10:00Z",
                        "type": "session_meta",
                        "payload": {
                            "forked_from_id": THREAD_ID,
                            "cwd": "/tmp/demo-project",
                            "source": {
                                "subagent": {
                                    "thread_spawn": {
                                        "parent_thread_id": THREAD_ID,
                                        "agent_nickname": "worker",
                                        "agent_role": "default",
                                    }
                                }
                            },
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:10:01Z",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "child prompt"},
                    },
                ],
            )
            paths = inspect_rollout.resolve_paths(codex_home)

            resolved = inspect_rollout.resolve_target(
                paths,
                {},
                None,
                archived=False,
                project="demo-project",
                prefer_parent_on_default=True,
            )

            self.assertEqual(resolved, parent_path)

    def test_summarize_tool_usage_correlates_call_outputs(self) -> None:
        records = [
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": {
                        "content": "permission denied",
                        "success": False,
                    },
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "call_id": "call-2",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "call-2",
                    "output": {
                        "content": "patched successfully",
                        "success": True,
                    },
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-3",
                },
            },
        ]

        summary = inspect_rollout.summarize_tool_usage(records)

        self.assertEqual(summary["function_calls"], {"exec_command": 2})
        self.assertEqual(summary["custom_tool_calls"], {"apply_patch": 1})
        self.assertEqual(summary["tool_error_count"], 1)
        self.assertEqual(summary["tool_errors_by_name"], {"exec_command": 1})
        self.assertEqual(summary["calls_with_output"], 2)
        self.assertEqual(summary["calls_without_output"], 1)
        self.assertEqual(summary["successful_output_count"], 1)
        self.assertEqual(summary["error_output_count"], 1)
        self.assertEqual(summary["unknown_output_status_count"], 0)
        self.assertEqual(summary["unmatched_output_count"], 0)

    def test_summarize_tool_usage_includes_native_calls(self) -> None:
        records = [
            {
                "type": "response_item",
                "payload": {
                    "type": "local_shell_call",
                    "call_id": "shell-1",
                    "status": "incomplete",
                    "action": {
                        "type": "exec",
                        "command": ["/bin/false"],
                    },
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "tool_search_call",
                    "call_id": "search-1",
                    "execution": "client",
                    "arguments": {"query": "calendar create"},
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "tool_search_output",
                    "call_id": "search-1",
                    "status": "failed",
                    "execution": "client",
                    "tools": [],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "web_search_call",
                    "id": "web-1",
                    "status": "completed",
                    "action": {"type": "search", "query": "weather seattle"},
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "image_generation_call",
                    "id": "img-1",
                    "status": "completed",
                    "result": "Zm9v",
                },
            },
        ]

        summary = inspect_rollout.summarize_tool_usage(records)

        self.assertEqual(
            summary["native_calls"],
            {
                "local_shell_call": 1,
                "tool_search_call": 1,
                "web_search_call": 1,
                "image_generation_call": 1,
            },
        )
        self.assertEqual(summary["all_calls"]["local_shell_call"], 1)
        self.assertEqual(summary["all_calls"]["tool_search_call"], 1)
        self.assertEqual(summary["all_calls"]["web_search_call"], 1)
        self.assertEqual(summary["all_calls"]["image_generation_call"], 1)
        self.assertEqual(
            summary["call_type_counts"],
            {
                "local_shell_call": 1,
                "tool_search_call": 1,
                "web_search_call": 1,
                "image_generation_call": 1,
            },
        )
        self.assertEqual(summary["tool_error_count"], 2)
        self.assertEqual(
            summary["tool_errors_by_name"],
            {
                "local_shell_call": 1,
                "tool_search_call": 1,
            },
        )
        self.assertEqual(summary["calls_with_output"], 1)
        self.assertEqual(summary["calls_without_output"], 0)
        self.assertEqual(summary["successful_output_count"], 0)
        self.assertEqual(summary["error_output_count"], 1)
        self.assertEqual(summary["unknown_output_status_count"], 0)
        self.assertEqual(summary["unmatched_output_count"], 0)

    def test_ingestion_summary_includes_tool_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_home = Path(tmpdir)
            sessions_dir = codex_home / "sessions" / "2026" / "04" / "06"
            sessions_dir.mkdir(parents=True)
            rollout_path = sessions_dir / f"rollout-2026-04-06T12-00-00-{THREAD_ID}.jsonl"
            write_jsonl(
                rollout_path,
                [
                    {
                        "timestamp": "2026-04-06T12:00:00Z",
                        "type": "session_meta",
                        "payload": {
                            "cwd": "/tmp/stale-project",
                            "timestamp": "2026-04-06T12:00:00Z",
                            "source": {},
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:00:01Z",
                        "type": "event_msg",
                        "payload": {
                            "type": "user_message",
                            "message": "run the failing command",
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:00:02Z",
                        "type": "turn_context",
                        "payload": {
                            "cwd": "/tmp/latest-project",
                            "model": "gpt-5-codex",
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:00:03Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "call_id": "call-1",
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:00:04Z",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "call-1",
                            "output": {
                                "content": "permission denied",
                                "success": False,
                            },
                        },
                    },
                    {
                        "timestamp": "2026-04-06T12:00:05Z",
                        "type": "response_item",
                        "payload": {
                            "type": "local_shell_call",
                            "call_id": "shell-1",
                            "status": "incomplete",
                            "action": {
                                "type": "exec",
                                "command": ["/bin/false"],
                            },
                        },
                    },
                ],
            )
            write_jsonl(
                codex_home / "session_index.jsonl",
                [{"id": THREAD_ID, "thread_name": "Test rollout"}],
            )

            paths = inspect_rollout.resolve_paths(codex_home)
            thread_names = inspect_rollout.load_session_index(paths.session_index_path)
            loaded = inspect_rollout.load_rollout(rollout_path)

            summary = inspect_rollout.summarize_rollout_ingestion(loaded, paths, thread_names)

            self.assertEqual(summary["session"]["cwd"], "/tmp/latest-project")
            self.assertEqual(summary["counts"]["tool_error_count"], 2)
            self.assertEqual(
                summary["usage"]["tools"],
                [
                    {
                        "name": "exec_command",
                        "count": 1,
                        "errors": 1,
                        "kind": "function_call",
                    },
                    {
                        "name": "local_shell_call",
                        "count": 1,
                        "errors": 1,
                        "kind": "local_shell_call",
                    }
                ],
            )

    def test_filter_records_tool_name_matches_native_call_types(self) -> None:
        records = [
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-1",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "local_shell_call",
                    "call_id": "shell-1",
                    "status": "completed",
                    "action": {
                        "type": "exec",
                        "command": ["/bin/echo", "hello"],
                    },
                },
            },
        ]

        matches = inspect_rollout.filter_records(
            records,
            record_type=None,
            payload_type=None,
            tool_name="local_shell_call",
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["payload"]["type"], "local_shell_call")


if __name__ == "__main__":
    unittest.main()
