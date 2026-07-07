---
name: jj-colocated
description: "Drive Jujutsu (jj) in colocated git repos: single-branch PRs, stacked dependent PRs, realigning local state with a remote PR tip, restacking after squash-merges, and recovering from bad operations via the jj operation log — while git, gh, GitHub, and teammates stay unaffected (jj metadata is local). Use when the repo contains a `.jj/` directory, when authoring or updating a PR branch, when local `@` diverged from `bookmark@origin`, when restacking a stack, when reconciling after a parent PR squash-merged, or when the user mentions jj/jujutsu."
---

# jj in colocated git repos

Tested with **jj 0.42.0**. Flags differ across versions — see Version pins in
[REFERENCE.md](REFERENCE.md).

Colocated mode = `.git/` and `.jj/` side by side: jj drives version control while
git, `gh`, GitHub, and teammates keep working unchanged (the extra jj metadata —
change IDs, operation log — stays local in `.jj/`). This skill provides the
mechanics for the high-value jj workflows. *Whether* jj is your default VCS and
whether to auto-init it in a repo is a per-user / per-project choice — set that in
your own config/rules; this skill stays neutral on policy.

Harness-specific guidance:

- If the active agent harness is Codex, read
  [references/codex-sandbox.md](references/codex-sandbox.md) before running jj
  commands. Other harnesses should skip it unless explicitly relevant.

## Mental model — jj is not git

Agents trained on git will misread jj unless this model is internalized first.

| Layer | What it is | What GitHub shows |
|---|---|---|
| Files on disk | Should match `@`; can desync from jj's view | — |
| `@` | **Mutable commit** — your in-progress change; file edits are snapshotted here automatically | — |
| `feat@origin` | Exported git ref after `jj git push` | **The open PR** |

Key distinctions:

- **No staging area.** There is no `git add`. Edits on disk are represented by mutable `@`; jj snapshots them before most commands (including push).
- **`jj describe -m`** sets or replaces the **message only**. It does not finalize file content the way `git commit` does.
- **`jj commit -m`** finalizes the current `@` into `@-` and opens a new empty `@` child — i.e. it **starts the next change**.
- **A PR tracks `feat@origin`, not local `@`.** After push, local `@` can be empty, off-tip, or divergent while the PR still shows the exported remote commit. Do not use `git status` alone to infer PR state — prefer `jj st`, `jj bookmark list`, and `jj diff` (see REFERENCE.md → Diagnostic recipes).
- **Publishing `@` is valid jj** but easy to misread. For agent PR work, **prefer `jj commit -m` before bookmark/push** unless you deliberately want the bookmark on mutable `@`.

Before `jj git push`, jj snapshots the working copy into `@`. The push exports whatever commit the bookmark points at. If the bookmark points at `@`, the PR can include current file state even when you never ran `jj commit`.

## When to use jj vs git (decision rules)

Apply in order.

1. **No `.jj/`, read-only task** → use git/gh as normal; do **not** init jj.
2. **No `.jj/`, about to make changes and you want jj here** → init colocation first
   (`jj git init --colocate && jj git fetch`), then drive the changes through jj.
   (Whether this is automatic or on-request is governed by your own config.)
3. **Repo has `.jj/` (colocated)** → drive *mutations* through jj (commit,
   rebase/restack, abandon, undo). Read-only `git log`/`diff`/`status` and `gh`
   for PRs/CI stay fine. The undo safety net only covers changes jj made.
4. **Single-branch PR or follow-up commit** → Workflows A/B below.
5. **Stack of dependent PRs** → Workflow C; restack onto advanced main → Workflow D;
   whole stack squash-merged, fetch left conflicts/twins → Workflow D2.
6. **Local state disagrees with the open PR** (divergent bookmark, empty `@`, WC
   drift) → Workflow E.
7. **Recovering from a bad operation** (wrong rebase/reset/squash/abandon, by you
   or by raw git) → Workflow F (`jj op log` + `jj undo`/`jj op restore`). The op
   log is also diagnostic — search for `describe`, `push`, `import git refs`.

## Agent-safety rules (always)

jj has interactive (TUI / `$EDITOR`) modes that **hang a non-interactive agent**.
Never use them. Always:

