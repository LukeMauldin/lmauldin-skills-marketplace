from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "report_api_costs.py"
SPEC = importlib.util.spec_from_file_location("report_api_costs", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"failed to load module from {SCRIPT_PATH}")
report_api_costs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = report_api_costs
SPEC.loader.exec_module(report_api_costs)

DB_PATH = ROOT / "scripts" / "db.py"
DB_SPEC = importlib.util.spec_from_file_location("report_test_db", DB_PATH)
if DB_SPEC is None or DB_SPEC.loader is None:
    raise RuntimeError(f"failed to load module from {DB_PATH}")
db_mod = importlib.util.module_from_spec(DB_SPEC)
sys.modules[DB_SPEC.name] = db_mod
DB_SPEC.loader.exec_module(db_mod)


SESSION_ID = "test-session-001"


def insert_session(
    conn: sqlite3.Connection,
    *,
    session_id: str = SESSION_ID,
    model: str = "claude-opus-4-6",
    start_timestamp: str = "2026-04-10T12:00:00Z",
    is_subagent: int = 0,
    parent_session_id: str | None = None,
    slug: str | None = "test-slug",
    custom_title: str | None = None,
    project: str | None = "/tmp/demo",
) -> None:
    conn.execute(
        """
        INSERT INTO sessions(
            session_id, source, file_path, model, start_timestamp,
            is_subagent, parent_session_id, slug, custom_title, project
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id, "claude", f"/tmp/{session_id}.jsonl", model,
            start_timestamp, is_subagent, parent_session_id,
            slug, custom_title, project,
        ),
    )


def insert_turn(
    conn: sqlite3.Connection,
    *,
    session_id: str = SESSION_ID,
    turn_index: int = 0,
    timestamp: str = "2026-04-10T12:00:01Z",
    model: str = "claude-opus-4-6",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read: int = 0,
    cache_create: int = 0,
    cache_create_5m: int | None = None,
    cache_create_1h: int = 0,
    speed: str | None = None,
) -> int:
    # Mirror the importer's reconciliation contract: 5m + 1h == aggregate.
    # Default unsplit cache writes to all-5m (the historical 1.25x assumption).
    if cache_create_5m is None:
        cache_create_5m = max(cache_create - cache_create_1h, 0)
    cur = conn.execute(
        """
        INSERT INTO turns(
            session_id, turn_index, timestamp, model, speed,
            input_tokens, output_tokens, cache_read,
            cache_create, cache_create_5m, cache_create_1h
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, turn_index, timestamp, model, speed,
         input_tokens, output_tokens, cache_read,
         cache_create, cache_create_5m, cache_create_1h),
    )
    return int(cur.lastrowid or 0)


