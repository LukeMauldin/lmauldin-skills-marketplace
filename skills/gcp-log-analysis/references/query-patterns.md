# GCP Log Query Patterns

Quick reference for common gcloud logging queries.

## Contents

- [Resource Types](#resource-types)
- [Severity Levels](#severity-levels)
- [Common Filters](#common-filters)
- [Output Formats](#output-formats)
- [Example Queries](#example-queries)
- [API Quotas](#api-quotas)

## Resource Types

| Resource | Type Filter | Label |
|----------|-------------|-------|
| Cloud Run Service | `resource.type="cloud_run_revision"` | `resource.labels.service_name` |
| Cloud Run Job | `resource.type="cloud_run_job"` | `resource.labels.job_name` |

## Severity Levels

```
DEFAULT < DEBUG < INFO < NOTICE < WARNING < ERROR < CRITICAL < ALERT < EMERGENCY
```

Use `severity>=ERROR` to catch ERROR and above.

## Common Filters

### By Severity
```bash
# All errors
severity>=ERROR

# Warnings and above
severity>=WARNING
```

### By HTTP Status
```bash
# All client/server errors
httpRequest.status>=400

# Server errors only
httpRequest.status>=500

# Specific status
httpRequest.status=429
```

### By Timestamp
```bash
# Absolute time
timestamp>="2025-01-01T00:00:00Z"

# Relative (not directly supported, compute in script)
```

### By Text Content
```bash
# In text payload
textPayload:"error message"

# In JSON payload
jsonPayload.message:"error message"
jsonPayload.error:"specific error"

# Combine with OR
(textPayload:"keyword" OR jsonPayload.message:"keyword")
```

## Output Formats

### JSON (Recommended for Scripts)
```bash
--format=json
# Returns full log entry structure, parse with json.loads() in Python
# or pipe to jq for shell processing
```

JSON output provides:
- Full nested structure (`resource.labels.service_name`)
- Proper types (integers for status codes, timestamps as strings)
- No parsing ambiguity from tab-delimited fields

### Value Format (Quick Shell Use)
```bash
# Single field
--format='value(resource.labels.service_name)'

# Multiple fields (tab-separated)
--format='value(field1,field2,field3)'

# With date formatting
--format='value(timestamp.date("%Y-%m-%d"),resource.labels.service_name)'
```

### Table Format (Human Readable)
```bash
--format='table(displayName,enabled,conditions.displayName)'
```

## Example Queries

### Service Errors Summary (Shell)
```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND severity>=ERROR AND timestamp>="2025-01-01T00:00:00Z"' \
  --project=ksu-live \
  --format='value(resource.labels.service_name)' \
  --limit=10000 \
  | sort | uniq -c | sort -rn
```

### Service Errors Summary (JSON for Python)
```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND severity>=ERROR AND timestamp>="2025-01-01T00:00:00Z"' \
  --project=ksu-live \
  --format=json \
  --limit=10000
```

Then in Python:
```python
import json
entries = json.loads(result.stdout)
for entry in entries:
    service = entry.get("resource", {}).get("labels", {}).get("service_name")
```

### Job Errors Summary
```bash
gcloud logging read \
  'resource.type="cloud_run_job" AND severity>=ERROR AND timestamp>="2025-01-01T00:00:00Z"' \
  --project=ksu-live \
  --format=json \
  --limit=10000
```

### HTTP 500s by Service
```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND httpRequest.status=500' \
  --project=ksu-live \
  --format=json \
  --limit=1000 \
  | jq -r '.[] | "\(.resource.labels.service_name)\t\(.httpRequest.requestUrl)"' \
  | sort | uniq -c | sort -rn
```

### Error Messages for Specific Service
```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="my-service" AND severity>=ERROR' \
  --project=ksu-live \
  --format=json \
  --limit=500 \
  | jq -r '.[] | .textPayload // .jsonPayload.message // .jsonPayload.error // "<no message>"'
```

### Timeline Analysis
```bash
gcloud logging read \
  'severity>=ERROR AND timestamp>="2025-01-01T00:00:00Z"' \
  --project=ksu-live \
  --format=json \
  --limit=10000 \
  | jq -r '.[] | "\(.timestamp[:10])\t\(.resource.labels.service_name // .resource.labels.job_name)"' \
  | sort | uniq -c
```

## API Quotas

The Cloud Logging API has rate limits:
- **60 `entries.list` requests per minute** per project (non-increasable)
- Max 100 projects per request

For high-volume analysis, consider:
- Exporting logs to BigQuery via log sinks
- Using Log Analytics with SQL queries
- Copying logs to Cloud Storage for batch processing