- `--no-pager` on anything that prints (`jj --no-pager log`, `jj --no-pager show`).
- `-m "..."` for messages (`jj commit -m`, `jj describe -m`). Never bare `jj describe`/`jj commit`.
- Avoid all `-i`/interactive forms: `jj split`, `jj squash -i`, `jj resolve`, `jj diff -i`.
- Diffs in familiar format: `jj --no-pager diff --git` (default jj diff is side-by-side, not `+/-` — that is normal, not corruption).
- After every mutation (`squash`/`rebase`/`abandon`/`restore`/`edit`) run `jj st` to confirm state.
- Reference commits by **change ID** (stable across rewrites), not commit SHA (changes on every edit). **Exception — divergence:** if `jj log` shows two+ commits sharing one change ID tagged `(divergent)`, the change ID is ambiguous and `jj abandon <change-id>` / `jj edit <change-id>` fail or hit the wrong copy. Operate on the specific commit **by SHA** until the divergence is resolved (see REFERENCE.md → Divergent changes).
- **To switch to / work on an existing branch, use `jj new <bookmark>`** (starts a child on its tip), **not `jj edit`**. `jj edit` tries to make `@` *be* that commit and rewrite it — on a pushed/shared bookmark that fails with `Error: Commit … is immutable` and sends you down a rabbit hole. Reserve `jj edit` for a *mutable* commit you own and mean to rewrite.
- **Before rebasing/rewriting a bookmark you did not author, verify ownership** (`gh pr view <n> --json author`, `git log -1 --format=%ae <tip>`). jj rebases another author's commits as frictionlessly as your own, and pushing the rewrite force-updates shared history. The "git/gh/teammates stay unaffected" property holds only while jj metadata stays local — it ends the moment you push a rewrite of a *shared* bookmark. When in doubt, stop and confirm before pushing.

### Pre-push checklist

```bash
jj git fetch
jj st                                    # only intentional changes?
jj --no-pager bookmark list              # bookmark on the commit you mean to push?
jj --no-pager log -r '<bookmark>' --no-graph  # target has a non-empty description?
jj --no-pager log -r 'trunk()..<bookmark>'    # expected topology?
jj --no-pager diff -f <bookmark>              # tip has expected file content?
```

## Setup: enable colocation in an existing repo

Run when you want jj in a repo that lacks `.jj/` (e.g. before mutating it):

```bash
jj git init --colocate        # run at repo root; adds .jj/ alongside .git/
jj git fetch                  # sync remote bookmarks (trunk(), etc.)
jj --no-pager log             # confirm; git is now in detached HEAD — this is NORMAL for jj, do not "fix" it
```

`.jj/` is auto-excluded from git. Disable later with `jj git colocation disable` if needed.

## Workflow A — single-branch PR

The most common path. One bookmark, one PR.

```bash
jj git fetch
jj new 'trunk()'                    # start on latest default branch
# ...edit files...
jj commit -m "feat: <description>"  # preferred for agents — finalizes change, opens empty @
jj bookmark create feat -r @-      # bookmark the commit you just made
jj git push --bookmark feat
gh pr create --base main --head feat --title "..." --body "..."
```

`jj commit` puts the work in `@-`; `@` is now an empty child. Bookmark `@-`, not `@`.

## Workflow B — follow-up commit on an existing PR

```bash
jj git fetch
jj new feat@origin                  # empty child on the PR tip — realigns local to remote
# ...edit files...
jj commit -m "address review feedback"
jj bookmark advance --to @- feat    # clean forward move from the named bookmark to @-
jj git push --bookmark feat
```

`jj new feat@origin` realigns **local** state to the PR tip; it does **not** change the remote until you push. **Warning:** any local-only WC drift not on `feat@origin` is discarded when you realign.

After `jj commit`, the new commit is `@-` and `@` is a fresh empty child — always
advance or move the bookmark to `@-`, not `@`.

**Do not run bare `jj bookmark advance` in agent workflows:** its default target is
`@`, so after `jj commit` it can advance the bookmark to the empty child. Use the
explicit bookmark name, e.g. `jj bookmark advance --to @- feat`.

`jj tug` is usually a user alias around bookmark movement, not a jj command to rely
on in agent instructions. Use `jj bookmark advance --to @- <bookmark>` for the clean
forward case. Keep `jj bookmark move <bookmark> --to @- --allow-backwards` for stale,
divergent, or otherwise non-forward recovery after verifying the target.

If you personally want implicit `jj bookmark advance` outside agent runs, protect
trunk/main with config like this, but agents should still use explicit bookmark names:

```toml
[revsets]
bookmark-advance-from = "heads(trunk()..to & bookmarks())"
```

## Workflow C — author a stack of dependent PRs

A stack of N dependent changes, one PR each. jj's biggest win: editing a commit
auto-rebases its descendants; no `--onto` SHA-threading.

