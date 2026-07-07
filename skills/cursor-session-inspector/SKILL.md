---
name: cursor-session-inspector
description: "Inspect local Cursor session data under ~/.cursor and Cursor Application Support: UI composers, CLI agents, transcript mirrors, subagents, stop-hook imports, and AI code attribution."
---

# Cursor Session Inspector

## Overview

Use this skill to inspect persisted Cursor sessions on the local machine. The raw Cursor data remains the source of truth; the inspector keeps a derived SQLite cache at `~/.cursor/inspector/session_inspector.db` for fast listing, summaries, subagent lookups, and AI-attribution reports.

This inspector mirrors the operator surface used by `claude-session-inspector` and `codex-rollout-inspector`: `locate`, `list`, `summary`, `records`, `subagents`, `refresh`, and `rebuild`. It also adds `report_ai_attribution.py` for Cursor's AI-code tracking database.

## Log Kinds

- UI composers: `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`
- Cursor CLI agents: `~/.cursor/chats/<workspace>/<agentId>/store.db`
- Transcript mirrors: `~/.cursor/projects/<slug>/agent-transcripts/<sessionId>/<sessionId>.jsonl`
- AI attribution: `~/.cursor/ai-tracking/ai-code-tracking.db`
- Inspector cache: `~/.cursor/inspector/session_inspector.db`
- Optional stop-hook markers: `~/.cursor/inspector/pending/*.json`
- Optional raw hook payload captures: `~/.cursor/inspector/payload-captures/*.json` when `CURSOR_INSPECTOR_CAPTURE_HOOK_PAYLOAD=1`

For split Cursor profiles, set both paths explicitly:

- `CURSOR_HOME`: profile Cursor home, for example `~/.cursor-homes/jb/.cursor`
- `CURSOR_APP_SUPPORT`: profile user-data root, for example `~/.cursor-instances/jb`
- `CURSOR_PROFILE`: known profile name, currently `jb` or `ks`, when explicit paths are not already set

When `CURSOR_APP_SUPPORT` is set, UI composers are read from
`$CURSOR_APP_SUPPORT/User/globalStorage/state.vscdb`.

On Luke's machine, prefer profile-aware invocation:

- JB: `uv run --python 3.14 scripts/inspect_session.py --cursor-profile jb locate`
- KidStrong: `uv run --python 3.14 scripts/inspect_session.py --cursor-profile ks locate`

If neither `CURSOR_HOME` nor `CURSOR_APP_SUPPORT` is set, the inspector infers the profile from the current working directory when it is under `~/code/github.com/jb-web-dev` or `~/code/github.com/KidStrong`. If the working directory is outside those roots and the user has not named a profile, ask whether to inspect `jb` or `ks` before running commands that read, refresh, rebuild, summarize, or reconcile sessions.

## Compatibility Policy

- Cursor's local storage is private implementation detail. Treat additive fields as expected and unknown versions as diagnostics, not hard failures.
- UI-store reads snapshot-copy `state.vscdb` before parsing so Cursor can keep writing to the hot database.
- CLI `store.db` data is walked through the observed Merkle-DAG blob format. Unknown blob shapes are retained as raw text records where possible.
- Transcript mirrors are fallback-quality only: they lack timestamps, token counts, tool results, thinking blocks, and request ids. Cursor stop-hook payloads are the preferred source for generation-level token totals when present.
- Cursor may emit stop-hook token fields for a parent composer without emitting matching stop-hook payloads for UI-created subagent composers. Treat missing child hook events as unavailable data, not a zero-cost run.
- Schema changes are rebuild-oriented. If the cache schema version changes, run `rebuild`.

## Workflow

1. Start with `locate` to confirm raw paths, cache status, counts, and hook configuration.
2. Run `refresh` to incrementally import Cursor data into SQLite.
3. Use `list`, `summary`, and `subagents` for cached operator workflows.
4. Use `records` for raw stateless inspection of one UI composer, CLI agent, transcript file, or matching id.
5. Use `--profile ingestion` when downstream tooling needs the normalized `session_inspector_v2` envelope.
6. Use `report_ai_attribution.py` for commit, branch, day, and session-level AI-code attribution.

