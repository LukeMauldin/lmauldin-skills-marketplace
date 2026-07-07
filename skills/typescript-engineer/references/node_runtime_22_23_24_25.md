# Node.js 22/23/24/25 Runtime Reference for TypeScript

Verified on 2026-03-10 against official Node.js release/docs pages.

Patch versions and release-page timestamps are volatile. Re-check the official releases page before using exact latest-version numbers in tooling or CI guidance.
If you update the verification date, refresh every "Last updated" value in the release snapshot table from the official releases page in the same edit.

## Release Channel Snapshot (2026-03-10)

| Line | First released | Last updated | Status | Decision-useful guidance |
|---|---|---|---|---|
| Node 22 (`Jod`) | 2024-04-24 | 2026-01-12 | Maintenance LTS | Keep only for compatibility support |
| Node 23 | 2024-10-16 | 2025-05-14 | End-of-life (EoL) | Do not target |
| Node 24 (`Krypton`) | 2025-05-06 | 2026-02-24 | Active LTS | Default production baseline |
| Node 25 | 2025-10-15 | 2026-02-24 | Current | Forward-compat CI lane; verify the latest patch before pinning |

`Inference`: with Node 23 EoL and Node 24 Active LTS, defaulting production to Node 24 minimizes risk.

## Major Milestones by Line

### Node 22 (`Jod`) - first release 2024-04-24

- `v22.0.0` introduced `require()` support for synchronous ESM graphs, built-in WebSocket by default, `node --run`, stable watch mode, and `fs.glob()/globSync()`.
- `v22.6.0` introduced runtime TS type stripping (`--experimental-strip-types` at introduction).
- `v22.7.0` added `--experimental-transform-types`.
- `v22.12.0` removed the `--experimental-require-module` gate for `require(esm)` in this line.
- `v22.13.0` marked Permission Model as no longer experimental.
- `v22.18.0` enabled type stripping by default and removed the experimental warning in 22.x docs (still `Stability: 1.2` in latest 22.x TS docs).

### Node 23 - first release 2024-10-16, EoL

- `v23.0.0` highlights: `require(esm)` enabled by default, `node --run` stabilized, and test-runner coverage glob improvements.
- `v23.5.0` marked Permission Model as no longer experimental.
- `v23.6.0` enabled TS type stripping by default.
- Release status page lists this line as EoL (last updated 2025-05-14).

### Node 24 (`Krypton`) - first release 2025-05-06, Active LTS

- `v24.0.0` highlights: V8 13.6, npm 11, global `URLPattern`, Permission Model CLI shift from `--experimental-permission` to `--permission`, `node:test` subtest behavior change, and migration-relevant deprecations/removals (`url.parse()` runtime deprecation transition; `tls.createSecurePair` removal callout).
- `v24.11.0` became LTS on 2025-10-28 (`Krypton`), with support through end of 2028-04.
- TS docs milestones on 24.x: warning removed at `v24.3.0`; type stripping stable at `v24.12.0`.
- CLI added `--allow-inspector` in `v24.12.0`.
- `node:test` docs show `run({ env })` at `v24.14.0`; `Expecting tests to fail` also appears in `v24.14.0`.
  - `Inference`: update startup scripts/CI from `--experimental-permission` to `--permission` when moving to 24+.

### Node 25 - first release 2025-10-15, Current

- `v25.0.0` highlights: V8 14.1, global `ErrorEvent`, Web Storage enabled by default, Permission Model adds `--allow-net` and `--allow-inspector`.
- `v25.0.0` semver-major release notes include `build: stop distributing Corepack`.
  - `Inference`: for Yarn/pnpm flows on Node 25+, bootstrap package-manager tooling explicitly in CI/dev setup instead of assuming bundled Corepack.
- `require(esm)` is marked no longer experimental at `v25.4.0`; CLI also reflects `--no-require-module` naming.
- TS docs: type stripping stable at `v25.2.0` (`Stability: 2`).
- CLI additions include `--build-sea=config` (`v25.5.0`).
- `node:test` docs show `context.attempt` added in `v25.0.0` and `run({ env })` at `v25.6.0`.

## Cross-Line Implementation Notes

### Runtime TypeScript

- Timeline from docs:
  - `v22.6.0`: type stripping added.
  - `v22.7.0`: `--experimental-transform-types` added.
  - `v22.18.0`, `v23.6.0`: type stripping enabled by default.
  - `v22.18.0`, `v24.3.0`: experimental warning removed.
  - `v24.12.0`, `v25.2.0`: type stripping marked stable.
- Constraints that remain relevant across these lines:
  - Node runtime TS does not use `tsconfig.json`.
  - `.tsx` is unsupported.
  - Type stripping in `node_modules` is disabled.
  - Explicit file extensions are required in imports/requires for TS execution.

### ESM/CJS Interop (`require(esm)`)

- `v22.0.0`: added.
- `v22.12.0`/`v23.0.0`: unflagged from `--experimental-require-module`.
- `v22.13.0`/`v23.5.0`: no warning by default (warning can still be forced via `--trace-require-module`).
- `v25.4.0`: no longer experimental.
- `require(esm)` only supports fully synchronous ESM graphs; top-level `await` in the target graph throws `ERR_REQUIRE_ASYNC_MODULE`.
- Runtime detection hook: `process.features.require_module`.

### Permissions

