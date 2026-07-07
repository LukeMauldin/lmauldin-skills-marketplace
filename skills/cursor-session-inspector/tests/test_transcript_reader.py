from __future__ import annotations

import importlib.util
import json
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


transcripts = load_module("test_cursor_transcripts", ROOT / "scripts" / "transcript_reader.py")


class TranscriptReaderTests(unittest.TestCase):
    def test_reads_transcript_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            cursor_home = Path(temp) / ".cursor"
            path = cursor_home / "projects" / "proj" / "agent-transcripts" / "session-1" / "session-1.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text(
                "\n".join(
                    json.dumps(row)
                    for row in [
                        {"role": "user", "message": {"content": [{"type": "text", "text": "hello"}]}},
                        {"role": "assistant", "message": {"content": [{"type": "text", "text": "world"}]}},
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            sessions = list(transcripts.iter_transcripts(cursor_home))
            self.assertEqual(len(sessions), 1)
            records, errors = transcripts.load_records(path)
            self.assertEqual(errors, 0)
            self.assertEqual(transcripts.first_user_message(records), "hello")


if __name__ == "__main__":
    unittest.main()
