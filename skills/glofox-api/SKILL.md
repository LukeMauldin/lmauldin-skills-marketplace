---
name: glofox-api
description: "Use for read-only Glofox (GF) REST API verification, investigation, or integration work: classes/events, bookings, users, memberships, courses, staff, GF/Glofox service code, glofoxclient, or paths like /2.0/events. Covers auth, pagination, quirks, and schemas."
---

# Glofox API

## Quick Reference

| Item | Value |
|------|-------|
| Base URL (prod) | `https://gf-api.aws.glofox.com/prod` |
| Auth headers | `x-api-key`, `x-glofox-api-token`, `x-glofox-branch-id` |
| Credential source | GCP Secret Manager, project `ksu-live` |
| OpenAPI spec (local) | [references/openapi.yml](references/openapi.yml) (downloaded 2026-03-25, incomplete — see Quirks) |
| OpenAPI spec (remote) | `https://apidocs-plat.aws.glofox.com/openapi.yaml` |
| Rate limits (KS prod) | 9 req/s realtime, 9500 burst; separate batch credentials |
| Go client | `go_modules/services/kidstrong-glofox-service/glofoxclient/` |
| Timeout | 31s (GF internal timeout is 30s) |
| Center/Branch mapping | [references/center_branch_mapping.json](references/center_branch_mapping.json) (217 centers, 2026-03-25) |

## OpenAPI Spec

A local copy of the Glofox OpenAPI spec is bundled at [references/openapi.yml](references/openapi.yml) (downloaded 2026-03-25). **Use this local copy by default** when you need to look up endpoint paths, query parameters, request/response schemas, or status codes. The APIs KidStrong uses rarely change, so the local copy is almost always sufficient.

**When to download a fresh copy**: If you encounter a response field or endpoint that isn't in the local spec and suspect Glofox has updated their API, download a fresh copy:
```bash
curl -sS -o "$(dirname "$0")/references/openapi.yml" "https://apidocs-plat.aws.glofox.com/openapi.yaml"
```
Or from this skill's directory:
```bash
curl -sS -o references/openapi.yml "https://apidocs-plat.aws.glofox.com/openapi.yaml"
```