- Permission Model is stable (`Stability: 2`) in 22+/23+ docs after `v22.13.0`/`v23.5.0`.
- 24.x+ uses `--permission` (without the `experimental` prefix).
- Flag surface differs by line:
  - `--allow-inspector`: appears in 24.x at `v24.12.0`, and in 25.x at `v25.0.0`.
  - `--allow-net`: appears in 25.x at `v25.0.0`; absent from 22.x/24.x CLI docs.
- Docs explicitly describe this as not a malicious-code sandbox; treat as guardrails, not full isolation.

### Deprecation Transitions That Affect Migrations

- `DEP0169` (`url.parse()` insecure behavior):
  - 22.x/23.x docs: documentation-only deprecation.
  - 24.x+: application deprecation (non-`node_modules` code).
- `DEP0176` (`fs.F_OK`, `fs.R_OK`, `fs.W_OK`, `fs.X_OK` on `node:fs`):
  - 22.x/23.x: documentation-only deprecation.
  - 24.x: runtime deprecation.
  - 25.x: End-of-Life (removed from direct `fs` getters; use `fs.constants` / `fs.promises.constants`).

## First-Seen Lookup (Compact)

| API/Behavior | First seen in 22-25 context | Notes |
|---|---|---|
| Runtime TS type stripping | `v22.6.0` (2024-08-06) | Introduced as experimental |
| `--experimental-transform-types` | `v22.7.0` (2024-08-22) | Needed for non-erasable TS syntax |
| Type stripping enabled by default | `v22.18.0` / `v23.6.0` | Default execution path begins |
| Type stripping stable | `v24.12.0` / `v25.2.0` | `Stability: 2` in current 24/25 docs |
| `require(esm)` support in `require()` | `v22.0.0` (2024-04-24) | Initially release-candidate status |
| `require(esm)` unflagged | `v22.12.0` / `v23.0.0` | No `--experimental-require-module` gate |
| `require(esm)` no longer experimental | `v25.4.0` | Also reflected by `--no-require-module` |
| Permission Model no longer experimental | `v22.13.0` / `v23.5.0` | Stable model baseline in docs |
| Permission entry flag renamed to `--permission` | `v24.0.0` | Replaces `--experimental-permission` in startup scripts |
| `--allow-inspector` | `v24.12.0` | Present in 24.x+ CLI docs |
| `--allow-net` | `v25.0.0` | Present in 25.x CLI/permissions docs |
| Corepack no longer bundled with Node release binaries | `v25.0.0` | `Inference`: bootstrap package-manager tooling explicitly |
| `node:test` `run({ env })` | `v24.14.0` (24.x docs), `v25.6.0` (25.x docs) | Versioned-doc history differs by line |
| `node:test` `context.attempt` | `v25.0.0` | Added as retry-attempt signal |
| `node:test` `Expecting tests to fail` | `v24.14.0` (24.x docs), `v25.5.0` (25.x docs) | Versioned-doc history differs by line |

## Primary Sources

- Release status page:
  - https://nodejs.org/en/about/previous-releases
- Release posts:
  - https://nodejs.org/en/blog/release/v22.0.0
  - https://nodejs.org/en/blog/release/v22.6.0
  - https://nodejs.org/en/blog/release/v22.7.0
  - https://nodejs.org/en/blog/release/v22.12.0
  - https://nodejs.org/en/blog/release/v22.13.0
  - https://nodejs.org/en/blog/release/v22.18.0
  - https://nodejs.org/en/blog/release/v23.0.0
  - https://nodejs.org/en/blog/release/v23.5.0
  - https://nodejs.org/en/blog/release/v23.6.0
  - https://nodejs.org/en/blog/release/v24.0.0
  - https://nodejs.org/en/blog/release/v24.11.0
  - https://nodejs.org/en/blog/release/v25.0.0
- TypeScript runtime docs:
  - https://nodejs.org/download/release/latest-v22.x/docs/api/typescript.html
  - https://nodejs.org/download/release/v23.11.0/docs/api/typescript.html
  - https://nodejs.org/download/release/latest-v24.x/docs/api/typescript.html
  - https://nodejs.org/download/release/latest-v25.x/docs/api/typescript.html
- Modules / interop docs:
  - https://nodejs.org/download/release/latest-v22.x/docs/api/modules.html
  - https://nodejs.org/download/release/v23.11.0/docs/api/modules.html
  - https://nodejs.org/download/release/latest-v24.x/docs/api/modules.html
  - https://nodejs.org/download/release/latest-v25.x/docs/api/modules.html
- Permissions + CLI docs:
  - https://nodejs.org/download/release/latest-v22.x/docs/api/permissions.html
  - https://nodejs.org/download/release/v23.11.0/docs/api/permissions.html
  - https://nodejs.org/download/release/latest-v24.x/docs/api/permissions.html
  - https://nodejs.org/download/release/latest-v25.x/docs/api/permissions.html
  - https://nodejs.org/download/release/latest-v24.x/docs/api/cli.html
  - https://nodejs.org/download/release/latest-v25.x/docs/api/cli.html
- Test runner docs:
  - https://nodejs.org/download/release/latest-v22.x/docs/api/test.html
  - https://nodejs.org/download/release/latest-v24.x/docs/api/test.html
  - https://nodejs.org/download/release/latest-v25.x/docs/api/test.html
- Deprecation docs:
  - https://nodejs.org/download/release/latest-v22.x/docs/api/deprecations.html
  - https://nodejs.org/download/release/v23.11.0/docs/api/deprecations.html
  - https://nodejs.org/download/release/latest-v24.x/docs/api/deprecations.html
  - https://nodejs.org/download/release/latest-v25.x/docs/api/deprecations.html