## Quick Start

- Locate Cursor data and hook snippets:
  - `uv run --python 3.14 scripts/inspect_session.py --cursor-profile jb locate`
  - `uv run --python 3.14 scripts/inspect_session.py --cursor-profile ks locate`
- Build or update the SQLite cache:
  - `uv run --python 3.14 scripts/inspect_session.py --cursor-profile <jb|ks> refresh`
- Reconcile pending stop-hook markers only:
  - `uv run --python 3.14 scripts/inspect_session.py --cursor-profile <jb|ks> refresh --pending`
- Rebuild the cache:
  - `uv run --python 3.14 scripts/inspect_session.py --cursor-profile <jb|ks> rebuild`
- List recent sessions:
  - `uv run --python 3.14 scripts/inspect_session.py --cursor-profile <jb|ks> list --limit 20`
- Summarize the newest session:
  - `uv run --python 3.14 scripts/inspect_session.py --cursor-profile <jb|ks> summary`
- Print raw records:
  - `uv run --python 3.14 scripts/inspect_session.py records <composer-or-agent-id> --tail 20`
- List subagents for a parent:
  - `uv run --python 3.14 scripts/inspect_session.py subagents <composer-id>`
- Report AI attribution by commit:
  - `uv run --python 3.14 scripts/report_ai_attribution.py --begin 2026-04-01 --end 2026-05-17 --by commit --limit 10`

## Parsing Guidance

- Treat `composerData:<id>` as one UI session and `bubbleId:<composerId>:<bubbleId>` as the ordered user/assistant turn data.
- Use `composerData.fullConversationHeadersOnly` as the bubble index; load missing bubble rows best-effort.
- Treat `composerData.subagentComposerIds` as the authoritative UI subagent link.
- Use Cursor stop-hook payload token fields when available; summaries and subagent listings fall back to `composerData.usageData` and per-bubble `tokenCount` because small bubbles often report zero tokens.
- Composer tool calls live in each assistant bubble's `toolFormerData` dict (one tool per `capabilityType == 15` bubble), NOT in `toolResults` (which is usually empty). The importer extracts `toolFormerData` into `tool_calls`; `name` is the tool (`ripgrep_raw_search`, `read_file_v2`, `glob_file_search`, `run_terminal_command_v2`), and `params`/`rawArgs` are JSON-encoded strings that must be decoded for `file_path`/`command`. Composer uses these primitive filesystem tools — a run with no `codebase_search`/`codebaseContextChunks` did not engage Cursor's semantic codebase index.
- Put global CLI flags before the subcommand, e.g. `inspect_session.py --json summary <id>`. `inspect_session.py summary <id> --json` is invalid.
- Treat CLI agent ids as a separate namespace. The cache uses `cli:<workspace>:<agentId>` to avoid collisions with UI composer ids.
- Prefer UI/CLI stores over transcript mirrors. Import transcript-only sessions only when no canonical store row exists.
- Hook integration is opt-in. `locate` prints a snippet for `~/.cursor/hooks.json`; never overwrite a user's hook file automatically.
- The default hook records token metadata only. For troubleshooting, set `CURSOR_INSPECTOR_CAPTURE_HOOK_PAYLOAD=1` on the hook command to write bounded raw payload captures; raw captures may include user and workspace metadata.
- In split Cursor setups, include `CURSOR_HOME`, `CURSOR_APP_SUPPORT`, and preferably `UV_CACHE_DIR` in the hook command so imports resolve the correct profile and do not depend on fake-home cache directories.
- Do not inspect the default Cursor profile on Luke's machine unless the user explicitly asks for it. Use `--cursor-profile jb`, `--cursor-profile ks`, `CURSOR_PROFILE`, or repo-root inference; ask when ambiguous.

## Resources

- Additional raw inspection recipes: `references/recipes.md`
- Cursor model pricing reference: `references/cursor-model-pricing.md`
- Main CLI: `scripts/inspect_session.py`
- Incremental hook entrypoint: `scripts/sync_session.py`
- AI attribution report: `scripts/report_ai_attribution.py`
