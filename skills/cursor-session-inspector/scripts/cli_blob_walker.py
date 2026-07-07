from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_INDEX_DEPTH = 32


@dataclass(slots=True, frozen=True)
class CliAgentRow:
    workspace_hash: str
    agent_id: str
    store_db_path: Path
    latest_root_blob_id: str | None
    name: str | None
    mode: str | None
    created_at: int | None
    last_used_model: str | None
    meta: dict[str, Any]

    @property
    def session_id(self) -> str:
        return f"cli:{self.workspace_hash}:{self.agent_id}"


@dataclass(slots=True, frozen=True)
class Message:
    index: int
    blob_id: str
    kind: str
    role: str | None
    content: str | None
    payload: dict[str, Any] | None
    raw_text: str | None


def list_cli_agents(cursor_home: Path) -> list[CliAgentRow]:
    chats_dir = cursor_home.expanduser() / "chats"
    if not chats_dir.exists():
        return []
    agents: list[CliAgentRow] = []
    for store_db in sorted(chats_dir.glob("*/*/store.db")):
        try:
            meta = load_meta(store_db)
        except (sqlite3.Error, ValueError, OSError):
            continue
        agent_id = _string(meta.get("agentId")) or store_db.parent.name
        workspace_hash = store_db.parent.parent.name
        agents.append(
            CliAgentRow(
                workspace_hash=workspace_hash,
                agent_id=agent_id,
                store_db_path=store_db,
                latest_root_blob_id=_string(meta.get("latestRootBlobId")),
                name=_string(meta.get("name")),
                mode=_string(meta.get("mode")),
                created_at=_int(meta.get("createdAt")),
                last_used_model=_string(meta.get("lastUsedModel")),
                meta=meta,
            )
        )
    agents.sort(key=lambda item: item.created_at or 0, reverse=True)
    return agents


def load_meta(store_db_path: Path) -> dict[str, Any]:
    with closing(_connect(store_db_path)) as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = '0' OR key = 0 LIMIT 1").fetchone()
    if row is None:
        return {}
    value = row["value"]
    if isinstance(value, bytes):
        text = value.decode("utf-8")
    else:
        text = str(value)
    try:
        decoded = bytes.fromhex(text).decode("utf-8")
    except ValueError:
        decoded = text
    payload = json.loads(decoded)
    if not isinstance(payload, dict):
        raise ValueError(f"meta row is not a JSON object: {store_db_path}")
    return payload


def walk_messages(store_db_path: Path, *, root_blob_id: str | None = None) -> list[Message]:
    with closing(_connect(store_db_path)) as conn:
        blobs = {
            str(row["id"]).lower(): _bytes(row["data"])
            for row in conn.execute("SELECT id, data FROM blobs").fetchall()
        }
    if root_blob_id is None:
        root_blob_id = _string(load_meta(store_db_path).get("latestRootBlobId"))
    if root_blob_id is None:
        return []
    ordered_blob_ids: list[str] = []
    _walk_blob(root_blob_id.lower(), blobs, ordered_blob_ids, set(), depth=0)
    messages: list[Message] = []
    for blob_id in ordered_blob_ids:
        data = blobs.get(blob_id)
        if data is None:
            continue
        message = _decode_message(len(messages), blob_id, data)
        if message is not None:
            messages.append(message)
    return messages


def parse_index_children(data: bytes) -> list[str]:
    if not data.startswith(b"\x0a\x20"):
        return []
    offset = 0
    children: list[str] = []
    while offset < len(data):
        if offset + 34 > len(data) or data[offset] != 0x0A or data[offset + 1] != 0x20:
            return []
        children.append(data[offset + 2 : offset + 34].hex())
        offset += 34
    return children


def count_cli_agents(cursor_home: Path) -> int:
    return len(list_cli_agents(cursor_home))


def _walk_blob(
    blob_id: str,
    blobs: dict[str, bytes],
    ordered_blob_ids: list[str],
    visited: set[str],
    *,
    depth: int,
) -> None:
    if depth > MAX_INDEX_DEPTH or blob_id in visited:
        return
    visited.add(blob_id)
    data = blobs.get(blob_id)
    if data is None:
        return
    children = parse_index_children(data)
    if not children:
        ordered_blob_ids.append(blob_id)
        return
    for child_id in children:
        _walk_blob(child_id, blobs, ordered_blob_ids, visited, depth=depth + 1)


def _decode_message(index: int, blob_id: str, data: bytes) -> Message | None:
    text = data.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            role = _string(payload.get("role"))
            return Message(
                index=index,
                blob_id=blob_id,
                kind="json_message",
                role=role,
                content=_message_content(payload.get("content")),
                payload=payload,
                raw_text=text,
            )
    return Message(
        index=index,
        blob_id=blob_id,
        kind="raw_text",
        role=None,
        content=text if text else None,
        payload=None,
        raw_text=text,
    )


def _message_content(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(item.get("name"), str):
                    parts.append(str(item["name"]))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts) if parts else None
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, memoryview):
        return value.tobytes()
    if isinstance(value, str):
        return value.encode("utf-8")
    return bytes(value)


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
