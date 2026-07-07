# KidStrong GCP Projects

## Project Reference

| Environment | Project ID | Description |
|-------------|------------|-------------|
| Production | `ksu-live` | Live production environment |
| Development | `kidstrong-at-home` | Development/staging environment |

## Cloud Run Services (Production)

Key services in `ksu-live`:

| Service | Description |
|---------|-------------|
| `kidstrong-task-handler` | Background task processing |
| `kidstrong-switchboard` | Request routing/orchestration |
| `kidstrong-glofox-service` | Glofox API integration |
| `kidstrong-coach-gateway` | Coach app GraphQL gateway |
| `kidstrong-kstv-gateway` | KSTV app gateway |
| `kidstrong-tools-gateway` | Internal tools gateway |
| `kidstrong-nexus` | Class management service |
| `center-sync-service` | Center data synchronization |
| `webhooks-gateway` | External webhook handling |
| `lighthouse-backend` | Lighthouse app backend |
| `pubsub-publish-service` | Pub/Sub publishing |
| `pubsub-subscribe-handler` | Pub/Sub message handling |
| `legacy-gateway` | Legacy API compatibility |
| `slack-helpdesk-bot` | Slack helpdesk integration |
| `junction` | API junction service |

## Cloud Run Jobs (Production)

Key jobs in `ksu-live`:

| Job | Schedule | Description |
|-----|----------|-------------|
| `kidstrong-firestore-integrity-checker-job` | Daily | Data integrity validation |
| `kidstrong-streak-destroyer-job` | Daily | Streak calculation cleanup |
| `kidstrong-close-old-classes-v2-job` | Scheduled | Close stale class sessions |
| `kidstrong-task-lock-cleanup-job` | Scheduled | Clean up stale task locks |
| `kidstrong-slack-helpdesk-bot-process-docs` | Scheduled | Process helpdesk docs |
| `sync-externaldata-*` | Various | External data sync jobs |
| `cleanup-pubsub-*` | Scheduled | Pub/Sub maintenance |
| `tech-redshift-etl` | Scheduled | Redshift ETL pipeline |

## Common Error Patterns

### Known Noisy Errors (Consider Filtering)

| Service/Job | Error Pattern | Cause |
|-------------|---------------|-------|
| `kidstrong-task-handler` | "Request de-duplicated" | Expected dedup behavior |
| `kidstrong-switchboard` | "Daxko vendor data is no longer supported" | Legacy data |
| `kidstrong-streak-destroyer-job` | "Kid didn't actually break streak" | Query design |
| `lighthouse-backend` | HTTP 401 on `/`, `/robots.txt` | Scanner traffic |
| `kidstrong-nexus` | HTTP 415 on `wp-includes` paths | WordPress scanners |

### Important Errors (Investigate)

| Service/Job | Error Pattern | Action |
|-------------|---------------|--------|
| `center-sync-service` | "Failed to ensure kid exists" | Kid sync ordering issue |
| `kidstrong-glofox-service` | "http transport error" | Glofox API timeouts |
| `kidstrong-slack-helpdesk-bot-process-docs` | "context length exceeded" | Document chunking needed |
| `onksqrqrcodewritten` | "Memory limit exceeded" | Increase function memory |