```bash
jj git fetch
jj new 'trunk()'                    # start the stack on the latest default branch
# ...edit files for change 1...
jj commit -m "T1: <description>"    # finalize change 1, opens empty child
# ...edits for change 2...
jj commit -m "T2: <description>"
# ...edits for change 3...
jj commit -m "T3: <description>"    # prefer commit for the tip too (agent-safe)

jj --no-pager log -r 'trunk()..@'   # review the stack; note each change ID
```

> **Tip vs `describe`:** `jj describe -m` on the final stack item is acceptable
> only if you intentionally keep the bookmark on mutable `@`. For agent PR
> publication, `jj commit -m` before bookmarking/pushing is safer.

Name a bookmark per PR, then push. New bookmarks are auto-tracked on push:

```bash
jj bookmark create feat-1 -r <change1-id>
jj bookmark create feat-2 -r <change2-id>
jj bookmark create feat-3 -r @-
jj git push --bookmark feat-1 --bookmark feat-2 --bookmark feat-3
```

jj pushes via your existing git remote, so your auth/remote config is respected.
Open the PRs with `gh`; **each PR is based on the previous bookmark:**

```bash
gh pr create --base main   --head feat-1 --title "..." --body "..."
gh pr create --base feat-1 --head feat-2 --title "..." --body "..."
gh pr create --base feat-2 --head feat-3 --title "..." --body "..."
```

### Editing a commit mid-stack (the win)

To change T1 after the stack exists — descendants auto-rebase, bookmarks on
rewritten commits move with them, so you mostly just re-push:

```bash
jj new <change1-id>           # new child of T1 to hold the fix (preferred over `jj edit`)
# ...make the fix...
jj squash                     # fold the fix into T1; T2 and T3 auto-rebase on top
jj edit feat-3                # IMPORTANT: return @ to the tip (auto-abandons the now-empty scratch commit)
jj --no-pager log -r 'trunk()..@'   # verify topology — now shows T1, T2, T3
jj git push --bookmark feat-1 --bookmark feat-2 --bookmark feat-3   # force-updates the moved bookmarks
```

