# ClickUp MCP → CLI Coverage Matrix

Goal: every one of the 18 commonly-used ClickUp MCP tools has a bundled CLI equivalent, so
an agent with only `bash` + `CLICKUP_API_TOKEN` (no ClickUp MCP) can do all of them. The
19th (`clickup_get_custom_fields`) is included as a natural extra.

All scripts: Python 3.14+, stdlib only, run via `uv run --python 3.14 scripts/<name>.py`.
Verified live against workspace `12606327` on 2026-06-09. **All 18 green.**

| # | MCP tool | CLI command | Type | Verification |
|---|----------|-------------|------|--------------|
| 1 | `clickup_get_task` | `get_task.py <id>` | READ | ✅ live — `get_task.py 868jyvd11` returned the task (existing, unchanged) |
| 2 | `clickup_get_list` | `get_list.py <id>` | READ | ✅ live — `get_list.py 900600273627` → "Product Roadmap" (existing, unchanged) |
| 3 | `clickup_get_task_comments` | `fetch_comments.py <id>` | READ | ✅ live — `fetch_comments.py 868jyvd11` → count:0 (existing, unchanged) |
| 4 | `clickup_create_task` | `create_task.py <name>` | WRITE | ✅ round-trip — created 2 throwaway tasks; **new live member fallback** verified (`--assignee "luke laughlin"` → `[16813750]`) |
| 5 | `clickup_update_task` | `update_task.py <id> ...` | WRITE | ✅ round-trip — comment applied; **new live member fallback** added |
| 6 | `clickup_create_task_comment` | `update_task.py <id> --comment` | WRITE | ✅ round-trip — "comment ok" on task A |
| 7 | `clickup_filter_tasks` | `fetch_filtered_tasks.py --preset server` | READ | ✅ live — wrote `/tmp/srv.json` (existing, unchanged) |
| 8 | `clickup_get_folder` | `get_folder.py <folder_id>` | READ | ✅ live — `get_folder.py 90100118193` → "Server Sprint Folder", 3 lists (**new**; `get_current_sprint.py` refactored to reuse its `get_folder_lists()` — output byte-identical before/after) |
| 9 | `clickup_resolve_assignees` | `resolve_members.py <name\|email\|id>` | READ | ✅ live — `"luke laughlin"` → 16813750; email exact match; `--list` → 100 members; ambiguous `luke` returns candidates (**new**, `GET /team`) |
| 10 | `clickup_get_document_pages` | `docs.py get-pages --doc-id <id>` | READ | ✅ live — doc `c0pvq-10131`, `content_format=text/md` returned page content (**new**, v3) |
| 11 | `clickup_list_document_pages` | `docs.py list-pages --doc-id <id>` | READ | ✅ live — doc `c0pvq-10131` → 1 page `c0pvq-4511` "Scope" (**new**, v3) |
| 12 | `clickup_search` | `search.py <query>` | READ | ✅ live — matched doc "Scope" and task "International Expansion…" (**new**; *imperfect parity* — see note below) |
| 13 | `clickup_get_workspace_hierarchy` | `get_workspace_hierarchy.py` | READ | ✅ live — composed Tech space → folders → lists tree (**new**) |
| 14 | `clickup_add_tag_to_task` | `task_relations.py add-tag <id> <tag>` | WRITE | ✅ round-trip — added tag `server` to task A (confirmed in `tags[]`); dry-run shown (**new**) |
| 15 | `clickup_add_task_link` | `task_relations.py add-link <id> <links_to>` | WRITE | ✅ round-trip — A↔B linked (`linked_tasks` populated); dry-run shown (**new**) |
| 16 | `clickup_add_task_dependency` | `task_relations.py add-dependency <id> --depends-on <x>` | WRITE | ✅ round-trip — A `depends_on` B confirmed in `dependencies[]`; body field `depends_on` arbitrated live (**new**) |
| 17 | `clickup_remove_task_dependency` | `task_relations.py remove-dependency <id> --depends-on <x>` | WRITE | ✅ round-trip — `dependencies[]` cleared to `[]`; dry-run shown (**new**) |
| 18 | `clickup_delete_task` | `delete_task.py <id> --yes` | DESTRUCTIVE | ✅ round-trip — dry-run-by-default verified on real task ("would DELETE… re-run with --yes"); `--yes` deleted A & B; both then `GET → 404` (**new**) |
| 19 | `clickup_get_custom_fields` | `get_custom_fields.py <list_id>` | READ | ✅ live — `get_custom_fields.py 900600273627` → 11 fields incl. option UUIDs (Apps→Server `90ca02d6…`) (**new, stretch**) |

## Conventions shared by the new scripts

- **Token resolution (all scripts):** `CLICKUP_API_TOKEN` env var first, then the file
  `~/.agents/clickup_key.txt` (entire contents = the token). Shared `clickup_auth.resolve_token()`.
- JSON to stdout by default; `--format summary` for humans; `--quiet` suppresses stderr only.
- Every mutation supports `--dry-run`, which prints the exact request (method, full URL, body).
- `api_request` handles empty/204 bodies (returns `{}`) and retries HTTP 429 with
  `Retry-After`-aware backoff; loops sleep 0.15s between calls.
- Task IDs accept the `CU-` display prefix (stripped via `normalize_task_id`).
- Custom-field writes use option **UUIDs**; reads return orderindex (unchanged behavior).

## Imperfect-parity notes

- **`search.py` (clickup_search):** ClickUp's public API has **no free-text search endpoint**.
  MCP's `clickup_search` wraps an internal ranked, cross-entity index (~20 hits). `search.py`
  approximates it with a **client-side substring scan** over task names (+ `--include-description`)
  and doc **titles** — no server-side relevance ranking, no comment search, doc bodies not
  searched. Unscoped scans are bounded by `--max-pages`/`--limit` with a 0.15s delay; scope
  with `--list/--space/--folder` for speed. For exhaustive custom-field filtering use
  `fetch_filtered_tasks.py`.
- **`resolve_members.py` (clickup_resolve_assignees):** `GET /team/{team_id}/member` does **not
  exist** (404). The script uses `GET /team` and filters to the workspace's `members[]`, which
  returns up to ~100 members — sufficient for all named team members. Ambiguous name substrings
  (e.g. "luke" → Luke Mauldin + Luke Laughlin) return `user: null` plus a `candidates` list.
- **Raw-passthrough parity:** for tools whose MCP return envelope is not observable
  (`get_folder`, `get_workspace_hierarchy`, `get_custom_fields`, `search`), the scripts return
  the raw API JSON under a thin wrapper rather than reverse-engineering the MCP envelope.

## Beyond the 18 (also covered by scripts)

- **File attach** (`clickup_attach_task_file`) → `attach_file.py <task_id> <file>` — native
  multipart upload from a local path (MCP takes only inline base64 / public URL). Verified live
  on 2026-06-09: uploaded a 50-byte text file to a throwaway task, confirmed via `get_task.py`
  (`attachments[]` populated with the returned `attachment_id` / `url`).

## Still MCP-only

Document write/create, chat, time tracking, and tag/link **removal**
(`clickup_remove_tag_from_task` / `clickup_remove_task_link`).
