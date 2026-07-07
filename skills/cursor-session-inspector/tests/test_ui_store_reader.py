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


ui = load_module("test_cursor_ui_reader", ROOT / "scripts" / "ui_store_reader.py")


class UiStoreReaderTests(unittest.TestCase):
    def test_reads_composers_and_bubbles(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "state.vscdb"
            write_state_db(db_path)

            composers = list(ui.list_composers(db_path))
            self.assertEqual([item.composer_id for item in composers], ["composer-1"])
            self.assertEqual(composers[0].bubble_ids, ["u1", "a1"])

            bubble = ui.load_bubble(db_path, "composer-1", "a1")
            self.assertIsNotNone(bubble)
            assert bubble is not None
            self.assertEqual(bubble.payload["requestId"], "req-1")
            self.assertEqual(ui.count_ui_composers(db_path), 1)


def write_state_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    conn.execute("CREATE TABLE cursorDiskKV (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
    composer = {
        "_v": 14,
        "composerId": "composer-1",
        "name": "Fixture Composer",
        "createdAt": 1770000000000,
        "lastUpdatedAt": 1770000001000,
        "fullConversationHeadersOnly": [
            {"bubbleId": "u1", "type": 1, "grouping": {}},
            {"bubbleId": "a1", "type": 2, "grouping": {"toolCallId": "tool-1"}},
        ],
    }
    conn.execute(
        "INSERT INTO ItemTable(key, value) VALUES(?, ?)",
        (
            "composer.composerHeaders",
            json.dumps({"allComposers": [{"composerId": "composer-1", "name": "Fixture Composer"}]}).encode(),
        ),
    )
    conn.execute("INSERT INTO cursorDiskKV(key, value) VALUES(?, ?)", ("composerData:composer-1", json.dumps(composer).encode()))
    conn.execute(
        "INSERT INTO cursorDiskKV(key, value) VALUES(?, ?)",
        ("bubbleId:composer-1:u1", json.dumps({"_v": 3, "bubbleId": "u1", "type": 1, "text": "hello"}).encode()),
    )
    conn.execute(
        "INSERT INTO cursorDiskKV(key, value) VALUES(?, ?)",
        (
            "bubbleId:composer-1:a1",
            json.dumps({"_v": 3, "bubbleId": "a1", "type": 2, "requestId": "req-1", "text": "world"}).encode(),
        ),
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    unittest.main()
