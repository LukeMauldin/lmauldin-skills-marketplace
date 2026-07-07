from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "inspect_session.py"
SPEC = importlib.util.spec_from_file_location("inspect_session", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"failed to load module from {SCRIPT_PATH}")
inspect_session = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = inspect_session
SPEC.loader.exec_module(inspect_session)


SESSION_ID = "019ea82f-8c31-785c-a219-5b3f1250c0d0"
SLUG = "--Users-me-code-github.com-org-repo--"
FILENAME = f"2026-06-08T17-02-28-913Z_{SESSION_ID}.jsonl"


def _usage(inp: int, out: int, cost: float = 0.0, cr: int = 0, cw: int = 0) -> dict[str, Any]:
    return {
        "input": inp,
        "output": out,
        "cacheRead": cr,
        "cacheWrite": cw,
        "totalTokens": inp + out,
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": cost},
    }


def sample_records() -> list[dict[str, Any]]:
    """A synthetic pi session exercising every verified record type/shape."""
    return [
        {"type": "session", "version": 3, "id": SESSION_ID, "cwd": "/Users/me/code/github.com/org/repo", "timestamp": "2026-06-08T17:02:28.913Z"},
        {"type": "model_change", "id": "aaa", "parentId": None, "provider": "lmstudio", "modelId": "qwen3.6-27b-mlx", "timestamp": "2026-06-08T17:02:31.087Z"},
        {"type": "thinking_level_change", "id": "bbb", "parentId": "aaa", "thinkingLevel": "medium", "timestamp": "2026-06-08T17:02:31.087Z"},
        {"type": "custom", "customType": "plannotator", "data": {"phase": "idle"}, "id": "ccc", "parentId": "bbb", "timestamp": "2026-06-08T17:02:31.180Z"},
        {"type": "custom_message", "customType": "pi-memory-context", "content": "<memory>…</memory>", "display": False, "id": "ddd", "parentId": "ccc", "timestamp": "2026-06-08T17:02:31.200Z"},
        {"type": "message", "id": "m1", "parentId": "ddd", "timestamp": "2026-06-08T17:02:40.000Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "Fix the bug. See https://github.com/org/repo/pull/42"}], "timestamp": 1}},
        {"type": "message", "id": "m2", "parentId": "m1", "timestamp": "2026-06-08T17:02:45.000Z",
         "message": {"role": "assistant", "model": "qwen3.6-27b-mlx", "provider": "lmstudio", "stopReason": "toolUse",
                     "content": [
                         {"type": "thinking", "thinking": "let me look"},
                         {"type": "text", "text": "Running a command."},
                         {"type": "toolCall", "id": "tc1", "name": "bash", "arguments": {"command": "ls"}},
                     ],
                     "usage": _usage(100, 20, cost=0.0), "timestamp": 2}},
        {"type": "message", "id": "m3", "parentId": "m2", "timestamp": "2026-06-08T17:02:46.000Z",
         "message": {"role": "toolResult", "toolName": "bash", "toolCallId": "tc1", "isError": True,
                     "content": [{"type": "text", "text": "boom: failure"}], "timestamp": 3}},
        {"type": "message", "id": "m4", "parentId": "m3", "timestamp": "2026-06-08T17:02:50.000Z",
         "message": {"role": "assistant", "model": "qwen3.6-27b-mlx", "provider": "lmstudio", "stopReason": "toolUse",
                     "content": [{"type": "toolCall", "id": "tc2", "name": "subagent", "arguments": {"agent": "worker", "task": "say PONG"}}],
                     "usage": _usage(9000, 80, cost=0.0), "timestamp": 4}},
        {"type": "message", "id": "m5", "parentId": "m4", "timestamp": "2026-06-08T17:03:30.000Z",
         "message": {"role": "toolResult", "toolName": "subagent", "toolCallId": "tc2", "isError": False,
                     "content": [{"type": "text", "text": "PONG"}],
                     "details": {"mode": "single", "agentScope": "user", "projectAgentsDir": None,
                                 "results": [{"agent": "worker", "agentSource": "user", "task": "say PONG", "exitCode": 0,
                                              "model": "qwen3.6-27b-mlx", "stopReason": "stop",
                                              "usage": {"input": 25289, "output": 22, "cacheRead": 0, "cacheWrite": 0, "cost": {"total": 0}, "contextTokens": 25311, "turns": 1},
                                              "messages": [{"role": "assistant", "content": [{"type": "toolCall", "id": "x", "name": "read", "arguments": {}}, {"type": "text", "text": "PONG"}]}]}]},
                     "timestamp": 5}},
        {"type": "message", "id": "m6", "parentId": "m5", "timestamp": "2026-06-08T17:03:35.000Z",
         "message": {"role": "assistant", "model": "qwen3.6-27b-mlx", "provider": "lmstudio", "stopReason": "stop",
                     "content": [{"type": "text", "text": "Done."}], "usage": _usage(50, 10, cost=0.0), "timestamp": 6}},
        {"type": "compaction", "id": "cmp", "parentId": "m6", "summary": "did stuff", "firstKeptEntryId": "m4", "tokensBefore": 12345, "fromHook": False, "details": {"readFiles": [], "modifiedFiles": []}, "timestamp": "2026-06-08T17:03:40.000Z"},
    ]


def make_session_tree(root: Path) -> Path:
    sessions = root / "sessions" / SLUG
    sessions.mkdir(parents=True)
    path = sessions / FILENAME
    path.write_text("\n".join(json.dumps(r) for r in sample_records()) + "\n", encoding="utf-8")
    return path


def make_recorder_db(root: Path) -> Path:
    db = root / "recorder.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, session_file TEXT, cwd TEXT, started_at INTEGER,
            ended_at INTEGER, model_provider TEXT, model_id TEXT, total_input_tokens INTEGER,
            total_output_tokens INTEGER, total_cost REAL);
        CREATE TABLE turns (id INTEGER PRIMARY KEY, session_id TEXT, turn_index INTEGER,
            iteration_number INTEGER, started_at INTEGER, ended_at INTEGER, duration_ms INTEGER,
            model_provider TEXT, model_id TEXT, input_tokens INTEGER, output_tokens INTEGER,
            cost REAL, stop_reason TEXT);
        CREATE TABLE tool_calls (id TEXT PRIMARY KEY, session_id TEXT, turn_id INTEGER, tool_name TEXT,
            input_json TEXT, started_at INTEGER, ended_at INTEGER, duration_ms INTEGER, is_error INTEGER, result_text TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, turn_id INTEGER, timestamp INTEGER);
        CREATE TABLE model_changes (id INTEGER PRIMARY KEY, session_id TEXT, timestamp INTEGER, source TEXT,
            from_provider TEXT, from_model_id TEXT, to_provider TEXT, to_model_id TEXT);
        """
    )
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
        (SESSION_ID, str(root / "sessions" / SLUG / FILENAME), "/Users/me/code/github.com/org/repo",
         1780333348913, 1780333420000, "lmstudio", "qwen3.6-27b-mlx", 9150, 110, 0.0),
    )
    # Subagent subprocess row: NULL session_file.
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("019ea830-1652-7f26-bc79-8c548e1e4566", None, "/Users/me/code/github.com/org/repo",
         1780333386000, 1780333389000, "lmstudio", "qwen3.6-27b-mlx", 25289, 22, 0.0),
    )
    conn.execute("INSERT INTO turns VALUES (1,?,0,0,1780333365000,1780333366000,1000,'lmstudio','qwen3.6-27b-mlx',100,20,0,'toolUse')", (SESSION_ID,))
    conn.execute("INSERT INTO turns VALUES (2,?,1,0,1780333370000,1780333415000,45000,'lmstudio','qwen3.6-27b-mlx',9000,80,0,'toolUse')", (SESSION_ID,))
    conn.execute("INSERT INTO tool_calls VALUES ('tc1',?,1,'bash','{}',1780333365100,1780333366100,1000,1,'boom')", (SESSION_ID,))
    conn.execute("INSERT INTO tool_calls VALUES ('tc2',?,2,'subagent','{}',1780333370100,1780333413000,42900,0,'PONG')", (SESSION_ID,))
    conn.commit()
    conn.close()
    return db


class FilenameTests(unittest.TestCase):
    def test_parse_filename(self) -> None:
        sid, iso, day = inspect_session.parse_session_filename(Path(FILENAME))
        self.assertEqual(sid, SESSION_ID)
        self.assertEqual(iso, "2026-06-08T17:02:28.913Z")
        self.assertEqual(day, "2026-06-08")

    def test_project_label_strips_wrapper(self) -> None:
        self.assertEqual(inspect_session.project_label(SLUG), "Users-me-code-github.com-org-repo")


class SummarizeTests(unittest.TestCase):
    def _summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = make_session_tree(root)
            sf = inspect_session.SessionFile(path, SLUG, SESSION_ID, "2026-06-08T17:02:28.913Z", "2026-06-08")
            records, errors = inspect_session.load_records(path)
            return inspect_session.summarize_session(sf, records, errors)

    def test_metadata_and_counts(self) -> None:
        s = self._summary()
        self.assertEqual(s.format_version, 3)
        self.assertEqual(s.cwd, "/Users/me/code/github.com/org/repo")
        self.assertEqual(s.model_provider, "lmstudio")
        self.assertEqual(s.model_id, "qwen3.6-27b-mlx")
        self.assertEqual(s.thinking_level, "medium")
        self.assertEqual(s.user_message_count, 1)
        self.assertEqual(s.assistant_message_count, 3)
        self.assertEqual(s.tool_result_count, 2)
        self.assertEqual(s.thinking_block_count, 1)

    def test_token_and_cost_aggregation(self) -> None:
        s = self._summary()
        self.assertEqual(s.tok_input, 100 + 9000 + 50)
        self.assertEqual(s.tok_output, 20 + 80 + 10)
        self.assertEqual(s.tok_total, 9150 + 110)
        self.assertEqual(s.cost_total, 0.0)

    def test_first_user_message_and_pr_link(self) -> None:
        s = self._summary()
        self.assertIn("Fix the bug", s.first_user_message)
        self.assertIn("https://github.com/org/repo/pull/42", s.pr_links)

    def test_tool_calls_and_failures(self) -> None:
        s = self._summary()
        self.assertEqual(s.tool_calls["bash"], 1)
        self.assertEqual(s.tool_calls["subagent"], 1)
        self.assertEqual(s.tool_errors["bash"], 1)
        self.assertNotIn("subagent", s.tool_errors)

    def test_stop_reasons(self) -> None:
        s = self._summary()
        self.assertEqual(s.stop_reasons["toolUse"], 2)
        self.assertEqual(s.stop_reasons["stop"], 1)

    def test_context_and_compaction(self) -> None:
        s = self._summary()
        self.assertEqual(s.custom_types["plannotator"], 1)
        self.assertEqual(s.custom_message_types["pi-memory-context"], 1)
        self.assertEqual(len(s.compactions), 1)
        self.assertEqual(s.compactions[0]["tokensBefore"], 12345)

    def test_subagent_extraction(self) -> None:
        s = self._summary()
        self.assertEqual(len(s.subagent_invocations), 1)
        sa = s.subagent_invocations[0]
        self.assertEqual(sa["mode"], "single")
        self.assertEqual(sa["agent"], "worker")
        self.assertEqual(sa["model"], "qwen3.6-27b-mlx")
        self.assertEqual(sa["usage"]["input"], 25289)
        self.assertEqual(sa["usage"]["turns"], 1)
        self.assertEqual(sa["tool_calls"], {"read": 1})


class RecorderDbTests(unittest.TestCase):
    def test_open_read_only_and_join(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_session_tree(root)
            make_recorder_db(root)
            conn = inspect_session.open_recorder_ro(root / "recorder.db")
            self.assertIsNotNone(conn)
            assert conn is not None
            # Read-only: a write must fail.
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("UPDATE sessions SET total_cost=1;")
            row = inspect_session.db_session_row(conn, SESSION_ID)
            self.assertIsNotNone(row)
            td = inspect_session.db_turn_durations(conn, SESSION_ID)
            self.assertEqual(td["iterations"], 2)
            self.assertEqual(td["total_duration_ms"], 46000)
            nulls = inspect_session.db_null_file_sessions(conn)
            self.assertEqual(len(nulls), 1)
            conn.close()

    def test_open_missing_db_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(inspect_session.open_recorder_ro(Path(tmp) / "nope.db"))


class CliTests(unittest.TestCase):
    def _run(self, root: Path, argv: list[str]) -> int:
        return inspect_session.main(["--pi-home", str(root), *argv])

    def test_jsonl_floor_no_db(self) -> None:
        # Every core verb must work with NO recorder.db present.
        # Global flags (--json/--profile) precede the subcommand, per sibling convention.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_session_tree(root)
            self.assertEqual(self._run(root, ["--json", "locate"]), 0)
            self.assertEqual(self._run(root, ["--json", "list"]), 0)
            self.assertEqual(self._run(root, ["--json", "summary", SESSION_ID]), 0)
            self.assertEqual(self._run(root, ["--json", "subagents", SESSION_ID]), 0)
            self.assertEqual(self._run(root, ["records", SESSION_ID, "--record-type", "compaction"]), 0)

    def test_ingestion_profile_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = make_session_tree(root)
            make_recorder_db(root)
            sf = inspect_session.SessionFile(path, SLUG, SESSION_ID, "2026-06-08T17:02:28.913Z", "2026-06-08")
            records, errors = inspect_session.load_records(path)
            s = inspect_session.summarize_session(sf, records, errors)
            conn = inspect_session.open_recorder_ro(root / "recorder.db")
            assert conn is not None
            td = inspect_session.db_turn_durations(conn, SESSION_ID)
            conn.close()
            payload = inspect_session.build_ingestion(s, td, kind="session_summary")
            self.assertEqual(payload["schema_version"], "session_inspector_v2")
            self.assertEqual(payload["source"], "pi_coding_agent")
            self.assertEqual(payload["usage"]["tokens"]["mode"], "per_message")
            self.assertEqual(payload["turns"]["source"], "recorder.db")
            self.assertEqual(len(payload["subagents"]), 1)

    def test_ingestion_turns_jsonl_approx_without_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = make_session_tree(root)
            sf = inspect_session.SessionFile(path, SLUG, SESSION_ID, "2026-06-08T17:02:28.913Z", "2026-06-08")
            records, errors = inspect_session.load_records(path)
            s = inspect_session.summarize_session(sf, records, errors)
            payload = inspect_session.build_ingestion(s, None, kind="session_summary")
            self.assertEqual(payload["turns"]["source"], "jsonl_approx")
            self.assertIn("note", payload["turns"])


if __name__ == "__main__":
    unittest.main()
