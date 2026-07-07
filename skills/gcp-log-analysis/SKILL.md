---
name: gcp-log-analysis
description: >
  Analyze Cloud Run service and job logs in GCP. Use when investigating errors,
  debugging production issues, checking Cloud Run logs, analyzing alert noise,
  reviewing HTTP 500s/4xxs, or conducting health checks. Provides scripts for
  error aggregation, timeline analysis, HTTP error breakdown, and alert policy
  listing. KidStrong projects: ksu-live (production), kidstrong-at-home (development).
---

# GCP Log Analysis

Analyze Cloud Run logs and metrics to investigate reliability issues, identify noise, and audit alert policies.

## Projects

| Environment | Project ID |
|-------------|------------|
| Production | `ksu-live` |
| Development | `kidstrong-at-home` |

## Prerequisites

- **uv**: Python package manager ([install](https://docs.astral.sh/uv/))
- **gcloud CLI**: Authenticated with access to target projects
  ```bash
  gcloud auth login
  gcloud config set project ksu-live
  ```
- **Python 3.13+**: Required by script inline metadata (PEP 723)

## Execution Policy (Time Efficiency)

### Step 0 - Select Analysis Mode (required)

Choose mode before running commands:

- **FAST_VERIFY**: Validate specific numbers/hypotheses quickly.
- **DEEP_INVESTIGATION**: Full root-cause and broad blast-radius analysis.

Default to **FAST_VERIFY** unless the user explicitly asks for deep investigation.

### FAST_VERIFY Constraints

- Time budget target: **5 minutes**.
- Answer the user's stated question first; do not expand scope by default.
- Prefer count-style queries (`--format='value(timestamp)'` + `wc -l`) over large JSON pulls.
- Use Cloud Monitoring metrics first for aggregate answers (counts/rates/trends/percentiles), then Cloud Logging for targeted cross-checks.
- Use JSON log payload reads only when required (for example, 2-3 trace samples).

### DEEP_INVESTIGATION Constraints

- Time budget target for initial results: **12 minutes**.
- Provide early findings first, then continue deeper only if needed.
- Do not run full-fleet, full-window JSON pulls unless required by explicit goal.

### Evidence Source Priority (required)

Use sources in this order unless the user explicitly requests otherwise:

1. **Monitoring metrics first for aggregates**: use Cloud Monitoring API when the question is about counts, rates, trends, percentiles, utilization, queue depth, or time-window comparisons (for example request volume, 4xx/5xx rates, CPU/memory, concurrency, latency distributions).
2. **Logging counts second for validation**: use log count-style queries (`--format='value(timestamp)'`) to cross-check key numerators/denominators or where metric labels are missing.
3. **Logging payload/trace third for causality**: use targeted JSON log reads and trace correlation for request-level evidence, error messages, missing app logs, and root-cause context.

Before running broad queries, check metric availability with descriptor queries (`metricDescriptors`) so you do not default to logs when usable metrics already exist.

### Guardrails

- No unfiltered fleet-wide `gcloud logging read --format=json`.
- Default `--limit` should be <= `50000`; exceed only when explicitly justified.
- Maximum 2 long-running log queries in parallel.
- If a query runs longer than ~90 seconds and is not critical, cancel and narrow scope.
- When the user's ask is answered with reproducible evidence, stop and return results.

## Scripts

All scripts and references are **self-contained in this skill directory**. Run from the skill root or use absolute paths:

```bash
# From skill directory
cd <skill-dir>
uv run scripts/error_summary.py --project ksu-live

# Or with absolute path
uv run <skill-dir>/scripts/error_summary.py --project ksu-live
```

Where `<skill-dir>` is the skill's installation path (e.g., `~/.claude/skills/gcp-log-analysis` for personal skills).

Scripts use PEP 723 inline metadata (Python 3.13+, zero external dependencies).

Scripts share common utilities via `_gcloud.py` (internal module, not run directly):
- `run_gcloud_logging()` - Execute log queries with JSON output
- `run_gcloud_command()` - Execute arbitrary gcloud commands
- `get_nested()` - Safe nested dict access for JSON parsing
- `GcloudError` - Shared exception handling

### Quick Health Check
```bash
# Error summary across all services/jobs (last 7 days)
uv run scripts/error_summary.py --project ksu-live --days 7

# Just services or just jobs
uv run scripts/error_summary.py --type service
uv run scripts/error_summary.py --type job

# Reusable UTC window for metric snapshots
START_UTC="2026-03-01T00:00:00Z"
END_UTC="2026-03-02T00:00:00Z"

# Aggregate request volume by response class (Monitoring API; fast metric snapshot)
ACCESS_TOKEN="$(gcloud auth print-access-token)"
curl -sS -G -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  "https://monitoring.googleapis.com/v3/projects/ksu-live/timeSeries" \
  --data-urlencode 'filter=metric.type="run.googleapis.com/request_count" AND resource.type="cloud_run_revision"' \
  --data-urlencode "interval.startTime=${START_UTC}" \
  --data-urlencode "interval.endTime=${END_UTC}" \
  --data-urlencode 'aggregation.alignmentPeriod=3600s' \
  --data-urlencode 'aggregation.perSeriesAligner=ALIGN_SUM' \
  --data-urlencode 'aggregation.crossSeriesReducer=REDUCE_SUM' \
  --data-urlencode 'aggregation.groupByFields=resource.label.service_name' \
  --data-urlencode 'aggregation.groupByFields=metric.label.response_code_class' \
  --data-urlencode 'view=FULL'

# Aggregate CPU pressure snapshot (Monitoring API; non-error operational signal)
curl -sS -G -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  "https://monitoring.googleapis.com/v3/projects/ksu-live/timeSeries" \
  --data-urlencode 'filter=metric.type="run.googleapis.com/container/cpu/utilizations" AND resource.type="cloud_run_revision"' \
  --data-urlencode "interval.startTime=${START_UTC}" \
  --data-urlencode "interval.endTime=${END_UTC}" \
  --data-urlencode 'aggregation.alignmentPeriod=3600s' \
  --data-urlencode 'aggregation.perSeriesAligner=ALIGN_PERCENTILE_99' \
  --data-urlencode 'aggregation.crossSeriesReducer=REDUCE_MAX' \
  --data-urlencode 'aggregation.groupByFields=resource.label.service_name' \
  --data-urlencode 'view=FULL'
```

Note: When querying both services and jobs (`--type=all`), queries run in parallel for faster results.

### Timeline Analysis
```bash
# Error timeline by day (shows top resources per day)
uv run scripts/timeline.py --project ksu-live --days 14

# Timeline for specific service
uv run scripts/timeline.py --service kidstrong-task-handler --days 7

# Timeline for specific job
uv run scripts/timeline.py --job kidstrong-firestore-integrity-checker-job
```

### Top Error Patterns
```bash
# Top errors for a service
uv run scripts/top_errors.py --service kidstrong-task-handler --days 7

# Top errors for a job
uv run scripts/top_errors.py --job kidstrong-streak-destroyer-job
```

### HTTP Error Breakdown
```bash
# All HTTP 4xx/5xx errors
uv run scripts/http_errors.py --project ksu-live --days 7

# Specific status code
uv run scripts/http_errors.py --status 500
uv run scripts/http_errors.py --status 429  # Rate limits
```

### Alert Policies
```bash
# List all alert policies
uv run scripts/alert_policies.py --project ksu-live

# Filter by name
uv run scripts/alert_policies.py --filter "HTTP"
uv run scripts/alert_policies.py --filter "Latency"
```

## Investigation Workflow

Copy this checklist to track progress:

```
Investigation Progress:
- [ ] Step 0: Select mode (FAST_VERIFY vs DEEP_INVESTIGATION)
- [ ] Step 1: Pull aggregate metrics first (counts/rates/latency/utilization) via Monitoring
- [ ] Step 2: Use log count queries to validate key numbers and fill metric-label gaps
- [ ] Step 3: Run error_summary.py / timeline.py for broad log-driven discovery
- [ ] Step 4: Run top_errors.py and trace-targeted JSON queries for causality
- [ ] Step 5: Classify noisy vs important and correlate with alert policies
```

**Step 0 - Select mode**: Choose `FAST_VERIFY` (default) or `DEEP_INVESTIGATION`

**Step 1 - Metrics first**: Use Monitoring API for aggregate answers before log-heavy queries

**Step 2 - Validate with counts**: Use log count queries for fast reconciliation

**Step 3 - Start broad logs**: Run `error_summary.py` / `timeline.py` for discovery

**Step 4 - Drill down**: Run `top_errors.py` and targeted trace/log payload queries for root-cause context

**Step 5 - Classify and correlate**: Determine noisy vs important and compare with alert policies

## Output Expectations

For each key number in findings, include:

- **Source**: Monitoring metric or Logging query
- **UTC window**: explicit start/end timestamps
- **Snapshot time**: when data was fetched
- **Scope**: service/fleet and any filters (status class, revision, route, etc.)

If counts differ between Monitoring and Logging, report both and explain likely causes (ingestion lag, label coverage, filter mismatch, or query limits).

## Script Architecture

```
scripts/
├── _gcloud.py          # Shared utilities (GcloudError, JSON parsing, logging)
├── error_summary.py    # Aggregate errors by service/job (parallel queries)
├── timeline.py         # Error counts by day
├── top_errors.py       # Top error patterns for a resource
├── http_errors.py      # HTTP 4xx/5xx breakdown
└── alert_policies.py   # List monitoring alert policies
```

All scripts use `--format=json` for robust parsing of gcloud output. The shared `get_nested()` helper safely traverses nested JSON structures like `resource.labels.service_name`.

## Resources

### Scripts (Execute with `uv run`)

| Script | Purpose |
|--------|---------|
| `scripts/error_summary.py` | Aggregate errors by service/job |
| `scripts/timeline.py` | Error counts by day |
| `scripts/top_errors.py` | Top error patterns for a resource |
| `scripts/http_errors.py` | HTTP 4xx/5xx breakdown |
| `scripts/alert_policies.py` | List monitoring alert policies |

### Reference Docs (Read for context)

- [query-patterns.md](references/query-patterns.md) - Raw gcloud query syntax and examples
- [projects.md](references/projects.md) - Service/job inventory and known error patterns
