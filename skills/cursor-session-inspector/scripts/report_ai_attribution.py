#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# ///
"""Report Cursor AI code attribution from the local Cursor tracking database."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import defaultdict
from contextlib import closing
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def _load_module(module_name: str, filename: str) -> Any:
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    module_path = SCRIPT_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


DB = _load_module("cursor_session_inspector_db", "db.py")
IMPORTER = _load_module("cursor_session_inspector_importer", "importer.py")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        rows = load_report_rows(
            args.cursor_home,
            begin=args.begin,
            end=args.end,
            group_by=args.group_by,
            limit=args.limit,
        )
        if args.json:
            print(json.dumps(rows, indent=2, sort_keys=True))
        else:
            print_table(rows, group_by=args.group_by)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report Cursor AI code attribution.",
        suggest_on_error=True,
    )
    parser.add_argument(
        "--cursor-home",
        type=Path,
        default=Path(os.environ.get("CURSOR_HOME", Path.home() / ".cursor")),
    )
    parser.add_argument("--begin", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--by", dest="group_by", choices=("commit", "session", "day", "branch"), default="commit")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def load_report_rows(
    cursor_home: Path,
    *,
    begin: date | None,
    end: date | None,
    group_by: str,
    limit: int,
) -> list[dict[str, Any]]:
    cursor_home = cursor_home.expanduser()
    db_path = IMPORTER.resolve_db_path(cursor_home)
    ensure_ai_cache(cursor_home, db_path)
    with closing(DB.open_db(db_path)) as conn:
        if group_by == "commit":
            rows = [dict(row) for row in conn.execute("SELECT * FROM commit_scores").fetchall()]
            filtered = [row for row in rows if _date_in_range(_commit_date(row.get("commit_date")), begin, end)]
            filtered.sort(key=lambda row: (_commit_date(row.get("commit_date")) or date.min, row.get("commit_hash") or ""), reverse=True)
            return [_commit_row(row) for row in filtered[:limit]]
        if group_by == "branch":
            rows = [dict(row) for row in conn.execute("SELECT * FROM commit_scores").fetchall()]
            filtered = [row for row in rows if _date_in_range(_commit_date(row.get("commit_date")), begin, end)]
            grouped = group_commit_rows(filtered, key="branch_name")
            return sorted(grouped, key=lambda row: row["lines_changed"], reverse=True)[:limit]
        if group_by == "day":
            rows = [dict(row) for row in conn.execute("SELECT * FROM commit_scores").fetchall()]
            filtered = [row for row in rows if _date_in_range(_commit_date(row.get("commit_date")), begin, end)]
            grouped = group_commit_rows(filtered, key="day")
            return sorted(grouped, key=lambda row: row["name"], reverse=True)[:limit]
        if group_by == "session":
            rows = [dict(row) for row in conn.execute("SELECT * FROM ai_code_chunks").fetchall()]
            filtered = [row for row in rows if _date_in_range(_ms_date(row.get("timestamp") or row.get("created_at")), begin, end)]
            grouped: dict[str, dict[str, Any]] = {}
            for row in filtered:
                conversation_id = row.get("conversation_id") or "(missing)"
                target = grouped.setdefault(
                    conversation_id,
                    {
                        "session_id": conversation_id,
                        "ai_code_hashes": 0,
                        "models": set(),
                        "sources": defaultdict(int),
                        "first_seen": None,
                        "last_seen": None,
                    },
                )
                target["ai_code_hashes"] += 1
                if row.get("model"):
                    target["models"].add(row["model"])
                if row.get("source"):
                    target["sources"][row["source"]] += 1
                ts = row.get("timestamp") or row.get("created_at")
                target["first_seen"] = min(_none_high(target["first_seen"]), ts)
                target["last_seen"] = max(target["last_seen"] or 0, ts or 0)
            result = []
            for value in grouped.values():
                result.append(
                    {
                        "session_id": value["session_id"],
                        "ai_code_hashes": value["ai_code_hashes"],
                        "models": sorted(value["models"]),
                        "sources": dict(value["sources"]),
                        "first_seen": _ms_iso(value["first_seen"]),
                        "last_seen": _ms_iso(value["last_seen"]),
                    }
                )
            return sorted(result, key=lambda row: row["ai_code_hashes"], reverse=True)[:limit]
    raise ValueError(f"unsupported report grouping: {group_by}")


def ensure_ai_cache(cursor_home: Path, db_path: Path) -> None:
    ai_only_app_support = cursor_home / "__missing_app_support__"
    if not db_path.exists():
        IMPORTER.refresh_sessions(
            cursor_home,
            app_support=ai_only_app_support,
            target="__cursor_ai_tracking_only__",
            reconcile=False,
            analyze=False,
        )
        return
    with closing(DB.open_db(db_path)) as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM ai_code_chunks").fetchone()
        if row is None or int(row["count"]) == 0:
            IMPORTER.refresh_sessions(
                cursor_home,
                app_support=ai_only_app_support,
                target="__cursor_ai_tracking_only__",
                reconcile=False,
                analyze=False,
            )


def group_commit_rows(rows: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if key == "day":
            group_name = (_commit_date(row.get("commit_date")) or date.min).isoformat()
        else:
            group_name = str(row.get(key) or "(missing)")
        target = grouped.setdefault(
            group_name,
            {
                "name": group_name,
                "commit_count": 0,
                "lines_added": 0,
                "lines_deleted": 0,
                "composer_lines_changed": 0,
                "tab_lines_changed": 0,
                "human_lines_changed": 0,
                "blank_lines_changed": 0,
                "ai_percentage_weighted": None,
            },
        )
        target["commit_count"] += 1
        target["lines_added"] += int(row.get("lines_added") or 0)
        target["lines_deleted"] += int(row.get("lines_deleted") or 0)
        target["composer_lines_changed"] += int(row.get("composer_lines_added") or 0) + int(row.get("composer_lines_deleted") or 0)
        target["tab_lines_changed"] += int(row.get("tab_lines_added") or 0) + int(row.get("tab_lines_deleted") or 0)
        target["human_lines_changed"] += int(row.get("human_lines_added") or 0) + int(row.get("human_lines_deleted") or 0)
        target["blank_lines_changed"] += int(row.get("blank_lines_added") or 0) + int(row.get("blank_lines_deleted") or 0)
    for row in grouped.values():
        row["lines_changed"] = row["lines_added"] + row["lines_deleted"]
        ai_lines = row["composer_lines_changed"] + row["tab_lines_changed"]
        row["ai_percentage_weighted"] = round(100 * ai_lines / row["lines_changed"], 2) if row["lines_changed"] else None
    return list(grouped.values())


def _commit_row(row: dict[str, Any]) -> dict[str, Any]:
    lines_changed = int(row.get("lines_added") or 0) + int(row.get("lines_deleted") or 0)
    return {
        "commit_hash": row.get("commit_hash"),
        "branch_name": row.get("branch_name"),
        "commit_date": row.get("commit_date"),
        "commit_message": row.get("commit_message"),
        "lines_added": row.get("lines_added"),
        "lines_deleted": row.get("lines_deleted"),
        "lines_changed": lines_changed,
        "composer_lines_changed": int(row.get("composer_lines_added") or 0) + int(row.get("composer_lines_deleted") or 0),
        "tab_lines_changed": int(row.get("tab_lines_added") or 0) + int(row.get("tab_lines_deleted") or 0),
        "human_lines_changed": int(row.get("human_lines_added") or 0) + int(row.get("human_lines_deleted") or 0),
        "v1_ai_percentage": _decimal_string(row.get("v1_ai_percentage")),
        "v2_ai_percentage": _decimal_string(row.get("v2_ai_percentage")),
    }


def print_table(rows: list[dict[str, Any]], *, group_by: str) -> None:
    if not rows:
        print("No rows.")
        return
    if group_by == "commit":
        headers = ("commit", "date", "v2_ai", "changed", "message")
        print("{:<12} {:<10} {:>7} {:>8} {}".format(*headers))
        for row in rows:
            commit = str(row.get("commit_hash") or "")[:12]
            day = str(_commit_date(row.get("commit_date")) or "")
            print(
                "{:<12} {:<10} {:>7} {:>8} {}".format(
                    commit,
                    day,
                    row.get("v2_ai_percentage") or "",
                    row.get("lines_changed") or 0,
                    row.get("commit_message") or "",
                )
            )
        return
    if group_by == "session":
        print("{:<38} {:>8} {}".format("session", "hashes", "models"))
        for row in rows:
            print("{:<38} {:>8} {}".format(row["session_id"], row["ai_code_hashes"], ",".join(row["models"])))
        return
    print("{:<40} {:>7} {:>8} {:>7}".format(group_by, "commits", "changed", "ai_pct"))
    for row in rows:
        print(
            "{:<40} {:>7} {:>8} {:>7}".format(
                row["name"][:40],
                row["commit_count"],
                row["lines_changed"],
                row["ai_percentage_weighted"] if row["ai_percentage_weighted"] is not None else "",
            )
        )


def _commit_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.strptime(value, "%a %b %d %H:%M:%S %Y %z")
    except ValueError:
        return None
    return parsed.date()


def _date_in_range(value: date | None, begin: date | None, end: date | None) -> bool:
    if value is None:
        return begin is None and end is None
    if begin is not None and value < begin:
        return False
    if end is not None and value > end:
        return False
    return True


def _ms_date(value: Any) -> date | None:
    if not isinstance(value, int):
        return None
    return datetime.fromtimestamp(value / 1000, UTC).date()


def _ms_iso(value: Any) -> str | None:
    if not isinstance(value, int) or value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _none_high(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 2**63 - 1


def _decimal_string(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return str(value)


if __name__ == "__main__":
    sys.exit(main())