Why the `jj edit feat-3`: after `jj new <T1>` + `jj squash`, the working copy `@`
is left as an empty commit hanging off T1' — *not* on the path to the tip. Verified
behavior: `jj log -r 'trunk()..@'` then shows only `{T1', empty-@}` and **hides
T2'/T3'`, which looks like a truncated stack. `jj edit <tip-bookmark>` moves `@`
back to the tip and the stray empty commit auto-abandons. (Bookmarks/pushes are
correct regardless — this only fixes what the log shows.)

Bookmarks **do not** auto-advance when you add a *new* commit on top — advance the
explicit bookmark (`jj bookmark advance --to @- feat-3`) before pushing in that case.

## Workflow D — get your stack onto an advanced main (rebase, never merge)

Use this whenever `main` advances while you have an in-flight stack: your base PR
squash-merged, **or a sibling PR merged while your stack's base is still unmerged**,
or you just want the latest main under your branch. The answer is always to
**rebase the stack onto `trunk()`** (below) — never a merge commit. This replaces
the `git rebase --onto origin/main <parent-tip> <dep-branch>` ritual entirely.
Because jj tracks changes by change ID and can drop emptied commits, there are
**no duplicate-history conflict piles**; your not-yet-merged base commits replant
cleanly on top of the new main, and once they later merge `--skip-emptied` drops them.

> **Squash-merge caveat (the common case).** GitHub squash-merge collapses each PR
> into one commit with a *new* change ID, so jj cannot match your local incremental
> commits by lineage. `--skip-emptied` therefore does **not** drop them; they replant
> onto the new `main` with **spurious per-commit conflicts** against content `main`
> already contains (you will see `New conflicts appeared in N commits` and possibly
> `(divergent)` twins on the next `jj git fetch`). This is still far better than
> git's one giant duplicate-history pile, but it is **not** conflict-free. Do **not**
> `jj resolve` these — the work is already merged. When the *whole* stack has merged,
> see Workflow D2.

> **Do NOT merge main into your branch to "catch up"** (`jj new @ main@origin` /
> `git merge main`). It looks clean and conflict-free, but it buries a 2-parent merge
> commit *inside* your stack — which then forces a painful manual linearization later
> (`jj undo` + `jj rebase -s`) and makes `trunk()..@` misreport the stack. Rebase
> instead; `jj rebase -b @ --onto 'trunk()'` is almost always available, even when
> your base hasn't merged yet. If you genuinely need one specific upstream commit
> that isn't on your path, `jj duplicate <rev>` — still not a merge.

```bash
jj git fetch
jj rebase -b @ --onto 'trunk()' --skip-emptied   # rebase surviving stack; drop the local copy of the merged change
jj --no-pager log -r 'trunk()..@'                # confirm the merged change is gone and the rest rebased cleanly
jj git push --bookmark feat-2 --bookmark feat-3  # update the remaining PRs
```

**Then re-target the orphaned PR base on GitHub.** Dropping T1 locally does not
fix feat-2's PR, which still has `--base feat-1`. GitHub's auto-retarget on parent
merge is unreliable (depends on the repo's branch-deletion setting), so do it
explicitly — this is the other half of the pain the `--onto` ritual existed for:

```bash
gh pr edit feat-2 --base main      # the new bottom-of-stack PR now targets main
```

If `--skip-emptied` leaves a now-redundant change (content differed slightly from
the squash), abandon it explicitly: `jj abandon <change-id>` (descendants rebase
to its parent automatically). Verified: when T1's content matches the squash
commit, `--skip-emptied` drops it automatically with no leftover.

## Workflow D2 — recover after your whole stack squash-merged

Use when **every** PR in your stack has merged and `jj git fetch` left a mess:
*"Abandoned N commits" + "New conflicts appeared in N commits" + `(divergent)`
twins*, and the bookmarks it deleted map to PRs that are all merged. Per the
squash-merge caveat above, those conflicts are **spurious** — the content is
already in `main`. Do not `jj resolve` them; abandon the orphans instead.

1. **Confirm the PRs merged** — `gh pr list --state merged`. The fetch abandons by
   *reachability* (the deleted bookmarks), **not** by verifying content landed, so
   "the bookmark is gone" alone does not prove the work is in `main`.
2. **Gate before abandoning — verify content is actually in `main`.** A commit made
   locally *after* the last push to its PR never entered the squash. `jj new 'trunk()'`
   first (step 3), then spot-check one **substantive, non-docs** commit per surviving
   branch: confirm its files/symbols exist in the working tree (now = `main`). If yes,
   abandon is safe; if a source line is missing, that branch has unpushed work — keep it.
   Docs-only commits are low-signal; do not gate on them.
3. **Get a clean working copy now (non-destructive):**
   ```bash
   jj new 'trunk()'                              # empty @ on the new main; resume work here
   ```
4. **Preview the abandon set before running it.** Target by reachability from the
   merged heads' **commit SHAs** (change IDs are ambiguous under divergence, and the
   deleted bookmark names are conflicted `??` — neither works in a revset), bounded
   away from `main` and `@`, and confirm it touches *only* the merged stack:
   ```bash
   SET='(::(sha1|sha2|sha3|…)) ~ ::main@origin ~ ::@'
   jj --no-pager log -r "$SET" --no-graph -T '"x\n"' | wc -l          # sanity: expected count
   jj --no-pager log -r "$SET & bookmarks()"                          # MUST list only merged-stack bookmarks
   jj --no-pager log -r "$SET & (<keep-bookmark-1> | <keep-bookmark-2>)"  # MUST be empty — no leak
   jj abandon -r "$SET"                                               # deletes the orphans + their stale bookmarks
   ```
5. **Confirm clean:** `jj --no-pager log -r 'conflicts() | divergent()'` returns
   nothing. A lone straggler conflict head can survive if its SHA was not in the set —
   verify its content is in `main`, then `jj abandon <sha>` it too.

Reversible throughout: `jj op restore <op-id-before-the-abandon>` (find it in
`jj --no-pager op log`). Nothing here pushes, so it stays local until you choose to.

**Root cause to avoid next time:** pre-emptively rebasing the stack (`jj rebase -s …
--onto 'trunk()'`) *while sibling PRs are still merging* seeds the `(divergent)` twins
that the next fetch then re-rebases. On a stack that is squash-merging, prefer to just
`jj git fetch`, let it abandon what it can, then run this workflow — rather than
rebasing repeatedly mid-merge.

## Workflow E — realign local state with the PR tip

Use when local `@`, the bookmark, and GitHub disagree.

**Symptoms:**

- `jj bookmark list` shows ahead/behind or `(divergent)` on your bookmark
- `jj diff -f @` empty but `jj diff` large
- Same change ID, two commits — local empty, `bookmark@origin` full (see REFERENCE.md → Post-push divergent twin)
- `git status` shows modifications that are already on the PR

**Diagnostic bundle** (full detail in REFERENCE.md):

```bash
jj git fetch
jj st
jj --no-pager bookmark list
jj --no-pager log -r 'feat | feat@origin'
jj --no-pager diff -f @
jj --no-pager diff
jj --no-pager op log --limit 20
git diff --stat origin/feat          # cross-check only — do not triangulate jj state from this alone
```

**Fix — discard stale local divergence and resume from the PR:**

```bash
jj git fetch
jj new feat@origin                   # WARNING: drops local-only WC drift not on origin
jj st                                # confirm alignment
# ...make new edits per Workflow B...
```

For SHA-level cleanup when twins persist, see REFERENCE.md → Divergent changes.

## Workflow F — recover from a bad operation (universal safety net)

This is the benefit that applies in *every* colocated repo, regardless of stacks.

```bash
jj --no-pager op log          # find the operation just before the mistake (note its op id)
jj undo                       # reverse the most recent operation
# or jump the whole repo back to a known-good point:
jj op restore <op-id>
jj st                         # confirm
```

Recovers from a bad `jj rebase/squash/abandon`. It also recovers from a raw
`git reset`/rebase **provided jj had snapshotted the good state in an earlier
operation** (i.e. some `jj` command ran while the repo was in the state you want
back) — jj can only restore to operations it recorded.

**Diagnosis, not just undo:** search the op log for `describe` without a
subsequent `commit` before `git push` (PR may have content local `@` lacks),
`import git refs` (raw git mutation jj absorbed), or `push bookmark` (what was
actually exported).

> **About `trunk()`:** it resolves to the default bookmark of the `origin`/`upstream`
> remote (e.g. `main@origin`), so the examples work unchanged on repos whose default
> branch isn't `main`. It reflects the latest *fetched* position — always `jj git fetch`
> before rebasing onto it.

## Workflow G — parallel working copies (jj workspaces, not git worktree)

jj **does not support `git worktree`** (mixing is unsupported/untested). The native
replacement is a **workspace**: an extra working copy backed by the same repo, for
running a long build/test or a parallel agent while you keep working elsewhere.

```bash
jj workspace add /path/to/dir -r 'trunk()' --name build   # base it on trunk explicitly
# ...work/test in /path/to/dir using jj...
jj workspace list                                          # see all workspaces and their @
jj workspace forget build                                  # when done (then delete the dir)
```

Three verified, non-obvious facts (LLM training is thin here — trust these):

1. **`-r` is effectively required.** With no `-r`, the new workspace's `@` is created
   sharing the *parents of your current `@`* — i.e. a sibling of your in-progress work,
   **not** that work and **not** trunk. Pass `-r 'trunk()'` (or `-r <change-id>`) to base
   it where you mean.
2. **An added workspace is jj-only — it has `.jj/` but no `.git/`.** `git` and `gh`
   commands fail inside it (`fatal: not a git repository`). `jj git push` / `jj git fetch`
   **do** work there (they share the repo's git backend), but run `gh` PR commands from
   the **main colocated workspace**.
3. **Stale working copy.** Editing a workspace's commit from *another* workspace can mark
   it stale. The fix is `jj workspace update-stale` (run it in the stale workspace). jj
   often reconciles automatically on the next command; only act when it reports stale.

Place the workspace outside the main checkout; follow your team's path convention if you have one.

## Workflow H — IDE/editor that expects a checked-out branch (detached HEAD)

Colocated jj keeps git in **detached HEAD** (your working copy `@` is a jj commit git
can't name as a branch). Most tools don't care, but editors/extensions that key off the
*current branch* — notably VS Code's git UI and the GitHub Pull Requests extension —
decide "no branch is checked out" and fall back to read-only virtual diffs, where
language-server features (go-to-definition, find-references) silently stop working.

**Exception to the "don't `git checkout`" rule** — temporarily attach HEAD for IDE review only:

```bash
git checkout <branch>     # symbolic-ref HEAD -> the branch; no file changes if @ sits empty on its tip
# ...review the PR in the IDE; LSP + the PR extension now work...
jj git fetch && jj st     # any jj op re-detaches HEAD and re-snapshots — back to normal jj state
# if jj reports a stale working copy: jj workspace update-stale
```

This is **read-only IDE attach**, not a substitute for `jj new <bookmark>`. Never
`git commit` after checkout. Never use checkout to drive mutations — jj ops re-detach
HEAD immediately.

Caveats: the branch must already exist as a **local** git ref — i.e. a tracked bookmark
(`jj bookmark track <name> --remote=origin` first if it's remote-only). Don't run jj
commands mid-review; any jj operation re-detaches HEAD and undoes the attach (which is
exactly how you clean up afterward). `git checkout` fails if `@` has uncommitted changes —
commit them in jj first. (Wrapping the checkout + resync in a shell alias/function
makes this a one-liner; that's a per-user convenience, not required.)

## Reference

Full command table, revset primer, bookmark semantics, diagnostic recipes, conflict
handling, colocated + workspace gotchas, the git→jj habit map, and version pins:
see [REFERENCE.md](REFERENCE.md).
