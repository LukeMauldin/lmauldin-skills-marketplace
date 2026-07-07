# Bun 1.0/1.1/1.2/1.3 Runtime Reference for TypeScript

Verified against Bun release notes/docs on 2026-03-02.

Purpose: high-signal version context for LLM agents when Bun is relevant. This is not an exhaustive changelog.

## Release Snapshot

| Line | Release Date | Focus Areas | Practical Guidance |
|---|---|---|---|
| Bun 1.0 | 2023-09-08 | Stable launch of all-in-one runtime/toolchain | Baseline for Bun adoption context |
| Bun 1.1 | 2024-04-01 | Windows support maturity, compatibility and behavior fixes | Important migration behavior changes from 1.0 |
| Bun 1.2 | 2025-01-22 | Node compatibility push, Bun.s3/Bun.sql, lockfile changes | Big production ergonomics jump |
| Bun 1.3 | 2025-10-10 | Monorepo/workspace defaults, testing and compatibility expansion | Recommended Bun baseline for new guidance |

## Cross-Version Summary (What Changed That Matters Most)

- Bun runs `.ts`/`.tsx` directly, but runtime execution is not a substitute for static type-checking. Keep `tsc --noEmit` in CI.
- Node compatibility improved significantly in each release, but Bun's compatibility matrix is still the source of truth for current gaps.
- Package manager behavior changed materially across releases (`trustedDependencies`, lockfile migration, and newer-workspace isolated-install defaults).
- Test-runner and bundler capabilities improved rapidly, with notable behavior changes that can break assumptions during migration.

## Major New APIs and Behavior Changes by Version

## Bun 1.0 (2023-09-08)

### Runtime and Core API Signals

- Stable, production-ready Bun release.
- "All-in-one toolkit" framing became official: runtime + package manager + test runner + bundler.
- TS/JSX runtime execution emphasized (`.ts`, `.tsx`, `.jsx`) without extra transpiler tools.
- Bun-native runtime APIs highlighted for app code:
  - `Bun.file()`
  - `Bun.write()`
  - `Bun.serve()` (HTTP + WebSocket support)
- ESM/CJS interoperability positioned as built-in for mixed ecosystems.

### Compatibility and Platform Signals

- Bun positioned as a Node drop-in replacement, while explicitly noting perfect compatibility is not possible.
- Native Windows build launched as experimental in 1.0 era.

### Migration Notes

- Bun can replace many Node-era tooling pieces for execution, but keep TypeScript type-checking explicit.
- For Node-heavy internals, confirm compatibility against `bun.sh/docs/runtime/nodejs-compat`.

## Bun 1.1 (2024-04-01)

### Runtime and Node-Compat Additions

- `import.meta.env` support (aligned with tooling expectations from ecosystems like Vite).
- `node:http2` client support (not full server-side parity at this point).
- `Date.parse()` behavior moved closer to Node compatibility.
- Recursive `fs.readdir()` support added.

### Package Manager and Security Model Changes

- `trustedDependencies` model introduced for lifecycle script execution.
- New related commands/workflows:
  - `bun pm untrusted`
  - `bun pm trust`
  - `bun add --trust`
- `bun pm migrate` added for npm lock migration (`package-lock.json` -> `bun.lockb` in 1.1 context).

### Test and Build Changes

- `expect.extend()` custom matcher support in `bun:test`.
- Module mocking support expanded (ESM + CJS runtime-aware behavior).
- `bun build --compile` improved (including embedding `.node` addons).

### Behavior Changes to Watch

- `NODE_ENV` default changed to `undefined` to align with Node behavior.
- `import.meta.resolve()` moved to synchronous URL-style behavior.
- `Bun.$` changed to reject on non-zero subprocess exit codes.
- Conditional export selection behavior changed (`worker` condition no longer preferred as before).

## Bun 1.2 (2025-01-22)

### Major Runtime/Node-Compat Changes

- Compatibility strategy shifted to broader Node test-suite-driven validation.
- Added high-signal module support/progress:
  - `node:http2` server support
  - `node:dgram`
  - `node:cluster`
  - `node:v8` compatibility improvements
- Added Bun-native UDP API: `Bun.udpSocket()`.

### Major Bun APIs Added

- `Bun.s3` introduced for S3-compatible storage access.
- `Bun.sql` introduced as built-in Postgres client.

### Package Manager and Monorepo Changes

- Default lockfile format changed to text `bun.lock` (from binary `bun.lockb`).
- `.npmrc` support added.
- `bun run --filter` added for workspace script execution.
- Package management additions included:
  - `bun outdated`
  - `bun publish`
  - `bun patch`

### Test Runner and Bundler Changes

- Test/CI reporting additions:
  - JUnit reporter support
  - LCOV coverage output support
  - Inline snapshots support
- Bundler updates:
  - `bun build --format=cjs` support
  - HTML imports support
  - Changed ambiguous module detection (`"use strict"` can affect CJS detection in ambiguous cases)

