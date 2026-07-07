from __future__ import annotations

import importlib.util
import json
import sqlite3
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


cli = load_module("test_cursor_cli_walker", ROOT / "scripts" / "cli_blob_walker.py")


class CliBlobWalkerTests(unittest.TestCase):
    def test_walks_root_index_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cursor_home = Path(temp) / ".cursor"
            store_db = cursor_home / "chats" / "workspace" / "agent-1" / "store.db"
            write_store_db(store_db)

            agents = cli.list_cli_agents(cursor_home)
            self.assertEqual(len(agents), 1)
            self.assertEqual(agents[0].session_id, "cli:workspace:agent-1")

            messages = cli.walk_messages(store_db)
            self.assertEqual([message.role for message in messages], ["user", "assistant"])
            self.assertEqual(messages[0].content, "hello")
            self.assertEqual(messages[1].content, "world")


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
    conn.execute("INSERT INTO blobs(id, data) VALUES(?, ?)", (user_id, json.dumps({"role": "user", "content": "hello"}).encode()))
    conn.execute("INSERT INTO blobs(id, data) VALUES(?, ?)", (assistant_id, json.dumps({"role": "assistant", "content": "world"}).encode()))
    root = b"\x0a\x20" + bytes.fromhex(user_id) + b"\x0a\x20" + bytes.fromhex(assistant_id)
    conn.execute("INSERT INTO blobs(id, data) VALUES(?, ?)", (root_id, root))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    unittest.main()
