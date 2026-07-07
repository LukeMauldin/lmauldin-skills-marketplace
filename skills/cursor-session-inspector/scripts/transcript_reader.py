from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class TranscriptSession:
    session_id: str
    path: Path
    project_slug: str | None
    parent_session_id: str | None
    is_subagent: bool
    mtime_ns: int
    size_bytes: int


def iter_transcripts(cursor_home: Path, *, include_subagents: bool = True) -> Iterator[TranscriptSession]:
    projects_dir = cursor_home.expanduser() / "projects"
    if not projects_dir.exists():
        return
    for path in sorted(projects_dir.glob("*/agent-transcripts/*/*.jsonl")):
        if not path.is_file():
            continue
        yield _session_from_path(path, is_subagent=False)
    if not include_subagents:
        return
    for path in sorted(projects_dir.glob("*/agent-transcripts/*/subagents/*.jsonl")):
        if not path.is_file():
            continue
        yield _session_from_path(path, is_subagent=True)


def load_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    parse_errors = 0
    if not path.exists():
        return records, parse_errors
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            parse_errors += 1
    return records, parse_errors


def first_user_message(records: list[dict[str, Any]]) -> str | None:
    for record in records:
        if record.get("role") != "user":
            continue
        text = message_text(record.get("message"))
        if text:
            return text
    return None


def message_text(message: Any) -> str | None:
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("text"), str):
            parts.append(item["text"])
        elif item.get("type") == "tool_use" and isinstance(item.get("name"), str):
            parts.append(f"[tool_use:{item['name']}]")
    return "\n".join(parts) if parts else None


def count_transcripts(cursor_home: Path) -> int:
    return sum(1 for _ in iter_transcripts(cursor_home, include_subagents=False))


def _session_from_path(path: Path, *, is_subagent: bool) -> TranscriptSession:
    stat = path.stat()
    session_id = path.stem
    parent_session_id: str | None = None
    if is_subagent:
        parent_session_id = path.parent.parent.name
    project_slug = None
    parts = path.parts
    if "projects" in parts:
        index = parts.index("projects")
        if index + 1 < len(parts):
            project_slug = parts[index + 1]
    return TranscriptSession(
        session_id=session_id,
        path=path,
        project_slug=project_slug,
        parent_session_id=parent_session_id,
        is_subagent=is_subagent,
        mtime_ns=stat.st_mtime_ns,
        size_bytes=stat.st_size,
    )