### Behavior Changes to Watch

- `bun run` working-directory behavior changed to align better with package manager expectations.
- `Bun.build()` failure behavior and related CLI semantics changed in this line.

## Bun 1.3 (2025-10-10)

### Package Manager/Workspace Changes (High Impact)

- Dependency catalogs for monorepo version centralization (`catalog` / `catalog:` workflows).
- New Bun 1.3+ workspace projects default to isolated installs under current config defaults. Migrated or older repos may still be hoisted unless `bunfig.toml` opts into isolated installs.
- Expanded lockfile migration support from `yarn.lock` and `pnpm-lock.yaml`.
- Security-focused package manager additions:
  - Security Scanner API integration path
  - `minimumReleaseAge` policy in `bunfig.toml`
- New package-manager commands/workflows highlighted (for example `bun why`, interactive updates).

### Runtime and Node Compatibility Changes

- Initial `node:test` support.
- `node:vm` received substantial additions:
  - `vm.SourceTextModule`
  - `vm.SyntheticModule`
  - `vm.compileFunction`
  - `vm.Script` cachedData support
  - `vm.constants.DONT_CONTEXTIFY`
- `require.extensions` support noted.
- `worker_threads` compatibility expanded (`getEnvironmentData` / `setEnvironmentData`).
- `--no-addons` introduced to disable native addon loading at runtime.

### Test Runner Changes

- Added concurrency controls/features:
  - `test.concurrent`
  - `test.serial`
  - `--randomize` + `--seed`
- Added type-focused test helper `expectTypeOf()` patterns.
- CI strictness increased for `test.only()` and snapshot creation without explicit update flags.

### Developer Experience and TypeScript Defaults

- Default TS config guidance shifted toward `"module": "Preserve"` (from older defaults).
- `@types/bun` behavior improved for Node-vs-DOM type selection.

### Behavior Changes to Watch

- `Bun.serve()` option rename: `static` -> `routes`.
- Minifier changed to remove unused function/class expression names by default (`--keep-names` to preserve names).
- `bun test -t` behavior changed to error when no tests match filter.

## API/Feature Quick Lookup (First Seen)

| API / Feature | First Seen | Notes |
|---|---|---|
| `import.meta.env` | 1.1 | Ecosystem compatibility aliasing for env access |
| `trustedDependencies` + `bun pm trust/untrusted` | 1.1 | Lifecycle script security model |
| `bun pm migrate` | 1.1 | npm lock migration flow (1.1 context) |
| `Bun.s3` | 1.2 | Built-in S3-compatible API |
| `Bun.sql` | 1.2 | Built-in Postgres client |
| `Bun.udpSocket()` | 1.2 | Bun-native UDP API |
| `bun run --filter` | 1.2 | Workspace script orchestration |
| `bun.lock` text lockfile default | 1.2 | Replaced `bun.lockb` default |
| `node:test` initial support | 1.3 | Implemented via `bun:test` internals |
| `test.concurrent` / `test.serial` / `--randomize` | 1.3 | Test ordering and concurrency controls |
| `expectTypeOf()` in `bun:test` | 1.3 | Type assertions paired with `tsc --noEmit` |
| New workspaces default to isolated installs | 1.3 | Current defaults apply to new workspace setups; migrated repos may still be hoisted |
| Catalogs (`catalog`, `catalog:`) | 1.3 | Centralized monorepo dep versions |
| `minimumReleaseAge` | 1.3 | Supply-chain hardening control |

## LLM Usage Guidance

When a task touches Bun behavior, do not assume Node behavior is identical. Check:

1. Release-note section for the relevant Bun line in this file.
2. Current Bun docs page for the specific API/module (`runtime`, `test`, `pm`, `bundler`).
3. Compatibility matrix for exact Node module status before choosing Bun-only patterns.

If uncertain, prefer project-local validation commands and feature probing over assumptions.

## Primary Sources

- Bun 1.0: https://bun.sh/blog/bun-v1.0
- Bun 1.1: https://bun.sh/blog/bun-v1.1
- Bun 1.2: https://bun.sh/blog/bun-v1.2
- Bun 1.3: https://bun.sh/blog/release-notes/bun-v1.3.0
- Bun runtime TypeScript docs: https://bun.sh/docs/runtime/typescript
- Bun Node compatibility docs: https://bun.sh/docs/runtime/nodejs-compat
- Bun lockfile docs: https://bun.sh/docs/pm/lockfile
- Bun isolated installs docs: https://bun.sh/docs/pm/isolated-installs
- Bun test docs: https://bun.sh/docs/test
- Bun bundler docs: https://bun.sh/docs/bundler
- GitHub release tags:
  - https://github.com/oven-sh/bun/releases/tag/bun-v1.0.0
  - https://github.com/oven-sh/bun/releases/tag/bun-v1.1.0
  - https://github.com/oven-sh/bun/releases/tag/bun-v1.2.0
  - https://github.com/oven-sh/bun/releases/tag/bun-v1.3.0