def insert_server_tool_call(
    conn: sqlite3.Connection,
    *,
    turn_id: int,
    session_id: str = SESSION_ID,
    tool_name: str = "advisor",
    tool_use_id: str = "srvtoolu_test_0",
    iteration_type: str = "advisor_message",
    iteration_model: str | None = "claude-opus-4-6",
    iteration_input_tokens: int = 0,
    iteration_output_tokens: int = 0,
    iteration_cache_read: int = 0,
    iteration_cache_create: int = 0,
    iteration_cache_create_5m: int | None = None,
    iteration_cache_create_1h: int = 0,
    is_aborted: int = 0,
) -> None:
    if iteration_cache_create_5m is None:
        iteration_cache_create_5m = max(iteration_cache_create - iteration_cache_create_1h, 0)
    conn.execute(
        """
        INSERT INTO server_tool_calls(
            turn_id, session_id, tool_name, tool_use_id,
            iteration_type, iteration_model,
            iteration_input_tokens, iteration_output_tokens,
            iteration_cache_read, iteration_cache_create,
            iteration_cache_create_5m, iteration_cache_create_1h,
            is_aborted
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            turn_id, session_id, tool_name, tool_use_id,
            iteration_type, iteration_model,
            iteration_input_tokens, iteration_output_tokens,
            iteration_cache_read, iteration_cache_create,
            iteration_cache_create_5m, iteration_cache_create_1h,
            is_aborted,
        ),
    )


class ReportApiCostsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.claude_home = self.root / ".claude"
        self.db_path = db_mod.default_db_path(self.claude_home)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = db_mod.open_db(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()
        self.temp_dir.cleanup()

    def build_report(self, **overrides: Any) -> dict[str, Any]:
        self.conn.commit()
        return report_api_costs.build_report(
            claude_home=self.claude_home,
            begin_at=datetime(2026, 4, 10, 0, 0, tzinfo=UTC),
            end_at=datetime(2026, 4, 10, 23, 59, 59, tzinfo=UTC),
            display_timezone=UTC,
            exclude_subagents=bool(overrides.pop("exclude_subagents", False)),
            unknown_model_policy=str(overrides.pop("unknown_model_policy", "closest-family")),
            **overrides,
        )

    # ---------------------------------------------------------------
    # Core pricing tests
    # ---------------------------------------------------------------

    def test_opus_46_cost_all_four_categories(self) -> None:
        """Verify the 4-component cost formula for Opus 4.6."""
        insert_session(self.conn)
        insert_turn(
            self.conn,
            input_tokens=1_000_000,
            cache_read=500_000,
            cache_create=200_000,
            output_tokens=100_000,
        )

        report = self.build_report()

        # input:       1M × $5.00/M  = $5.00
        # cache_read:  500K × $0.50/M = $0.25
        # cache_write: 200K × $6.25/M = $1.25
        # output:      100K × $25.00/M = $2.50
        # total = $9.00
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 9.00, places=2)

    def test_sonnet_46_cost(self) -> None:
        insert_session(self.conn, model="claude-sonnet-4-6")
        insert_turn(
            self.conn,
            model="claude-sonnet-4-6",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )

        report = self.build_report()

        # input: 1M × $3.00/M = $3.00, output: 100K × $15.00/M = $1.50
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 4.50, places=2)

    def test_haiku_45_with_snapshot_suffix(self) -> None:
        """Model ID with YYYYMMDD suffix resolves to base model pricing."""
        insert_session(self.conn, model="claude-haiku-4-5-20251001")
        insert_turn(
            self.conn,
            model="claude-haiku-4-5-20251001",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )

        report = self.build_report()

        # input: 1M × $1.00/M = $1.00, output: 100K × $5.00/M = $0.50
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 1.50, places=2)
        self.assertEqual(report["by_model"][0]["model"], "claude-haiku-4-5")

    # ---------------------------------------------------------------
    # Cache-write TTL pricing tests
    # ---------------------------------------------------------------

    def test_cache_write_1h_priced_at_2x(self) -> None:
        """1-hour cache writes bill at 2x base input, not 1.25x."""
        insert_session(self.conn, model="claude-opus-4-6")
        insert_turn(
            self.conn,
            model="claude-opus-4-6",
            cache_create=200_000,
            cache_create_5m=0,
            cache_create_1h=200_000,
        )

        report = self.build_report()

        # 1h write: 200K × ($5 × 2)/M = 200K × $10/M = $2.00
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 2.00, places=2)
        self.assertEqual(report["totals"]["cache_write_1h_tokens"], 200_000)
        self.assertEqual(report["totals"]["cache_write_5m_tokens"], 0)

    def test_cache_write_mixed_5m_and_1h(self) -> None:
        """A turn with both TTLs prices each portion at its own rate."""
        insert_session(self.conn, model="claude-opus-4-6")
        insert_turn(
            self.conn,
            model="claude-opus-4-6",
            cache_create=300_000,
            cache_create_5m=100_000,
            cache_create_1h=200_000,
        )

        report = self.build_report()

        # 5m: 100K × $6.25/M = $0.625 ; 1h: 200K × $10/M = $2.00 ; total $2.625
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 2.625, places=3)
        self.assertEqual(report["totals"]["cache_write_5m_tokens"], 100_000)
        self.assertEqual(report["totals"]["cache_write_1h_tokens"], 200_000)
        self.assertEqual(report["totals"]["cache_write_tokens"], 300_000)

    def test_cache_write_unsplit_defaults_to_5m(self) -> None:
        """Legacy rows with only the aggregate price all-5m (1.25x)."""
        insert_session(self.conn, model="claude-opus-4-6")
        insert_turn(self.conn, model="claude-opus-4-6", cache_create=200_000)

        report = self.build_report()

        # all-5m: 200K × $6.25/M = $1.25
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 1.25, places=2)
        self.assertEqual(report["totals"]["cache_write_5m_tokens"], 200_000)
        self.assertEqual(report["totals"]["cache_write_1h_tokens"], 0)

    def test_cache_write_1h_fast_mode_doubles_off_fast_rate(self) -> None:
        """1h cache writes on a fast turn derive 2x off the fast input rate."""
        insert_session(self.conn, model="claude-opus-4-8")
        insert_turn(
            self.conn,
            model="claude-opus-4-8",
            speed="fast",
            cache_create=100_000,
            cache_create_5m=0,
            cache_create_1h=100_000,
        )

        report = self.build_report()

        # fast input rate = $10/M; 1h = 2x = $20/M; 100K × $20/M = $2.00
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 2.00, places=2)
        self.assertEqual(report["fast_mode"]["fast_events"], 1)

    def test_server_tool_1h_cache_write_priced_at_2x(self) -> None:
        """Server-tool iteration 1h cache writes also bill at 2x."""
        insert_session(self.conn, model="claude-opus-4-6")
        turn_id = insert_turn(self.conn, model="claude-opus-4-6", input_tokens=1_000)
        insert_server_tool_call(
            self.conn,
            turn_id=turn_id,
            iteration_input_tokens=0,
            iteration_cache_create=100_000,
            iteration_cache_create_5m=0,
            iteration_cache_create_1h=100_000,
        )

        report = self.build_report()

        # parent: 1K × $5/M = $0.005 ; advisor 1h write: 100K × $10/M = $1.00
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 1.005, places=3)
        self.assertEqual(report["by_server_tool"][0]["cache_write_tokens"], 100_000)

    # ---------------------------------------------------------------
    # Fast mode pricing tests
    # ---------------------------------------------------------------

    def test_opus_48_fast_mode_doubles_rate(self) -> None:
        """Opus 4.8 fast mode bills input/output at $10/$50 (2x standard)."""
        insert_session(self.conn, model="claude-opus-4-8")
        insert_turn(
            self.conn,
            model="claude-opus-4-8",
            speed="fast",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )

        report = self.build_report()

        # fast input: 1M × $10/M = $10.00, fast output: 100K × $50/M = $5.00
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 15.00, places=2)
        self.assertEqual(report["scan"]["fast_turns"], 1)
        self.assertEqual(report["fast_mode"]["fast_events"], 1)
        self.assertAlmostEqual(report["fast_mode"]["estimated_cost_usd"], 15.00, places=2)

    def test_opus_47_fast_mode_six_x_rate(self) -> None:
        """Opus 4.7 fast mode bills input/output at $30/$150 (6x standard)."""
        insert_session(self.conn, model="claude-opus-4-7")
        insert_turn(
            self.conn,
            model="claude-opus-4-7",
            speed="fast",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )

        report = self.build_report()

        # fast input: 1M × $30/M = $30.00, fast output: 100K × $150/M = $15.00
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 45.00, places=2)

    def test_standard_speed_uses_standard_rate(self) -> None:
        """An explicit speed='standard' prices identically to no speed value."""
        insert_session(self.conn, model="claude-opus-4-8")
        insert_turn(
            self.conn,
            model="claude-opus-4-8",
            speed="standard",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )

        report = self.build_report()

        # standard: 1M × $5 + 100K × $25 = $5.00 + $2.50 = $7.50
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 7.50, places=2)
        self.assertEqual(report["scan"]["fast_turns"], 0)
        self.assertEqual(report["fast_mode"]["fast_events"], 0)

    def test_unknown_speed_prices_standard_and_counts(self) -> None:
        """An unrecognized speed value is priced standard and surfaced via a counter."""
        insert_session(self.conn, model="claude-opus-4-8")
        insert_turn(
            self.conn,
            model="claude-opus-4-8",
            speed="turbo",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )

        report = self.build_report()

        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 7.50, places=2)
        self.assertEqual(report["scan"]["unknown_speed_turns"], 1)
        self.assertEqual(report["scan"]["fast_turns"], 0)

    def test_fast_speed_on_non_opus_falls_back_to_standard(self) -> None:
        """Fast mode is Opus-only; fast speed on Sonnet prices standard + counts."""
        insert_session(self.conn, model="claude-sonnet-4-6")
        insert_turn(
            self.conn,
            model="claude-sonnet-4-6",
            speed="fast",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )

        report = self.build_report()

        # standard sonnet: 1M × $3 + 100K × $15 = $3.00 + $1.50 = $4.50
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 4.50, places=2)
        self.assertEqual(report["scan"]["fast_speed_without_fast_price"], 1)
        self.assertEqual(report["scan"]["fast_turns"], 0)

    def test_server_tool_inherits_parent_fast_speed(self) -> None:
        """A server-tool iteration on a fast turn is also fast-priced."""
        insert_session(self.conn, model="claude-opus-4-8")
        turn_id = insert_turn(
            self.conn,
            model="claude-opus-4-8",
            speed="fast",
            input_tokens=1_000_000,
            output_tokens=100_000,
        )
        insert_server_tool_call(
            self.conn,
            turn_id=turn_id,
            iteration_model="claude-opus-4-8",
            iteration_input_tokens=200_000,
            iteration_output_tokens=10_000,
        )

        report = self.build_report()

        # parent fast: 1M × $10 + 100K × $50 = $10.00 + $5.00 = $15.00
        # advisor fast iter: 200K × $10 + 10K × $50 = $2.00 + $0.50 = $2.50
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 17.50, places=2)
        # Both the turn and the server-tool iteration are fast events.
        self.assertEqual(report["fast_mode"]["fast_events"], 2)

    def test_advisor_iteration_adds_separate_cost(self) -> None:
        """Server-tool iterations are billed in addition to the parent turn."""
        insert_session(self.conn)
        turn_id = insert_turn(
            self.conn,
            input_tokens=1_000_000,
            output_tokens=100_000,
        )
        # Advisor iteration on Opus 4.6: 200k input + 10k output.
        # 200k × $5/M + 10k × $25/M = $1.00 + $0.25 = $1.25 additive.
        insert_server_tool_call(
            self.conn,
            turn_id=turn_id,
            iteration_input_tokens=200_000,
            iteration_output_tokens=10_000,
        )

        report = self.build_report()

        # Parent turn: 1M × $5 + 100k × $25 = $5.00 + $2.50 = $7.50
        # Advisor iter: $1.25
        # Total: $8.75
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 8.75, places=2)
        self.assertEqual(report["scan"]["server_tool_iterations_in_range"], 1)
        self.assertEqual(report["scan"]["server_tool_priced"], 1)
        self.assertEqual(report["scan"]["turns_in_range"], 1)
        self.assertEqual(len(report["by_server_tool"]), 1)
        advisor_row = report["by_server_tool"][0]
        self.assertEqual(advisor_row["tool_name"], "advisor")
        self.assertEqual(advisor_row["calls"], 1)
        self.assertEqual(advisor_row["input_tokens"], 200_000)
        self.assertEqual(advisor_row["output_tokens"], 10_000)
        self.assertAlmostEqual(advisor_row["estimated_cost_usd"], 1.25, places=2)

    def test_aborted_server_tool_call_skipped(self) -> None:
        """Aborted server-tool calls contribute no cost even if tokens recorded."""
        insert_session(self.conn)
        turn_id = insert_turn(
            self.conn,
            input_tokens=1_000_000,
            output_tokens=100_000,
        )
        insert_server_tool_call(
            self.conn,
            turn_id=turn_id,
            iteration_input_tokens=999_999,
            iteration_output_tokens=999_999,
            is_aborted=1,
        )

        report = self.build_report()

        # Only the parent turn is billed.
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 7.50, places=2)
        self.assertEqual(report["scan"]["server_tool_iterations_in_range"], 0)
        self.assertEqual(report["by_server_tool"], [])

    def test_zero_token_turns_skipped(self) -> None:
        insert_session(self.conn)
        insert_turn(self.conn, input_tokens=0, output_tokens=0)

        report = self.build_report()

        self.assertEqual(report["scan"]["turns_in_range"], 0)
        self.assertEqual(report["scan"]["zero_token_turns_skipped"], 1)

    # ---------------------------------------------------------------
    # Model resolution tests
    # ---------------------------------------------------------------

    def test_unknown_model_excluded(self) -> None:
        insert_session(self.conn, model="claude-unknown-9-9")
        insert_turn(self.conn, model="claude-unknown-9-9", input_tokens=100, output_tokens=10)

        report = self.build_report(unknown_model_policy="exclude")

        self.assertEqual(report["totals"]["estimated_cost_usd"], 0.0)
        self.assertEqual(report["scan"]["unpriced_turns"], 1)
        self.assertEqual(report["unpriced"][0]["key"], "claude-unknown-9-9")

    def test_closest_family_maps_legacy_model(self) -> None:
        insert_session(self.conn, model="claude-3-5-sonnet")
        insert_turn(self.conn, model="claude-3-5-sonnet", input_tokens=100, output_tokens=10)

        report = self.build_report(unknown_model_policy="closest-family")

        self.assertEqual(report["by_model"][0]["model"], "claude-sonnet-4-0")
        self.assertEqual(report["scan"]["estimated_model_mapping_turns"], 1)

    def test_missing_model_falls_back_to_session_model(self) -> None:
        insert_session(self.conn, model="claude-opus-4-6")
        insert_turn(self.conn, model=None, input_tokens=100, output_tokens=10)

        report = self.build_report()

        # COALESCE(t.model, s.model) should resolve to session model
        self.assertEqual(report["by_model"][0]["model"], "claude-opus-4-6")
        self.assertGreater(report["totals"]["estimated_cost_usd"], 0)

    # ---------------------------------------------------------------
    # Subagent handling tests
    # ---------------------------------------------------------------

    def test_subagent_turns_included_by_default(self) -> None:
        insert_session(self.conn, session_id="parent-001")
        insert_turn(self.conn, session_id="parent-001", input_tokens=100, output_tokens=10)
        insert_session(
            self.conn,
            session_id="subagent-001",
            is_subagent=1,
            parent_session_id="parent-001",
        )
        insert_turn(
            self.conn,
            session_id="subagent-001",
            turn_index=0,
            input_tokens=200,
            output_tokens=20,
        )

        report = self.build_report()

        self.assertEqual(report["totals"]["session_count"], 2)
        self.assertEqual(report["totals"]["input_tokens"], 300)
        self.assertEqual(report["totals"]["output_tokens"], 30)

    def test_subagent_turns_excluded_when_flag_set(self) -> None:
        insert_session(self.conn, session_id="parent-001")
        insert_turn(self.conn, session_id="parent-001", input_tokens=100, output_tokens=10)
        insert_session(
            self.conn,
            session_id="subagent-001",
            is_subagent=1,
            parent_session_id="parent-001",
        )
        insert_turn(
            self.conn,
            session_id="subagent-001",
            turn_index=0,
            input_tokens=200,
            output_tokens=20,
        )

        report = self.build_report(exclude_subagents=True)

        self.assertEqual(report["totals"]["session_count"], 1)
        self.assertEqual(report["totals"]["input_tokens"], 100)

    # ---------------------------------------------------------------
    # Project filter tests
    # ---------------------------------------------------------------

    def test_project_filter_restricts_to_matching_sessions(self) -> None:
        insert_session(self.conn, session_id="s-alpha", project="/work/alpha-svc")
        insert_turn(self.conn, session_id="s-alpha", input_tokens=1_000_000, output_tokens=0)
        insert_session(self.conn, session_id="s-beta", project="/work/beta-svc")
        insert_turn(self.conn, session_id="s-beta", input_tokens=2_000_000, output_tokens=0)

        report = self.build_report(project="alpha")

        # Only alpha's 1M input × $5/M = $5.00 is counted.
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 5.00, places=2)
        self.assertEqual(report["totals"]["input_tokens"], 1_000_000)
        self.assertEqual(report["scan"]["project_filter"], "alpha")
        session_ids = {row["session_id"] for row in report["by_session"]}
        self.assertEqual(session_ids, {"s-alpha"})

    # ---------------------------------------------------------------
    # Report structure tests
    # ---------------------------------------------------------------

    def test_human_report_contains_core_sections(self) -> None:
        insert_session(self.conn)
        insert_turn(self.conn, input_tokens=100, output_tokens=10, cache_read=50)

        report = self.build_report()
        rendered = report_api_costs.render_human_report(report)

        self.assertIn("Claude API Cost Estimate", rendered)
        self.assertIn("By Day", rendered)
        self.assertIn("By Model", rendered)
        self.assertIn("Top Sessions", rendered)
        self.assertIn("Notes", rendered)
        self.assertIn("Sources", rendered)
        self.assertIn("$", rendered)

    def test_by_day_groups_correctly(self) -> None:
        insert_session(self.conn)
        insert_turn(self.conn, turn_index=0, timestamp="2026-04-10T08:00:00Z", input_tokens=100, output_tokens=10)
        insert_turn(self.conn, turn_index=1, timestamp="2026-04-10T20:00:00Z", input_tokens=200, output_tokens=20)

        report = self.build_report()

        self.assertEqual(len(report["by_day"]), 1)
        self.assertEqual(report["by_day"][0]["day"], "2026-04-10")
        self.assertEqual(report["by_day"][0]["turns"], 2)

    def test_multiple_models_in_by_model(self) -> None:
        insert_session(self.conn)
        insert_turn(self.conn, turn_index=0, model="claude-opus-4-6", input_tokens=100, output_tokens=10)
        insert_turn(self.conn, turn_index=1, model="claude-sonnet-4-6", input_tokens=100, output_tokens=10)

        report = self.build_report()

        models = {row["model"] for row in report["by_model"]}
        self.assertIn("claude-opus-4-6", models)
        self.assertIn("claude-sonnet-4-6", models)

    # ---------------------------------------------------------------
    # Time parsing tests
    # ---------------------------------------------------------------

    def test_parse_time_range_date_only(self) -> None:
        begin_at, end_at = report_api_costs.parse_time_range("2026-04-10", "2026-04-10", UTC)

        self.assertEqual(begin_at.isoformat(), "2026-04-10T00:00:00+00:00")
        self.assertEqual(end_at.isoformat(), "2026-04-10T23:59:59.999999+00:00")

    def test_requires_sqlite_cache(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "inspect_session.py refresh"):
            report_api_costs.build_report(
                claude_home=self.root / "nonexistent",
                begin_at=datetime(2026, 4, 10, tzinfo=UTC),
                end_at=datetime(2026, 4, 10, 23, 59, 59, tzinfo=UTC),
                display_timezone=UTC,
                exclude_subagents=False,
                unknown_model_policy="closest-family",
            )

    # ---------------------------------------------------------------
    # Snapshot suffix stripping
    # ---------------------------------------------------------------

    def test_strip_claude_snapshot_suffix(self) -> None:
        self.assertEqual(
            report_api_costs.strip_claude_snapshot_suffix("claude-haiku-4-5-20251001"),
            "claude-haiku-4-5",
        )

    def test_strip_snapshot_no_suffix(self) -> None:
        self.assertEqual(
            report_api_costs.strip_claude_snapshot_suffix("claude-opus-4-6"),
            "claude-opus-4-6",
        )

    def test_strip_snapshot_non_date_suffix(self) -> None:
        self.assertEqual(
            report_api_costs.strip_claude_snapshot_suffix("claude-opus-4-6-beta"),
            "claude-opus-4-6-beta",
        )

    # ---------------------------------------------------------------
    # Price catalog sanity
    # ---------------------------------------------------------------

    def test_all_catalog_entries_have_positive_rates(self) -> None:
        for model_id, price in report_api_costs.PRICE_CATALOG.items():
            with self.subTest(model=model_id):
                self.assertGreater(price.input_per_million, 0)
                self.assertGreater(price.cache_read_per_million, 0)
                self.assertGreater(price.cache_write_5m_per_million, 0)
                self.assertGreater(price.cache_write_1h_per_million, 0)
                self.assertGreater(price.output_per_million, 0)

    def test_fable_5_and_mythos_5_priced_at_flagship_rate(self) -> None:
        for model_id in ("claude-fable-5", "claude-mythos-5"):
            with self.subTest(model=model_id):
                price = report_api_costs.PRICE_CATALOG[model_id]
                self.assertEqual(price.input_per_million, Decimal("10.00"))
                self.assertEqual(price.output_per_million, Decimal("50.00"))
                self.assertEqual(price.cache_read_per_million, Decimal("1.000000"))
                self.assertEqual(price.cache_write_5m_per_million, Decimal("12.500000"))
                self.assertEqual(price.cache_write_1h_per_million, Decimal("20.000000"))
                # Fable/Mythos have no fast-mode rate (Opus-only feature).
                self.assertNotIn(model_id, report_api_costs.FAST_PRICE_CATALOG)

    def test_cache_read_is_tenth_of_input(self) -> None:
        for model_id, price in report_api_costs.PRICE_CATALOG.items():
            with self.subTest(model=model_id):
                expected = (price.input_per_million * Decimal("0.1")).quantize(
                    report_api_costs.USD_PRECISION
                )
                self.assertEqual(price.cache_read_per_million, expected)

    def test_cache_write_5m_is_125x_and_1h_is_2x_input(self) -> None:
        for model_id, price in report_api_costs.PRICE_CATALOG.items():
            with self.subTest(model=model_id):
                expected_5m = (price.input_per_million * Decimal("1.25")).quantize(
                    report_api_costs.USD_PRECISION
                )
                expected_1h = (price.input_per_million * Decimal("2")).quantize(
                    report_api_costs.USD_PRECISION
                )
                self.assertEqual(price.cache_write_5m_per_million, expected_5m)
                self.assertEqual(price.cache_write_1h_per_million, expected_1h)

    def test_fast_catalog_derives_both_cache_write_rates(self) -> None:
        for model_id, price in report_api_costs.FAST_PRICE_CATALOG.items():
            with self.subTest(model=model_id):
                self.assertEqual(
                    price.cache_write_5m_per_million,
                    (price.input_per_million * Decimal("1.25")).quantize(
                        report_api_costs.USD_PRECISION
                    ),
                )
                self.assertEqual(
                    price.cache_write_1h_per_million,
                    (price.input_per_million * Decimal("2")).quantize(
                        report_api_costs.USD_PRECISION
                    ),
                )


if __name__ == "__main__":
    unittest.main()
