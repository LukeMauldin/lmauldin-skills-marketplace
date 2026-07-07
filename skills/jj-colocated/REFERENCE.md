# jj-colocated — Reference

Companion to [SKILL.md](SKILL.md). Tested with **jj 0.42.0** (verify flags if your
jj version differs — other docs may reference 0.41.0).

## Version pins (verify if jj version differs)

These bit older docs/skills elsewhere — the values below are correct for 0.42.0:

| Concern | 0.42.0 (use this) | Notes |
|---|---|---|
| Rebase destination | `jj rebase --onto <dest>` (`-o`) | `-d` is an accepted **alias** for `--onto` on 0.42 (`jj rebase --help` → `-o, --onto … [aliases: -d]`); prefer `--onto` for clarity, but `-d` is **not** an error. (`--destination` was the pre-0.40 spelling.) |
| Drop merged commit on rebase | `jj rebase ... --skip-emptied` | manual `jj abandon` |
| Push a new bookmark | `jj git push --bookmark <name>` (auto-creates the remote bookmark) | `--allow-new` — **removed in 0.42** (was deprecated in 0.41); unneeded, do not add it |
| Describe commit | `jj describe -m` / `jj desc -m` | bare `jj describe` opens `$EDITOR` (hangs agent) |
| Advance bookmark after commit | `jj bookmark advance --to @- <name>` | bare `jj bookmark advance` targets `@` by default; after `jj commit`, use explicit name + `@-` |
| Bookmark move backward | `jj bookmark move <name> --to <rev> --allow-backwards` | required when jj refuses a move to an ancestor (stale/divergent bookmark recovery) |

When in doubt, run `jj <cmd> --help` and read the `Usage:` line before scripting it.

## Command cheatsheet (agent-safe forms only)

| Action | Command |
|---|---|
| Status | `jj st` |
| Log (current stack) | `jj --no-pager log -r 'trunk()..@'` |
| Log (all) | `jj --no-pager log` |
| Show a commit | `jj --no-pager show <change-id>` |
| Diff (unified) | `jj --no-pager diff --git` |
| Diff (committed in rev) | `jj --no-pager diff -f <rev>` |
| Start work on latest main | `jj git fetch && jj new 'trunk()'` |
| Realign to PR tip | `jj git fetch && jj new <bookmark>@origin` |
| Finalize commit + open next | `jj commit -m "msg"` |
| Set/replace message | `jj describe -m "msg"` (alias `jj desc`) |
| New empty child | `jj new [<parent-rev>]` |
| Resume an earlier change | `jj new <rev>` then edit then `jj squash` (preferred over `jj edit`) |
| Fold working copy into parent | `jj squash` |
| Auto-distribute edits to owning commits | `jj absorb` |
| Move a commit (+ its descendants) | `jj rebase -s <rev> --onto <dest>` |
| Move a whole branch | `jj rebase -b @ --onto <dest>` |
| Update stack to latest main | `jj git fetch && jj rebase -b @ --onto 'trunk()' --skip-emptied` |
| Drop a commit | `jj abandon <change-id>` (descendants rebase to its parent) |
| Discard working-copy edits | `jj restore [paths]` |
| Create bookmark | `jj bookmark create <name> -r <rev>` |
| Advance bookmark after commit | `jj bookmark advance --to @- <name>` |
| Move bookmark | `jj bookmark move <name> --to <rev>` |
| Move bookmark (stale recovery) | `jj bookmark move <name> --to <rev> --allow-backwards` |
| List bookmarks | `jj --no-pager bookmark list` |
| Fetch | `jj git fetch` |
| Push specific bookmarks | `jj git push --bookmark <name> [--bookmark <name>...]` |
| Push, auto-named per change | `jj git push -c <rev>` |
| Operation log | `jj --no-pager op log` |
| Undo last op | `jj undo` |
| Restore to an op | `jj op restore <op-id>` |
| Add a workspace | `jj workspace add <path> -r 'trunk()' --name <name>` |
| List workspaces | `jj workspace list` |
| Workspace root path | `jj workspace root --name <name>` |
| Drop a workspace | `jj workspace forget <name>` (then delete dir) |
| Fix a stale workspace | `jj workspace update-stale` |

### `jj rebase` — pick the right selector (`-b` vs `-s` vs `-r`)

Choosing wrong here is the most common rebase mistake — `-r` when you meant `-s`
silently detaches the rest of your stack. Verified on 0.42.0:

- **`-b <rev>`** — the whole **b**ranch containing `<rev>` (everything back to the
  trunk fork-point). The default for "move my entire stack onto new main":
  `jj rebase -b @ --onto 'trunk()'`.
- **`-s <rev>`** — `<rev>` **and all its descendants** (a subtree). Use to relocate
  part of a stack, e.g. linearize an impl commit + working copy onto a doc commit:
  `jj rebase -s <impl> --onto <doc>`.
