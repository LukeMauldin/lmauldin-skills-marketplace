from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
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

IMPORTER_PATH = ROOT / "scripts" / "importer.py"
IMPORTER_SPEC = importlib.util.spec_from_file_location("report_api_costs_importer", IMPORTER_PATH)
if IMPORTER_SPEC is None or IMPORTER_SPEC.loader is None:
    raise RuntimeError(f"failed to load module from {IMPORTER_PATH}")
importer = importlib.util.module_from_spec(IMPORTER_SPEC)
sys.modules[IMPORTER_SPEC.name] = importer
IMPORTER_SPEC.loader.exec_module(importer)


THREAD_ID = "019d2494-6c37-7c93-9df6-7ed84372b136"


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def make_token_count(
    timestamp: str,
    *,
    total_input: int,
    total_cached: int,
    total_cache_write: int | None = None,
    total_output: int,
    total_reasoning: int,
    last_input: int | None = None,
    last_cached: int | None = None,
    last_cache_write: int | None = None,
    last_output: int | None = None,
    last_reasoning: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "token_count",
        "info": {
            "total_token_usage": {
                "input_tokens": total_input,
                "cached_input_tokens": total_cached,
                "output_tokens": total_output,
                "reasoning_output_tokens": total_reasoning,
                "total_tokens": total_input + total_output,
            }
        },
    }
    if last_input is not None:
        payload["info"]["last_token_usage"] = {
            "input_tokens": last_input,
            "cached_input_tokens": last_cached or 0,
            "output_tokens": last_output or 0,
            "reasoning_output_tokens": last_reasoning or 0,
            "total_tokens": last_input + (last_output or 0),
        }
    if total_cache_write is not None:
        payload["info"]["total_token_usage"]["cache_write_tokens"] = total_cache_write
    if last_input is not None and last_cache_write is not None:
        payload["info"]["last_token_usage"]["cache_write_tokens"] = last_cache_write
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": payload,
    }


class ReportApiCostsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.codex_home = self.root / ".codex"
        self.sessions_dir = self.codex_home / "sessions" / "2026" / "04" / "10"
        self.archived_dir = self.codex_home / "archived_sessions"
        self.sessions_dir.mkdir(parents=True)
        self.archived_dir.mkdir(parents=True)
        (self.codex_home / "session_index.jsonl").write_text(
            json.dumps({"id": THREAD_ID, "thread_name": "Primary session"}) + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_gpt_56_family_standard_price_catalog(self) -> None:
        expected = {
            "gpt-5.6-sol": ("5.00", "0.50", "6.25", "30.00"),
            "gpt-5.6-terra": ("2.50", "0.25", "3.125", "15.00"),
            "gpt-5.6-luna": ("1.00", "0.10", "1.25", "6.00"),
        }

        for model, rates in expected.items():
            price = report_api_costs.PRICE_CATALOG[model]
            self.assertEqual(
                tuple(
                    str(value)
                    for value in (
                        price.input_per_million,
                        price.cached_input_per_million,
                        price.cache_write_per_million,
                        price.output_per_million,
                    )
                ),
                rates,
            )

    def build_report(self, **overrides: Any) -> dict[str, Any]:
        return report_api_costs.build_report(
            codex_home=self.codex_home,
            begin_at=datetime(2026, 4, 10, 0, 0, tzinfo=UTC),
            end_at=datetime(2026, 4, 10, 23, 59, 59, tzinfo=UTC),
            display_timezone=UTC,
            archived_only=bool(overrides.pop("archived_only", False)),
            active_only=bool(overrides.pop("active_only", False)),
            unknown_model_policy=str(overrides.pop("unknown_model_policy", "closest-public")),
            **overrides,
        )

    def refresh_db(self, *, archived: bool | None = False) -> None:
        importer.refresh_rollouts(
            self.codex_home,
            archived=archived,
            reconcile=False,
            analyze=False,
        )

    def import_rollout(
        self,
        rows: list[dict[str, Any]],
        *,
        archived: bool = False,
        filename_timestamp: str = "2026-04-10T12-00-00",
    ) -> Path:
        base_dir = self.archived_dir if archived else self.sessions_dir
        rollout_path = base_dir / f"rollout-{filename_timestamp}-{THREAD_ID}.jsonl"
        write_jsonl(rollout_path, rows)
        self.refresh_db(archived=archived)
        return rollout_path

    def test_reasoning_tokens_reported_but_not_double_counted(self) -> None:
        self.import_rollout(
            [
                {
                    "timestamp": "2026-04-10T12:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": THREAD_ID, "cwd": "/tmp/demo", "model_provider": "openai", "source": {}},
                },
                {
                    "timestamp": "2026-04-10T12:00:01Z",
                    "type": "turn_context",
                    "payload": {"model": "gpt-5-codex", "cwd": "/tmp/demo"},
                },
                make_token_count(
                    "2026-04-10T12:00:02Z",
                    total_input=1000,
                    total_cached=200,
                    total_output=100,
                    total_reasoning=30,
                    last_input=1000,
                    last_cached=200,
                    last_output=100,
                    last_reasoning=30,
                ),
            ]
        )

        report = self.build_report()

        self.assertEqual(report["totals"]["reasoning_output_tokens"], 30)
        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 0.002025, places=6)
        self.assertIn("not double-counted", report["pricing"]["reasoning_note"])
        self.assertEqual(report["scan"]["source"], "sqlite")

    def test_uses_total_token_delta_when_last_usage_missing(self) -> None:
        self.import_rollout(
            [
                {
                    "timestamp": "2026-04-10T12:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": THREAD_ID, "cwd": "/tmp/demo", "model_provider": "openai", "source": {}},
                },
                {
                    "timestamp": "2026-04-10T12:00:01Z",
                    "type": "turn_context",
                    "payload": {"model": "gpt-5.1", "cwd": "/tmp/demo"},
                },
                make_token_count(
                    "2026-04-09T23:59:59Z",
                    total_input=100,
                    total_cached=20,
                    total_output=10,
                    total_reasoning=2,
                ),
                make_token_count(
                    "2026-04-10T12:00:02Z",
                    total_input=150,
                    total_cached=30,
                    total_output=20,
                    total_reasoning=4,
                ),
            ]
        )

        report = self.build_report()

        self.assertEqual(report["totals"]["input_tokens"], 50)
        self.assertEqual(report["totals"]["cached_input_tokens"], 10)
        self.assertEqual(report["totals"]["output_tokens"], 10)
        self.assertEqual(report["scan"]["approximate_usage_events"], 1)

    def test_applies_gpt_54_long_context_multiplier(self) -> None:
        self.import_rollout(
            [
                {
                    "timestamp": "2026-04-10T12:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": THREAD_ID, "cwd": "/tmp/demo", "model_provider": "openai", "source": {}},
                },
                {
                    "timestamp": "2026-04-10T12:00:01Z",
                    "type": "turn_context",
                    "payload": {"model": "gpt-5.4", "cwd": "/tmp/demo"},
                },
                make_token_count(
                    "2026-04-10T12:00:02Z",
                    total_input=300000,
                    total_cached=100000,
                    total_output=1000,
                    total_reasoning=100,
                    last_input=300000,
                    last_cached=100000,
                    last_output=1000,
                    last_reasoning=100,
                ),
            ]
        )

        report = self.build_report()

        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 1.0725, places=6)
        self.assertEqual(report["scan"]["long_context_pricing_events"], 1)

    def test_applies_gpt_55_long_context_multiplier(self) -> None:
        self.import_rollout(
            [
                {
                    "timestamp": "2026-04-10T12:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": THREAD_ID, "cwd": "/tmp/demo", "model_provider": "openai", "source": {}},
                },
                {
                    "timestamp": "2026-04-10T12:00:01Z",
                    "type": "turn_context",
                    "payload": {"model": "gpt-5.5", "cwd": "/tmp/demo"},
                },
                make_token_count(
                    "2026-04-10T12:00:02Z",
                    total_input=300000,
                    total_cached=100000,
                    total_output=1000,
                    total_reasoning=100,
                    last_input=300000,
                    last_cached=100000,
                    last_output=1000,
                    last_reasoning=100,
                ),
            ]
        )

        report = self.build_report()

        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 2.145, places=6)
        self.assertEqual(report["by_model"][0]["model"], "gpt-5.5")
        self.assertEqual(report["scan"]["long_context_pricing_events"], 1)

    def test_prices_gpt_56_sol_cache_writes_exactly(self) -> None:
        self.import_rollout(
            [
                {
                    "timestamp": "2026-04-10T12:00:00Z",
                    "type": "session_meta",
                    "payload": {
                        "id": THREAD_ID,
                        "cwd": "/tmp/demo",
                        "model_provider": "openai",
                        "source": "cli",
                        "cli_version": "0.144.1",
                    },
                },
                {
                    "timestamp": "2026-04-10T12:00:01Z",
                    "type": "turn_context",
                    "payload": {"model": "gpt-5.6-sol", "cwd": "/tmp/demo"},
                },
                make_token_count(
                    "2026-04-10T12:00:02Z",
                    total_input=1000,
                    total_cached=200,
                    total_cache_write=300,
                    total_output=100,
                    total_reasoning=30,
                    last_input=1000,
                    last_cached=200,
                    last_cache_write=300,
                    last_output=100,
                    last_reasoning=30,
                ),
            ]
        )

        report = self.build_report()

        self.assertAlmostEqual(report["totals"]["estimated_cost_usd"], 0.007475, places=6)
        self.assertEqual(report["totals"]["cache_write_tokens"], 300)
        self.assertEqual(report["scan"]["missing_cache_write_usage_events"], 0)
        self.assertEqual(report["by_model"][0]["model"], "gpt-5.6-sol")

    def test_bounds_gpt_56_cost_when_codex_01441_omits_cache_writes(self) -> None:
        self.import_rollout(
            [
                {
                    "timestamp": "2026-04-10T12:00:00Z",
                    "type": "session_meta",
                    "payload": {
                        "id": THREAD_ID,
                        "cwd": "/tmp/demo",
                        "model_provider": "openai",
                        "source": "cli",
                        "cli_version": "0.144.1",
                    },
                },
                {
                    "timestamp": "2026-04-10T12:00:01Z",
                    "type": "turn_context",
                    "payload": {"model": "gpt-5.6", "cwd": "/tmp/demo"},
                },
                make_token_count(
                    "2026-04-10T12:00:02Z",
                    total_input=1000,
                    total_cached=200,
                    total_output=100,
                    total_reasoning=30,
                    last_input=1000,
                    last_cached=200,
                    last_output=100,
                    last_reasoning=30,
                ),
            ]
        )

        report = self.build_report()

        self.assertIsNone(report["totals"]["estimated_cost_usd"])
        self.assertAlmostEqual(report["totals"]["estimated_cost_lower_usd"], 0.0071, places=6)
        self.assertAlmostEqual(report["totals"]["estimated_cost_upper_usd"], 0.0081, places=6)
        self.assertEqual(report["scan"]["missing_cache_write_usage_events"], 1)
        self.assertEqual(report["by_model"][0]["model"], "gpt-5.6-sol")
        self.assertIn("Codex 0.144.1", report["warnings"][0])
        self.assertIn("$0.007100–$0.008100", report_api_costs.render_human_report(report))

    def test_maps_internal_openai_variant_to_public_model(self) -> None:
        self.import_rollout(
            [
                {
                    "timestamp": "2026-04-10T12:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": THREAD_ID, "cwd": "/tmp/demo", "model_provider": "openai", "source": {}},
                },
                {
                    "timestamp": "2026-04-10T12:00:01Z",
                    "type": "turn_context",
                    "payload": {"model": "gpt-5.3-codex-spark", "cwd": "/tmp/demo"},
                },
                make_token_count(
                    "2026-04-10T12:00:02Z",
                    total_input=100,
                    total_cached=0,
                    total_output=10,
                    total_reasoning=2,
                    last_input=100,
                    last_cached=0,
                    last_output=10,
                    last_reasoning=2,
                ),
            ]
        )

        report = self.build_report()

        self.assertEqual(report["by_model"][0]["model"], "gpt-5.3-codex")
        self.assertEqual(report["scan"]["estimated_model_mapping_events"], 1)
        self.assertEqual(report["estimated_mappings"][0]["mapping"], "gpt-5.3-codex-spark -> gpt-5.3-codex")

    def test_excludes_non_openai_provider_from_cost_totals(self) -> None:
        self.import_rollout(
            [
                {
                    "timestamp": "2026-04-10T12:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": THREAD_ID, "cwd": "/tmp/demo", "model_provider": "vmlx-gemma", "source": {}},
                },
                {
                    "timestamp": "2026-04-10T12:00:01Z",
                    "type": "turn_context",
                    "payload": {"model": "dealignai/Gemma-4-31B-JANG_4M-CRACK", "cwd": "/tmp/demo"},
                },
                make_token_count(
                    "2026-04-10T12:00:02Z",
                    total_input=100,
                    total_cached=0,
                    total_output=10,
                    total_reasoning=2,
                    last_input=100,
                    last_cached=0,
                    last_output=10,
                    last_reasoning=2,
                ),
            ]
        )

        report = self.build_report()

        self.assertEqual(report["totals"]["estimated_cost_usd"], 0.0)
        self.assertEqual(report["scan"]["unpriced_events"], 1)
        self.assertEqual(report["unpriced"][0]["key"], "dealignai/Gemma-4-31B-JANG_4M-CRACK")

    def test_prefers_active_rollout_when_thread_exists_in_active_and_archived(self) -> None:
        active_rows = [
            {
                "timestamp": "2026-04-10T12:00:00Z",
                "type": "session_meta",
                "payload": {"id": THREAD_ID, "cwd": "/tmp/demo", "model_provider": "openai", "source": {}},
            },
            {
                "timestamp": "2026-04-10T12:00:01Z",
                "type": "turn_context",
                "payload": {"model": "gpt-5", "cwd": "/tmp/demo"},
            },
            make_token_count(
                "2026-04-10T12:00:02Z",
                total_input=100,
                total_cached=0,
                total_output=10,
                total_reasoning=2,
                last_input=100,
                last_cached=0,
                last_output=10,
                last_reasoning=2,
            ),
        ]
        archived_rows = [
            {
                "timestamp": "2026-04-10T11:00:00Z",
                "type": "session_meta",
                "payload": {"id": THREAD_ID, "cwd": "/tmp/demo", "model_provider": "openai", "source": {}},
            },
            {
                "timestamp": "2026-04-10T11:00:01Z",
                "type": "turn_context",
                "payload": {"model": "gpt-5", "cwd": "/tmp/demo"},
            },
            make_token_count(
                "2026-04-10T11:00:02Z",
                total_input=500,
                total_cached=0,
                total_output=50,
                total_reasoning=5,
                last_input=500,
                last_cached=0,
                last_output=50,
                last_reasoning=5,
            ),
        ]
        self.import_rollout(active_rows, archived=False, filename_timestamp="2026-04-10T12-00-00")
        self.import_rollout(archived_rows, archived=True, filename_timestamp="2026-04-10T11-00-00")

        report = self.build_report()

        self.assertEqual(report["totals"]["input_tokens"], 100)
        self.assertEqual(report["scan"]["rollouts_scanned"], 1)

    def test_uses_sqlite_cache_when_available(self) -> None:
        rollout_path = self.import_rollout(
            [
                {
                    "timestamp": "2026-04-10T12:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": THREAD_ID, "cwd": "/tmp/demo", "model_provider": "openai", "source": {}},
                },
                {
                    "timestamp": "2026-04-10T12:00:01Z",
                    "type": "turn_context",
                    "payload": {"model": "gpt-5.1-codex-mini", "cwd": "/tmp/demo"},
                },
                make_token_count(
                    "2026-04-10T12:00:02Z",
                    total_input=100,
                    total_cached=25,
                    total_output=10,
                    total_reasoning=1,
                    last_input=100,
                    last_cached=25,
                    last_output=10,
                    last_reasoning=1,
                ),
            ]
        )
        rollout_path.unlink()

        report = self.build_report()

        self.assertEqual(report["scan"]["source"], "sqlite")
        self.assertEqual(report["scan"]["rollouts_scanned"], 1)
        self.assertEqual(report["totals"]["input_tokens"], 100)
        self.assertEqual(report["totals"]["cached_input_tokens"], 25)

    def test_human_report_contains_core_sections(self) -> None:
        self.import_rollout(
            [
                {
                    "timestamp": "2026-04-10T12:00:00Z",
                    "type": "session_meta",
                    "payload": {"id": THREAD_ID, "cwd": "/tmp/demo", "model_provider": "openai", "source": {}},
                },
                {
                    "timestamp": "2026-04-10T12:00:01Z",
                    "type": "turn_context",
                    "payload": {"model": "gpt-5.1-codex-mini", "cwd": "/tmp/demo"},
                },
                make_token_count(
                    "2026-04-10T12:00:02Z",
                    total_input=100,
                    total_cached=25,
                    total_output=10,
                    total_reasoning=1,
                    last_input=100,
                    last_cached=25,
                    last_output=10,
                    last_reasoning=1,
                ),
            ]
        )

        report = self.build_report()
        rendered = report_api_costs.render_human_report(report)

        self.assertIn("OpenAI API Cost Estimate", rendered)
        self.assertIn("By Day", rendered)
        self.assertIn("By Model", rendered)
        self.assertIn("Sources", rendered)
        self.assertIn("$0.00", rendered)

    def test_parse_time_range_supports_date_only_end_of_day(self) -> None:
        begin_at, end_at = report_api_costs.parse_time_range("2026-04-10", "2026-04-10", UTC)

        self.assertEqual(begin_at.isoformat(), "2026-04-10T00:00:00+00:00")
        self.assertEqual(end_at.isoformat(), "2026-04-10T23:59:59.999999+00:00")

    def test_requires_sqlite_cache(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "inspect_rollout.py refresh"):
            self.build_report()


if __name__ == "__main__":
    unittest.main()
