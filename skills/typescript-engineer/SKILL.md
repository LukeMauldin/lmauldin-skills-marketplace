---
name: typescript-engineer
description: TypeScript best practices for Node.js 24+ and modern browser apps (around Chrome 142). Use when writing TS for CLI scripts, services, libraries, or frontend web apps.
---

# TypeScript Engineer

Target: TypeScript 5.9+ on Node.js 24+.

Production baseline: Node 24 Active LTS.
Forward-compat baseline: keep Node 25 compatibility in CI.

**Tooling**:
- If `.nvmrc` exists, run `nvm use` before Node/TypeScript commands.
- Repo signals override this skill's defaults. Detect existing Node version, package manager, test runner, and module mode before introducing new tooling.
- Resolve Node version in this order: existing version-manager files (`.nvmrc`, `.node-version`, Volta, mise, asdf), `package.json` `engines.node`, CI/Docker/deployment config, then contributor docs/scripts. Only default to Node `24` when none exist.
- Resolve package manager in this order: `package.json` `packageManager`, existing lockfile, workspace/CI/docs, then Bun signals (`bun.lock`, `bunfig.toml`). Only default to `pnpm` when none exist.
- Keep Node `25` as a forward-compat CI lane; do not promote it to the primary dev/runtime baseline unless the project explicitly targets it.
- In Bun repositories, use Bun-native commands (`bun install`, `bun run`, `bunx`) instead of `pnpm`.
- Preserve the repo's existing package manager and lockfile. Do not introduce a second lockfile or switch package managers unless the repo is already migrating.
- For one-off CLI execution, use the repo-native executor: `pnpm dlx` in pnpm repos, `npm exec`/`npx` in npm repos, `yarn dlx` in Yarn repos, and `bunx` in Bun repos. Only default to `pnpm dlx` when this skill also defaulted the repo to pnpm.

## Included Resources

- [Node.js 22/23/24/25 Runtime Reference](references/node_runtime_22_23_24_25.md)
- [Bun 1.0/1.1/1.2/1.3 Runtime Reference](references/bun_runtime_1_0_1_1_1_2_1_3.md)
- [Browser Target Reference (Chrome 142)](references/browser_target_chrome_142.md)
- [TypeScript Config Presets](references/tsconfig_presets.md)
- [TypeScript 5.5-5.9 Release Reference](references/typescript_releases_5_5_5_9.md)

## Context Detection

**Node CLI script** (default for one-off tools): single-file or small utility run from terminal.
**Node application/library**: multiple modules, package boundaries, tests, and CI.
**Frontend web application**: browser-targeted code (React/Vue/Svelte/vanilla) with DOM/event/rendering concerns.
**Isomorphic/shared package**: consumed by both Node and browser bundles.
**Bun repository**: Bun runtime/package-manager signals are present (`bun.lock`, `bunfig.toml`, Bun-specific scripts/docs/CI).

Signs of frontend context:
- `vite.config.*`, `webpack.config.*`, `next.config.*`, or `astro.config.*`
- `src/main.ts(x)`, `index.html`, or framework component files
- DOM APIs (`document`, `window`, `HTMLElement`) in primary paths

Signs of Bun context:
- `bun.lock` or historical `bun.lockb`
- `bunfig.toml`
- `bun run`, `bun test`, or `bunx` in scripts, docs, or CI

Use minimal ceremony for scripts and stronger API boundary typing for apps/libraries.

## Type System Defaults

- Keep `strict: true`.
- Prefer `unknown` at untrusted boundaries; narrow with type guards.
- Avoid `any`; if unavoidable, isolate it and document why.
- Add explicit return types on exported functions.
- Prefer discriminated unions over boolean-flag bundles.
- Prefer `readonly` for data that should not mutate.
- Use `type` for unions/intersections/mapped types.
- Use `interface` for object contracts intended to be extended/implemented.
- Use `satisfies` for config literals instead of broad `as` casts.
- Prefer `as const` objects + union types over `enum` for most app code.
- Treat non-null assertions (`!`) as a last resort.

## Node CLI Script Structure (TypeScript)

This example assumes ESM module semantics. If the package is not `"type": "module"`, use `.mts` for direct runtime execution or compile first.

```ts
import { parseArgs } from 'node:util';
import process from 'node:process';

type CliOptions = {
  readonly verbose: boolean;
  readonly dryRun: boolean;
};

function parseCli(argv: readonly string[]): {
  readonly options: CliOptions;
  readonly positionals: readonly string[];
} {
  const { values, positionals } = parseArgs({
    args: [...argv],
    options: {
      verbose: { type: 'boolean', short: 'v', default: false },
      dryRun: { type: 'boolean', default: false },
    },
    allowPositionals: true,
  });

  return {
    options: {
      verbose: values.verbose,
      dryRun: values.dryRun,
    },
    positionals,
  };
}

export async function main(argv: readonly string[]): Promise<number> {
  const { options, positionals } = parseCli(argv);
  if (options.verbose) {
    console.error('debug: argv=%o', positionals);
  }

  // Core logic
  return 0;
}

if (import.meta.main) {
  main(process.argv.slice(2)).then(
    (code) => {
      process.exitCode = code;
    },
    (error: unknown) => {
      console.error(error);
      process.exitCode = 1;
    },
  );
}
```

### CLI Execution Modes

