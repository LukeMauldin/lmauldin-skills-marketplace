from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class ComposerRow:
    composer_id: str
    key: str
    payload: dict[str, Any]
    header: dict[str, Any] | None

    @property
    def bubble_headers(self) -> list[dict[str, Any]]:
        headers = self.payload.get("fullConversationHeadersOnly")
        return headers if isinstance(headers, list) else []

    @property
    def bubble_ids(self) -> list[str]:
        result: list[str] = []
        for header in self.bubble_headers:
            if not isinstance(header, dict):
                continue
            bubble_id = header.get("bubbleId")
            if isinstance(bubble_id, str) and bubble_id:
                result.append(bubble_id)
        return result


@dataclass(slots=True, frozen=True)
class BubbleRow:
    composer_id: str
    bubble_id: str
    key: str
    payload: dict[str, Any]


@dataclass(slots=True, frozen=True)
class BlobRow:
    blob_sha: str
    data: bytes
    json_value: Any
    is_encrypted: bool


def snapshot_state_vscdb(src: Path, dst: Path | None = None) -> Path:
    src = src.expanduser()
    if not src.exists():
        raise FileNotFoundError(src)
    if dst is None:
        fd, name = tempfile.mkstemp(prefix="cursor-state-", suffix=".vscdb")
        os.close(fd)
        target = Path(name)
    elif dst.is_dir():
        target = dst / f"cursor-state-{os.getpid()}.vscdb"
    else:
        target = dst
        target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return target


def list_composers(db_path: Path) -> Iterator[ComposerRow]:
    headers = _load_composer_headers(db_path)
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT key, value
            FROM cursorDiskKV
            WHERE key LIKE 'composerData:%'
            ORDER BY key
            """
        ).fetchall()
    composers: list[ComposerRow] = []
    for row in rows:
        key = str(row["key"])
        payload = _decode_json(row["value"])
        if not isinstance(payload, dict):
            continue
        composer_id = _string(payload.get("composerId")) or key.removeprefix("composerData:")
        composers.append(
            ComposerRow(
                composer_id=composer_id,
                key=key,
                payload=payload,
                header=headers.get(composer_id),
            )
        )
    composers.sort(key=lambda item: _int(item.payload.get("lastUpdatedAt")) or 0, reverse=True)
    yield from composers


def load_bubble(db_path: Path, composer_id: str, bubble_id: str) -> BubbleRow | None:
    key = f"bubbleId:{composer_id}:{bubble_id}"
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            "SELECT value FROM cursorDiskKV WHERE key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    payload = _decode_json(row["value"])
    if not isinstance(payload, dict):
        return None
    return BubbleRow(composer_id=composer_id, bubble_id=bubble_id, key=key, payload=payload)


def iter_bubbles(db_path: Path, composer: ComposerRow) -> Iterator[tuple[dict[str, Any], BubbleRow | None]]:
    for header in composer.bubble_headers:
        if not isinstance(header, dict):
            continue
        bubble_id = header.get("bubbleId")
        if not isinstance(bubble_id, str) or not bubble_id:
            continue
        yield header, load_bubble(db_path, composer.composer_id, bubble_id)


def load_blob(db_path: Path, blob_sha: str) -> BlobRow | None:
    key = f"agentKv:blob:{blob_sha}"
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            "SELECT value FROM cursorDiskKV WHERE key = ?",
            (key,),
        ).fetchone()
    if row is None:
        return None
    data = _bytes(row["value"])
    json_value: Any = None
    is_encrypted = False
    try:
        json_value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        is_encrypted = True
    return BlobRow(blob_sha=blob_sha, data=data, json_value=json_value, is_encrypted=is_encrypted)


def load_plan_registry(db_path: Path) -> dict[str, Any]:
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key = 'composer.planRegistry'",
        ).fetchone()
    if row is None:
        return {}
    payload = _decode_json(row["value"])
    return payload if isinstance(payload, dict) else {}


def count_ui_composers(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    try:
        with closing(_connect(db_path)) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM cursorDiskKV WHERE key LIKE 'composerData:%'",
            ).fetchone()
    except sqlite3.Error:
        return 0
    return int(row["count"]) if row else 0


def _load_composer_headers(db_path: Path) -> dict[str, dict[str, Any]]:
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key = 'composer.composerHeaders'",
        ).fetchone()
    if row is None:
        return {}
    payload = _decode_json(row["value"])
    if not isinstance(payload, dict):
        return {}
    all_composers = payload.get("allComposers")
    if not isinstance(all_composers, list):
        return {}
    headers: dict[str, dict[str, Any]] = {}
    for item in all_composers:
        if not isinstance(item, dict):
            continue
        composer_id = item.get("composerId")
        if isinstance(composer_id, str) and composer_id:
            headers[composer_id] = item
    return headers


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _decode_json(value: Any) -> Any:
    data = _bytes(value)
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _bytes(value: Any) -> bytes:
    if value is None:
        return b""
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