- **`-r <rev>`** — **only** `<rev>`; its descendants are left behind (rebased onto
  `<rev>`'s parent). Reaching for `-r` when you meant `-s` orphans the rest of the
  stack. If you do it by accident: `jj undo`, then redo with `-s`.

## Bookmark semantics — `@` vs `@-`

After `jj commit -m "msg"`:

- **`@-`** — the commit you just finalized (put work here when moving a bookmark)
- **`@`** — new empty child (where new edits land)

Common mistake: `jj bookmark move feat --to @` after `jj commit` — the bookmark
lands on the empty child, not the commit with your changes. Use `--to @-`.

The same trap applies to bare `jj bookmark advance`: on 0.42.0 its default target is
`revsets.bookmark-advance-to`, which defaults to `@`. In agent workflows, always
name the bookmark and target explicitly:

```bash
jj bookmark advance --to @- feat
```

Use `jj bookmark move` instead of `advance` when the bookmark is stale/divergent or
the update is intentionally non-forward. Add `--allow-backwards` only after verifying
the exact target with `jj --no-pager log -r '<bookmark>' --no-graph` and
`jj --no-pager diff -f <bookmark>`.

Use `--allow-backwards` when jj refuses the move because the bookmark still points
at a stale divergent sibling and you are moving it back to the canonical parent line
(e.g. after Workflow E realignment).

For personal, non-agent use of implicit `jj bookmark advance`, constrain the source
revset so it cannot select trunk/main ancestors:

```toml
[revsets]
bookmark-advance-from = "heads(trunk()..to & bookmarks())"
```

Agents should still use explicit bookmark names; this config is a guardrail, not a
workflow dependency.

## Revsets (for `-r` / `--onto` targets)

- `@` working copy · `@-` its parent
- `trunk()` the default bookmark of `origin`/`upstream` (e.g. `main@origin`); the standard
  rebase target after `jj git fetch`. Robust on repos whose default branch isn't `main`.
- `trunk()..@` your current stack — correct **only when `@` is at the tip**. After a
  mid-stack edit, `@` is off to the side; use `trunk()..` (omit `@`) to see the whole
  stack, or `jj edit <tip-bookmark>` first to put `@` back on the tip.
- `::@` ancestors of `@` · `@::` descendants of `@`
- `<bookmark>@origin` the remote-tracking position of a bookmark (what the PR shows)
- `<change-id>` a stable change ID (e.g. `tqpwlqmp`); preferred over commit SHAs

### Path-scoped commits and filesets

jj path arguments are filesets. Literal paths containing glob metacharacters need
escaping, especially Next-style route folders such as `[id]`:

```bash
jj commit -m "msg" src/app/api/foo/\[id\]/route.ts
```

Verify the path with `jj file list` or `jj --no-pager diff --git` before committing.
Do not use unverified `file("...")` examples; jj 0.42.0 does not provide a `file`
fileset function in the default language.

## Where am I? — diff and status commands

| Command | Shows |
|---|---|
| `jj st` | WC changes relative to `@`; bookmark ahead/behind hints |
| `jj diff` | Changes in `@` relative to its parent (includes unsnapshotted WC) |
| `jj diff -f @` | What `@` introduces vs its parent; **empty if `@` matches parent** |
| `jj diff -f <rev>` | What `<rev>` introduces vs its parent |
| `jj bookmark list` | **Primary signal** for ahead/behind/divergent bookmark state |
| `git status` | Git's view of detached HEAD — **not authoritative** for jj PR state |
| `git diff origin/<branch>` | Git tree vs remote — cross-check only; may not reveal jj bookmark divergence |

Do not triangulate jj state from a single `git diff` or `git status` alone.

## Diagnostic recipes

### "Are there local changes not on the PR?"

```bash
jj git fetch
jj st
jj --no-pager bookmark list
jj --no-pager log -r 'feat | feat@origin'
jj --no-pager diff -f @
jj --no-pager diff
git diff --stat origin/feat
```

Interpret:

- PR tracks **`feat@origin`**, not local `@`.
- If `jj diff -f @` is empty but `jj diff` is large, `@` matches its parent but WC
  (or jj's view of pending edits) does not — see Divergent changes.
- If `git diff origin/feat` is empty but `jj diff` is large, git and jj disagree on
  what tree to compare — trust `jj bookmark list` and `feat@origin`.

### "What happened?" (op log patterns)

```bash
jj --no-pager op log --limit 25
```

Search for:

- `describe` without subsequent `commit` before `push bookmark` — PR may have
  content that local `@` no longer shows
- `push bookmark` — what was exported to git
- `import git refs` — raw git mutation jj absorbed (recoverable via `jj undo`)

## Conflicts (non-interactive resolution)

jj **commits conflicts** rather than blocking — a rebase/squash never halts the
agent. To resolve:

1. `jj st` lists conflicted files.
2. **Do not** run `jj resolve` (interactive). Open each conflicted file with
   Read/Edit and remove the conflict markers directly.
3. `jj st` again to confirm the conflict cleared. The fix lands in whatever commit
   carried the conflict; descendants auto-rebase onto the resolution.

## Divergent changes (a jj-native failure mode; no git analogue)

A change is **divergent** when two+ visible commits share one change ID. `jj log`
tags each `(divergent)`; surface it with a template guard —
`if(divergent, " DIVERGENT", " ok")`.

**Cause:** the same change was rewritten in two different operations or
workspaces, or rewritten locally while an older copy still lives on a remote
bookmark (`@origin`), so the change ID now maps to more than one commit. A plain
`jj rebase` can also create divergence; `jj rebase --keep-divergent` governs that
behavior (see `jj rebase --help`).

### Post-push divergent twin (colocated)

Common after `jj git push` when the bookmark pointed at mutable `@`:

```
local bookmark:   qmsytxtv/0  <sha-a>  (empty)        (divergent)
remote bookmark:  qmsytxtv/1  <sha-b>  (full content) ← PR points here
WC on disk:       may match remote content
jj bookmark list: ahead by 1, behind by 1
```

**Symptoms:** `jj diff -f @` empty, `jj diff` large, PR has files local `@` lacks.

**Fast fix:** Workflow E in SKILL.md — `jj new feat@origin` to realign local to the
PR tip. For persistent twins, use SHA-level resolution below.

**The trap:** while divergent, the change ID is ambiguous. `jj abandon
<change-id>` / `jj edit <change-id>` either fail or act on the wrong copy. And if
one of the twins is the `@origin` copy, it is **immutable** — `jj abandon` on it
errors with `Commit … is immutable / would rewrite N immutable commits`.

**Resolution (operate by commit SHA, not change ID):**

```bash
# 1. List both copies with SHA + divergence flag
jj --no-pager log -r 'change_id(<id>)' --no-graph \
  -T 'change_id.shortest(8) ++ " " ++ commit_id.short() ++ if(divergent, " DIVERGENT", " ok") ++ "\n"'

# 2. Make the copy you want to KEEP the live/mutable local one. If the stale twin is
#    @origin (immutable), track the remote bookmark, then rewrite the local side so the
#    surviving copy is local — e.g. rebase the stack so the keeper becomes current:
jj bookmark track <bookmark> --remote=origin
jj rebase -b @ --onto <dest> --skip-emptied        # or rebase -s <keeper-sha> --onto <parent>

# 3. Abandon the STALE copy BY SHA (change ID won't disambiguate)
jj abandon <stale-commit-sha>

# 4. Confirm the change now reads `ok`, not DIVERGENT
jj --no-pager log -r 'change_id(<id>)' --no-graph \
  -T 'commit_id.short() ++ if(divergent, " DIVERGENT", " ok") ++ "\n"'
```

`jj abandon <sha>` of an already-hidden commit prints `Skipping 1 revisions that
are already hidden. No revisions to abandon.` — that is a benign no-op, **not** an
error; do not retry or escalate.

## Colocated gotchas

- **Detached HEAD in git is normal.** jj keeps git HEAD detached. Do not use
  `git checkout <branch>` to *drive* the repo — use `jj new <bookmark>` for that.
  **Exception:** Workflow H in SKILL.md — temporary `git checkout` for IDE/LSP
  attach only; never `git commit` after checkout; any jj op re-detaches HEAD.
- **Every `jj` command syncs with git** (import + export). If raw `git` made
  changes, the next `jj` command imports them as an operation — recoverable, but
  prefer driving mutations through jj to keep the op log meaningful.
- **No staging area; WC is mutable `@`.** Before most jj commands (including push),
  jj snapshots file changes into `@`. `jj git push --bookmark feat` exports whatever
  commit `feat` points at — if that is `@`, the PR gets current file state even
  without `jj commit`.
- **Bookmarks ≠ git branches.** A bookmark on a *rewritten* commit moves with the
  rewrite automatically; a bookmark does **not** advance when you add a *new*
  commit on top — move it manually to `@-` before pushing.
- **`jj git push` only pushes bookmarks.** Unbookmarked commits never reach the
  remote. Each PR in a stack needs its own bookmark.
- **Large-repo import cost:** in repos with very many refs, per-command git import
  can be slow; `jj util gc` occasionally helps.
- **Pushing respects your existing git remote** and its auth/SSH config. PR
  *creation* still goes through `gh`.
- **`Error: Commit X is immutable` / `would rewrite N immutable commits`** — you tried
  to rewrite a commit jj protects: one already pushed to a remote bookmark, or in
  `trunk()`'s ancestry (the `immutable_heads()` config). The usual trigger is reaching
  for `jj edit <bookmark>` to "check out" a branch. Fix: to build on top, `jj new
  <bookmark>` (creates a child) — don't rewrite the shared commit. `jj edit
  --ignore-immutable` exists but is rarely what you want; `git switch` is a worse
  fallback that drops you out of jj.

## Workspaces (parallel working copies) gotchas

- **Replaces `git worktree`** — jj does not support git worktrees; do not create one in
  a jj repo. Use `jj workspace add`.
- **No `.git/` in added workspaces.** Only the main colocated workspace has `.git/`. Inside
  an added workspace, `git`/`gh` fail; `jj` (including `jj git push`/`fetch`) works.
  Run `gh` PR commands from the main workspace.
- **Default base is a sibling, not your work.** `jj workspace add <path>` with no `-r`
  bases the new `@` on the *parents of your current `@`*. Always pass `-r 'trunk()'` (or a
  specific change) unless you truly want a sibling of the current change.
- **Stale working copy:** editing a workspace's commit from another workspace can mark it
  stale → `jj workspace update-stale` in that workspace. Often auto-reconciles on the next
  command; only act on an explicit stale report.
- **Cleanup:** `jj workspace forget <name>` stops tracking it; delete the directory
  separately (order doesn't matter).

## git habit → jj equivalent

| git | jj |
|---|---|
| `git add -A && git commit -m` | (no staging) edit files — they live in mutable `@` immediately; `jj commit -m` finalizes `@` into `@-` and opens new empty `@` |
| `git commit --amend` | `jj squash` (from a child) or `jj describe -m` for message-only |
| `git stash` / `git stash pop` | nothing needed — working copy is already a commit; `jj new` to set it aside |
| `git rebase main` | `jj rebase -b @ --onto 'trunk()'` |
| `git rebase --onto main <parent> <dep>` | `jj rebase -b @ --onto 'trunk()' --skip-emptied` |
| `git reset --hard <ref>` recovery | `jj op restore <op-id>` |
| `git switch <branch>` / `git checkout <branch>` (work on it) | `jj new <bookmark>` (child on its tip) — **not** `jj edit` (fails `immutable` on pushed tips) |
| `git switch -c feat` then push | `jj commit -m "..."`; `jj bookmark create feat -r @-`; `jj git push --bookmark feat` |
| `git cherry-pick X` | `jj rebase -r X --onto @` (or duplicate: `jj duplicate X`) |
| `git worktree add <path>` | `jj workspace add <path> -r 'trunk()'` (no `.git` inside — use jj/`jj git push` there, `gh` from main workspace) |
| "What's on the PR?" | `jj log -r '<bookmark>@origin'` — not local `@` or `git status` |

## Do NOT

- Init jj for a **read-only** task. Only colocate before a *mutation* (SKILL.md decision rules 1–2).
- Use any interactive form: `jj split`, `jj squash -i`, `jj resolve`, `jj diff -i`,
  bare `jj describe`/`jj commit` (opens `$EDITOR`).
- Omit `--no-pager` on output commands (hangs on the pager).
- Treat the default side-by-side `jj diff` as corruption — use `--git` for `+/-`.
- Push expecting unbookmarked commits to go (they won't).
- Pass `--allow-new` to `jj git push` — **removed in 0.42** (`error: unexpected argument`);
  a plain `jj git push --bookmark <name>` already creates and tracks the remote bookmark.
- Run bare `jj bookmark advance` after `jj commit`; it targets `@` by default, and
  `@` is the empty child. Use `jj bookmark advance --to @- <name>`.
- Treat `jj bookmark advance` as recovery. Use `jj bookmark move --allow-backwards`
  for verified stale/divergent/non-forward bookmark repairs.
- Merge main into your branch to catch up (`jj new @ main@origin` / `git merge main`).
  Rebase onto `trunk()` instead (Workflow D) — even when your base hasn't merged yet.
  A merge commit inside a stack forces a later manual linearization (`jj undo` + `-s`).
- Use `jj edit` to "switch to" an existing pushed branch — it tries to rewrite that
  (immutable) commit and fails. `jj new <bookmark>` builds a child on its tip instead.
- Rebase/rewrite a bookmark you did **not** author without first checking ownership
  (`gh pr view <n> --json author`, `git log -1 --format=%ae <tip>`). Pushing the rewrite
  force-updates a teammate's shared history — the "teammates unaffected" property only
  holds while jj metadata stays local. Confirm before pushing a rewrite of a shared bookmark.
- Trust a change ID while it is `(divergent)` — disambiguate by commit SHA (see Divergent changes).
- Use `git status` or a single `git diff origin/<branch>` as the source of truth for
  whether work is on the PR — use `jj bookmark list` and `feat@origin`.
- Move a bookmark to `@` immediately after `jj commit` — the work is in `@-`.