**Caveat**: The spec is incomplete (see Quirks #5). It has ~50 endpoints but undocumented response fields, incorrectly typed fields, and missing v3.0 coverage. The hand-curated [references/endpoints.md](references/endpoints.md) covers KidStrong-relevant endpoints with actual observed response shapes and is often more reliable for KS-specific work.

## Center ID to Branch ID Translation

The Glofox API uses `branch_id` (24-char hex MongoDB ObjectID) to identify centers, but KidStrong internally uses `center_id` (e.g., `ks_prosper_glofox`). Every Glofox API call requires the `branch_id` in the `x-glofox-branch-id` header.

### Quick Lookup

A cached mapping file is at [references/center_branch_mapping.json](references/center_branch_mapping.json). To look up a branch_id:

```bash
jq -r '.centers[] | select(.center_id == "ks_prosper_glofox") | .branch_id' references/center_branch_mapping.json
# Output: 669a5b7b375abd04fa05f64e
```

**This file may be stale** (~1-2 centers added per week). If a center_id is not found in the mapping, refresh it using the live service below.

### Live Lookup via Switchboard gRPC

The authoritative source is the `ExternalConfigService.GetCenters` gRPC endpoint on the KidStrong switchboard service. To query it:

```bash
# 1. Fetch switchboard credentials (GCP Secret Manager, project ksu-live)
SWITCHBOARD_URI=$(gcloud secrets versions access latest --secret=svc-switchboard-uri --project=ksu-live)
SWITCHBOARD_KEY=$(gcloud secrets versions access latest --secret=svc-switchboard-secret-key --project=ksu-live)

# 2. Proto file location (bedrock-protos repo must be cloned locally)
PROTO_PATH="$HOME/code/github.com/KidStrong/bedrock-protos/protos"

# 3. Get ALL centers with their branch_ids
grpcurl \
  -import-path "$PROTO_PATH" \
  -proto services/external_config.proto \
  -H "authorization: GCPSecret ${SWITCHBOARD_KEY}" \
  "${SWITCHBOARD_URI}" \
  bedrockprotos.ExternalConfigService/GetCenters \
  | jq '[.centers[] | {center_id: .centerId, branch_id: .vendorExtension.glofoxExtension.branchId, name: .name}] | sort_by(.center_id)'

# 4. Look up a single center_id
grpcurl \
  -import-path "$PROTO_PATH" \
  -proto services/external_config.proto \
  -H "authorization: GCPSecret ${SWITCHBOARD_KEY}" \
  "${SWITCHBOARD_URI}" \
  bedrockprotos.ExternalConfigService/GetCenters \
  | jq -r '.centers[] | select(.centerId == "ks_prosper_glofox") | .vendorExtension.glofoxExtension.branchId'
```

**Requirements**: `grpcurl` (`brew install grpcurl`), `gcloud` authenticated with `ksu-live` project access, bedrock-protos repo at `~/code/github.com/KidStrong/bedrock-protos/`.

**gRPC details**:
- Service: `bedrockprotos.ExternalConfigService`
- Method: `GetCenters` (no request body needed)
- Auth header: `authorization: GCPSecret {svc-switchboard-secret-key value}`
- Endpoint: `prod.switchboard.kidstrong.com:443` (from `svc-switchboard-uri` secret)
- Server reflection is disabled; must supply proto files via `-import-path`/`-proto`

### Refreshing the Mapping File

After a live lookup, update the cached file so future lookups are instant:

```bash
grpcurl \
  -import-path "$PROTO_PATH" \
  -proto services/external_config.proto \
  -H "authorization: GCPSecret ${SWITCHBOARD_KEY}" \
  "${SWITCHBOARD_URI}" \
  bedrockprotos.ExternalConfigService/GetCenters \
  | jq '{_generated: (now | strftime("%Y-%m-%d")), _source: "ExternalConfigService.GetCenters via switchboard gRPC", _note: "~1-2 centers added per week. Refresh via grpcurl command in SKILL.md if a center_id is not found.", centers: [.centers[] | {center_id: .centerId, branch_id: .vendorExtension.glofoxExtension.branchId, name: (.name | sub(" \\(GF\\)$"; ""))}] | {_generated, _source, _note, centers: (.centers | sort_by(.center_id))}' \
  > references/center_branch_mapping.json
```

## Authentication

Every request requires three headers. Fetch credentials once per session:

```bash
GF_API_KEY=$(gcloud secrets versions access latest --secret=glofox-api-key-realtime --project=ksu-live)
GF_API_TOKEN=$(gcloud secrets versions access latest --secret=glofox-api-token-realtime --project=ksu-live)
```

When the user provides a `center_id` (e.g., `ks_prosper_glofox`), resolve it to a `branch_id` using the mapping file or live gRPC lookup above before making any Glofox API calls.

```
x-api-key: {GF_API_KEY}
x-glofox-api-token: {GF_API_TOKEN}
x-glofox-branch-id: {branch_id}
```

- `x-glofox-branch-id` is a 24-char hex MongoDB ObjectID specific to each center/location
- Use `glofox-api-key-realtime` / `glofox-api-token-realtime` for interactive queries
- Use `glofox-api-key-batch` / `glofox-api-token-batch` for batch job traffic (separate rate pool)
- Branch-to-center mapping is sourced from the switchboard ExternalConfigService (backed by Hygraph), not Postgres

## Core Endpoints

### Events (Classes)

**List events** for a branch within a time window:
```bash
curl -s "${GF_BASE}/2.0/events?start=${START_UNIX}&end=${END_UNIX}&filter=event&active=any&limit=50&page=1" \
  -H "x-api-key: ${GF_API_KEY}" -H "x-glofox-api-token: ${GF_API_TOKEN}" \
  -H "x-glofox-branch-id: ${BRANCH_ID}"
```

- `start`/`end`: Unix timestamps (seconds). Required.
- `filter`: `event` (regular classes) or `timeslot` (appointments). Courses use a separate endpoint.
- `active`: `true`, `false`, or `any`
- `private`: omit for all, `true`/`false` to filter
- Paginated: check `has_more`, increment `page`
- Key response fields: `_id`, `name`, `size`, `booked`, `waiting`, `private` (boolean), `active`, `status`, `time_start` (unix), `modified` (unix), `branch_id`, `type`, `program_id`, `trainers[]`

**Get single event**:
```bash
curl -s "${GF_BASE}/2.0/events/${EVENT_ID}" \
  -H "x-api-key: ${GF_API_KEY}" -H "x-glofox-api-token: ${GF_API_TOKEN}" \
  -H "x-glofox-branch-id: ${BRANCH_ID}"
```
Response is the event object directly (not wrapped in `data[]`). The event payload includes `private` as a boolean field.

### Bookings

**List bookings** for a branch, optionally filtered by event:
```bash
curl -s "${GF_BASE}/2.2/branches/${BRANCH_ID}/bookings?event_id=${EVENT_ID}&event_type=events&limit=50&page=1" \
  -H "x-api-key: ${GF_API_KEY}" -H "x-glofox-api-token: ${GF_API_TOKEN}" \
  -H "x-glofox-branch-id: ${BRANCH_ID}"
```

- `event_id`: filter to a specific event (optional but recommended)
- `event_type`: `events`, `courses`, `time_slots`
- Date filters (all Unix timestamps): `start_date`, `end_date`, `modified_start_date`, `modified_end_date`, `time_start_start_date`, `time_start_end_date`
- Paginated via `meta.totalCount`, `meta.page`, `meta.limit`
- Key fields: `_id`, `status` (`BOOKED`/`WAITING`/`CANCELED`/`RESERVED`/`FAILED`), `user_id`, `event_id`, `time_start`, `modified`, `created`, `attended`, `guest_bookings`

**Get user bookings** (different endpoint, requires `user_id`):
```bash
curl -s "${GF_BASE}/2.0/bookings?branchId=${BRANCH_ID}&user_id=${USER_ID}&limit=50" \
  -H "x-api-key: ${GF_API_KEY}" -H "x-glofox-api-token: ${GF_API_TOKEN}" \
  -H "x-glofox-branch-id: ${BRANCH_ID}"
```

### Courses (v3)

```bash
curl -s "${GF_BASE}/3.0/locations/${BRANCH_ID}/courses" \
  -H "x-api-key: ${GF_API_KEY}" -H "x-glofox-api-token: ${GF_API_TOKEN}" \
  -H "x-glofox-branch-id: ${BRANCH_ID}"
```
Courses and events are separate entity types. A course has sessions; an event is a standalone class.

For full endpoint details (users, memberships, staff, etc.), see [references/endpoints.md](references/endpoints.md).

## Pagination

**Pattern A** (older: `/2.0/events`, `/2.0/bookings`):
```json
{"page": 1, "limit": 50, "has_more": true, "total_count": 120, "data": [...]}
```
Increment `page` while `has_more == true`.

**Pattern B** (newer: `/2.2/branches/{id}/bookings`):
```json
{"meta": {"totalCount": 20, "page": 1, "limit": 50}, "data": [...]}
```
Stop when `page * limit >= totalCount`.

## ID Validation

All entity IDs must be valid 24-char hex MongoDB ObjectIDs: `^[0-9a-fA-F]{24}$`. Invalid IDs return opaque errors.

## Known API Quirks

1. **`booked` counts only `BOOKED` status**: Does NOT include `RESERVED`, `FAILED`, or `CANCELED`. Query `/2.2/branches/{id}/bookings?event_id={id}` for the full status breakdown.
2. **Mixed timestamp formats**: `/2.0/events` returns `time_start`/`modified` as Unix int64. `/2.2/branches/{id}/bookings` returns them as ISO-ish strings (`"2026-03-23 01:13:35"`).
3. **`duration` can be float**: e.g., `45.0`. Round to nearest int for display.
4. **OpenAPI spec is incomplete**: The spec at `https://apidocs-plat.aws.glofox.com/openapi.yaml` has ~50 endpoints but undocumented response fields, incorrectly typed fields, and missing v3.0 coverage. **Always verify response shapes against actual API calls.**
5. **List omissions**: `GetEvents` may omit some zero-booked or inactive events that are retrievable by direct `GetEvent` ID lookup. Lists are not exhaustive.
6. **Event `status`**: Computed field — `AVAILABLE`, `FULLY_BOOKED`, `BOOKING_WINDOW_PASSED`. Not settable.

## Rate Limiting

KidStrong production: 9 req/s refill, 9500 burst buffer (realtime pool). The Go client blocks with `Wait(ctx)` — excess requests queue, converting throughput overload into latency. For CLI/investigation work, keep under 5 req/s.

## KidStrong Go Client

Location: `go_modules/services/kidstrong-glofox-service/glofoxclient/`

| File | Endpoints |
|------|-----------|
| `glofoxclient.go` | Client struct, auth headers, rate limiting |
| `glofox_events.go` | `GetEvents`, `GetEvent` |
| `glofox_bookings.go` | `GetBranchBookings`, `GetUserBookings`, `CreateBooking`, `MarkBookingsAttended` |
| `glofox_courses.go` | `GetCourses` (v3) |
| `glofox_users.go` | User endpoints |
| `glofox_memberships.go` | `GetMemberships`, purchase |
| `glofox_staff.go` | Staff endpoints |
| `glofox_branch.go` | Branch details |

Booking status mapping (GF → KS domain, via `glofox_attendance_adapter.rs:determine_attendance_status()`): `BOOKED`→`reserved`, `WAITING`→`reserved`, `CANCELED`→`cancelled`, `RESERVED`→`reserved`, `FAILED`→`cancelled`. This mapping is the same for both the webhook path and the batch sync path. Note: GF does not reliably emit `BOOKING_UPDATED` webhooks for BOOKED→FAILED transitions (confirmed 2026-03-26 via log analysis of Prosper bookings), so FAILED bookings may sit stale until the next batch resync picks them up.
