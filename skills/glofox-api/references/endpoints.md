# Glofox API Endpoint Reference

Detailed request/response shapes for endpoints used by KidStrong. All paths are relative to `https://gf-api.aws.glofox.com/prod`.

## Table of Contents

- [Events](#events)
- [Bookings](#bookings)
- [Courses](#courses)
- [Users](#users)
- [Memberships](#memberships)
- [Staff](#staff)
- [Branch](#branch)
- [Attendances](#attendances)

---

## Events

### GET /2.0/events

List events (classes) for a branch.

**Query params**:

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `start` | int64 | yes | Unix timestamp, window start |
| `end` | int64 | yes | Unix timestamp, window end |
| `filter` | string | no | `event`, `timeslot` (comma-separated) |
| `active` | string | no | `true`, `false`, `any` |
| `private` | bool | no | Filter by private status |
| `limit` | int32 | no | Page size (default 50) |
| `page` | int32 | no | Page number (1-indexed) |
| `sort_by` | string | no | Sort field |
| `programs` | string | no | Filter by program IDs |
| `facilities` | string | no | Filter by facility |
| `trainers` | string | no | Filter by trainer IDs |
| `model` | string | no | Filter by model type |
| `model_id` | string | no | Filter by model ID |
| `modified_start_date` | ISO 8601 | no | Modified after |
| `modified_end_date` | ISO 8601 | no | Modified before |

**Response** (`GetEventsResponse`):
```json
{
  "success": true,
  "object": "list",
  "page": 1,
  "limit": 50,
  "has_more": false,
  "total_count": 12,
  "data": [Event]
}
```

**Event object**:
```json
{
  "_id": "68ae7d78019eb6ca120f1c20",
  "namespace": "kidstronglive",
  "branch_id": "669a5b7b375abd04fa05f64e",
  "type": "event",
  "active": true,
  "name": "3 - 4 Years",
  "description": "",
  "time_start": 1774452600,
  "duration": 45,
  "is_online": false,
  "image_url": "",
  "size": 20,
  "private": null,
  "booked": 1,
  "waiting": 0,
  "modified": 1774321459,
  "program_id": "64a833abc...",
  "level": "",
  "facility": "",
  "trainers": ["64b..."],
  "status": "AVAILABLE",
  "open_booking_time": 0,
  "close_booking_time": 0,
  "session_id": 12345,
  "booking_status": null,
  "model": "appointments",
  "model_id": "64a..."
}
```

**Known undocumented fields** that may appear in responses: `booking_status`, `session_id`, `model`, `model_id`, `open_booking_time`, `close_booking_time`.

### GET /2.0/events/{id}

Get a single event by ID.

**Response** (`GetEventResponse`): Event object at top level (not in `data[]`):
```json
{
  "success": true,
  "_id": "...",
  "name": "...",
  "size": 20,
  "booked": 1,
  ...
}
```

---

## Bookings

### GET /2.2/branches/{branchId}/bookings

List bookings for a branch with optional filters.

**Query params**:

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `event_id` | string | no | Filter by event (24-hex) |
| `course_id` | string | no | Filter by course |
| `event_type` | string | no | `events`, `courses`, `time_slots` |
| `status` | string | no | Filter by booking status |
| `limit` | int32 | no | Page size |
| `page` | int32 | no | Page number |
| `start_date` | int64 | no | Unix timestamp |
| `end_date` | int64 | no | Unix timestamp |
| `modified_start_date` | int64 | no | Unix timestamp |
| `modified_end_date` | int64 | no | Unix timestamp |
| `time_start_start_date` | int64 | no | Filter booking time_start after |
| `time_start_end_date` | int64 | no | Filter booking time_start before |
| `time_finish_start_date` | int64 | no | Filter booking time_finish after |
| `time_finish_end_date` | int64 | no | Filter booking time_finish before |

**Response**:
```json
{
  "meta": {"totalCount": 20, "page": 1, "limit": 50},
  "data": [BranchBooking]
}
```

**BranchBooking object**:
```json
{
  "_id": "6824c79c0dd60fde9a0d180f",
  "branch_id": "669a...",
  "namespace": "kidstronglive",
  "user_id": "66c7...",
  "user_name": "Jane Doe",
  "status": "BOOKED",
  "type": "booking",
  "program_id": "64a...",
  "event_id": "68b3...",
  "event_name": "8 - 11 Years",
  "model": "appointments",
  "model_id": "68b3...",
  "model_name": "8 - 11 Years",
  "guest_bookings": 0,
  "attended": false,
  "paid": true,
  "is_from_waiting_list": false,
  "is_late_cancellation": false,
  "time_start": "2026-03-29 12:15:00",
  "time_finish": "2026-03-29 13:00:00",
  "modified": "2026-02-15 13:32:55",
  "created": "2025-05-14 16:41:00",
  "is_first": false,
  "canceled_at": null,
  "region": "US",
  "timestamp": 1747237260
}
```

**Status values**: `BOOKED`, `WAITING`, `CANCELED`, `RESERVED`, `FAILED`

**Type values**: `booking`, `events`, `courses`, `time_slots`

### POST /2.3/branches/{branchId}/bookings

Create a new booking. **Write operation — use only with explicit authorization.**

```json
{"model_id": "{event_id}", "user_id": "{user_id}", "model": "event"}
```

### GET /2.0/bookings

Get bookings for a specific user. Requires `branchId` and `user_id` as query params.

**Query params**: `branchId`, `user_id` (required), `start`, `end`, `limit`, `page`, `exclude_cancelled`, `event_id`, `program_id`, `model`, `model_id`, `time_slot_id`

---

## Courses

### GET /3.0/locations/{locationId}/courses

List courses for a location. Different from events — courses have multiple sessions.

---

## Users

### GET /2.1/branches/{branchId}/users

List users for a branch.

**Query params**: `limit`, `page`, `type` (`member`, `staff`, `lead`), `search`, `membership_status`, `modified_start_date`, `modified_end_date`, `sort_by`

### GET /2.0/members/{userId}

Get a single member/user by ID.

---

## Memberships

### GET /2.0/memberships

List memberships (plans) for a branch.

**Query params**: `private` (`true`/`false`/omit for all)

### GET /2.0/memberships/{membershipId}

Get a single membership plan.

---

## Staff

### GET /2.0/staff

List staff members for a branch.

### GET /2.0/staff/{staffId}

Get a single staff member.

---

## Branch

### GET /2.0/branches/{id}

Get branch details.

---

## Attendances

### GET /2.0/attendances

Get attendances (check-in records). Distinct from bookings — attendances track physical check-in, bookings track reservation status.

---

## Common Response Envelope

Most endpoints wrap responses in:
```json
{
  "success": true|false,
  "message": "optional message",
  "message_code": "optional code",
  "errors": []
}
```

When `success` is `false`, inspect `message` and `errors[]` for details. HTTP status may still be 200 with `success: false`.