- `node script.ts`: use when code uses erasable TypeScript only.
- `tsx script.ts` (or `node --import=tsx script.ts`): use when syntax requires transforms (`enum`, decorators, TS emit transforms).
- Use the repo-native executor for ad hoc `tsx` runs when `tsx` is not already a project dependency (`pnpm dlx tsx`, `npm exec tsx`, `yarn dlx tsx`, or `bunx tsx`).
- For runtime TS on Node, keep explicit local import extensions (`./file.ts`, `./file.mts`, `./file.cts`) for relative local imports only.
- `.ts` files follow normal Node module detection rules. Check `package.json` `"type"` and file extensions before assuming ESM syntax or `import.meta.main` will run.
- In runtime-TS files, use `import type` / `export type` for type-only symbols so Node does not try to load them at runtime.
- Do not rely on direct runtime TS plus emitted JS staying aligned when the repo uses `.tsx`, `paths` aliases, or package `imports`/`exports` indirection. Node ignores `tsconfig.json` at runtime, and TypeScript does not rewrite alias-based specifiers or package subpath mappings during emit. Compile to JavaScript with an explicit mapping strategy for those cases and for published packages.

## Execution Mode Selection

| Choose this mode | Use when | Avoid when |
|---|---|---|
| Direct runtime TS in Node | Repo-internal scripts/tools, plain relative imports, no publish/deploy artifact needed | Published packages, alias-heavy code, `.tsx`, package subpath remapping, mixed-runtime consumers |
| Compile TS to JS | Services, libraries, deploy artifacts, published packages, any code using aliases or package boundary indirection | Throwaway local scripts where runtime TS is simpler |
| Bun runtime TS | Bun-signaled repos that already execute with Bun | Node-first repos without Bun runtime/package-manager signals |

## Node App and Library Guidance

- Default to ESM for new packages (`"type": "module"`), unless a project constraint requires CJS.
- Choose `NodeNext` when the repo wants current Node module semantics; choose `Node20` only when the repo explicitly wants a fixed compatibility target.
- If supporting both ESM and CJS, expose explicit entry points instead of implicit dual-mode behavior.
- For published packages, ship JavaScript + declaration files. Do not publish raw `.ts` for consumers.
- Keep I/O, process env, and network access at boundaries; keep domain logic pure and testable.
- Prefer native platform APIs first (`fetch`, `AbortController`, `URL`, `node:test` in new Node-only repos) before adding dependencies.

### ESM/CJS Checklist

- Inspect `package.json` `"type"` before choosing import/export syntax or file extensions.
- Use `.mts`/`.cts` only when the repo needs per-file module-mode overrides; otherwise keep `.ts` with a package-level module policy.
- For published packages, prefer explicit `exports` maps over relying on legacy resolution side effects.
- If consumers still require CJS, plan separate outputs or entry points instead of assuming dual-mode source will work everywhere.
- `.ts` import specifiers plus `rewriteRelativeImportExtensions` only solve relative local imports in emitted files; they do not rewrite alias-based imports, `paths`, or `package.json` `imports`/`exports` mappings.

## Frontend Web App Guidance (Modern Browsers)

- Before applying the Chrome 142 baseline, check existing browser support policy (`browserslist`, framework build targets, Babel/SWC targets, and browser-test CI). Repo/browser requirements override this skill's default browser baseline.
- Treat browser input and API payloads as `unknown`; parse/validate at boundaries.
- Keep render components small; move async/data orchestration into hooks/services.
- Type event handlers explicitly when inference is weak (`SubmitEvent`, `MouseEvent`, keyboard events).
- Use `AbortController` for cancellable requests tied to component lifecycle.
- Prefer progressive enhancement over broad polyfills when the product's browser support policy is otherwise unspecified and modern browsers are acceptable.
- Keep shared types in dedicated modules; avoid leaking server-only types into browser bundles.

## Testing Defaults

- New Node-only repositories: prefer built-in `node:test` + `node:assert/strict`.
- Existing repositories: use the established test runner and conventions (`vitest`, `jest`, `bun test`, `playwright`, etc.).
- Frontend code: use the existing framework setup (`vitest`, `jest`, `playwright`, etc.).
- Test parsing, validation, and domain invariants first; snapshots are secondary.

## Error Handling and Async

- Throw `Error` instances or `Error` subclasses at boundaries. If machine-readable handling is needed, add a stable `code` or tag field instead of throwing bare object literals.
- Never silently swallow promise rejections.
- Use `Promise.allSettled()` when partial success is valid; otherwise use `Promise.all()`.
- Preserve original causes with `new Error("message", { cause })` when wrapping.

## Monorepo and TSConfig Heuristics

- In monorepos, preserve the existing `tsconfig` layering before introducing new defaults.
- Prefer extending the repo's base config over inventing a new root TypeScript policy.
- Add project references only when the repo already uses composite builds or when package-level incremental boundaries are an explicit requirement.

## Version Notes

- TypeScript baseline: 5.9+.
- Node 24 is the production baseline (Active LTS).
- Node 25 is useful for forward-compat checks; run CI on both 24.x and 25.x when practical.
- Read [TypeScript 5.5-5.9 Release Reference](references/typescript_releases_5_5_5_9.md) before choosing module mode/emit settings (`node20`, `nodenext`, `rewriteRelativeImportExtensions`, `erasableSyntaxOnly`).
- Read [Node.js 22/23/24/25 Runtime Reference](references/node_runtime_22_23_24_25.md) before relying on runtime TypeScript, ESM/CJS interop edge behavior, or permission-model flags.
- Read [Bun 1.0/1.1/1.2/1.3 Runtime Reference](references/bun_runtime_1_0_1_1_1_2_1_3.md) before assuming Node and Bun behavior are interchangeable.
