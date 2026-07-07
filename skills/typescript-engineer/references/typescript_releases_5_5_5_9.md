# TypeScript 5.5-5.9 Release Reference

Verified on 2026-03-10 against official TypeScript release announcements, handbook release notes, and TSConfig reference pages.

Purpose: decision-useful context for Node CLI scripts, Node services/libraries, and modern browser apps. This is not an exhaustive changelog. Operational baseline for this skill: TypeScript 5.9+.

## Stable Release Timeline

| Version | Stable release date | Announcement |
|---|---|---|
| 5.5 | 2024-06-20 | https://devblogs.microsoft.com/typescript/announcing-typescript-5-5/ |
| 5.6 | 2024-09-09 | https://devblogs.microsoft.com/typescript/announcing-typescript-5-6/ |
| 5.7 | 2024-11-22 | https://devblogs.microsoft.com/typescript/announcing-typescript-5-7/ |
| 5.8 | 2025-02-28 | https://devblogs.microsoft.com/typescript/announcing-typescript-5-8/ |
| 5.9 | 2025-08-01 | https://devblogs.microsoft.com/typescript/announcing-typescript-5-9/ |

## TypeScript 5.5 (2024-06-20)

Release notes: https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-5.html

- Type-system narrowing got stricter and more useful with inferred type predicates and control-flow narrowing for constant indexed accesses.
- `isolatedDeclarations` landed to enforce export annotations that allow simpler, faster declaration generation tooling.
- `"${configDir}"` was added for shared `tsconfig` portability in multi-project repos.
- Declaration emit became more practical for library code by consulting `package.json` dependencies when generating declaration imports.
- Compiler API and tooling-oriented changes included easier ESM consumption of the `typescript` package and the new `transpileDeclaration` API.
- Migration-sensitive behavior changes included stricter decorator parsing, `undefined` no longer being a definable type name, and simplified reference directive declaration emit.

## TypeScript 5.6 (2024-09-09)

Release notes: https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-6.html

- New correctness diagnostics catch always-truthy/always-nullish condition bugs earlier.
- `--noUncheckedSideEffectImports` can turn unresolved side-effect imports into errors (important for catching typos; may require wildcard ambient modules for asset imports).
- `--noCheck` enables emit-first workflows, with separate full type-check phases (`tsc --noEmit`) when needed.
- `tsc -b` now continues across intermediate dependency errors by default; `--stopOnBuildErrors` restores fail-fast behavior.
- `.tsbuildinfo` is now always written in `--build` mode, even without `--incremental`.
- Module format resolution became safer in mixed ecosystems: TypeScript now consults `.mjs`/`.cjs` and `package.json` `"type"` in `node_modules` across module modes (except `amd`/`umd`/`system`).

## TypeScript 5.7 (2024-11-22)

Release notes: https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-7.html

- Added checks for never-initialized variables in additional closure/function scenarios.
- Added `--rewriteRelativeImportExtensions` to rewrite relative `.ts/.tsx/.mts/.cts` imports to JS extensions in emitted files.
- Added `--target es2024` and `--lib es2024` support, including updated typed-array typing implications.
- `--module nodenext` JSON imports now require import attributes (`with { type: "json" }`) and enforce safer access patterns.
- Editor/project ownership behavior changed: tsserver now searches ancestor `tsconfig.json` files and improves ownership checks for composite projects.
- TypeScript CLI startup can benefit from Node 22 compile caching (`module.enableCompileCache()`) in supported environments.

## TypeScript 5.8 (2025-02-28)

Release notes: https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-8.html

- Return-expression checking became more granular for branch expressions, reducing missed issues when `any` contaminates one branch.
- `--module nodenext` now supports Node's `require()` of ESM behavior.
- Stable `--module node18` was added as a non-floating Node mode.
- `--erasableSyntaxOnly` was added to enforce syntax compatible with erase-only runtime TypeScript execution.
- `--libReplacement` was added so projects can disable `@typescript/lib-*` package lookup overhead when unused.
- Declaration emit preserves computed property names more consistently.
- Under `--module nodenext`, import assertions (`assert`) are rejected in favor of import attributes (`with`).

## TypeScript 5.9 (2025-08-01)

Release notes: https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-9.html

- `tsc --init` now generates a smaller, more prescriptive baseline config (including strictness and module-related defaults).
- Added `import defer` support (namespace form only), with no downlevel transform by TypeScript.
- Added stable `--module node20` for a fixed Node 20 model; unlike `nodenext`, it does not float with newer Node semantics.
- Type argument inference changes can introduce new errors in generic-heavy code; explicit type arguments are the primary remediation.
- `lib.d.ts` updates changed `ArrayBuffer`/typed-array relationships and can surface new `Buffer` and `BufferSource` errors in Node/browser boundary code.
- Language-service improvements include expandable hovers, configurable hover length, and performance optimizations.

## Use-Case Implications (Inference)

- `Inference (Node CLI scripts)`: combining `--rewriteRelativeImportExtensions` (5.7) with `--erasableSyntaxOnly` (5.8) reduces mismatch risk between "run `.ts` directly" development and emitted JS distribution.
- `Inference (Node services/libraries)`: `--module node20` (5.9) is the safer fixed target when you want stable semantics; `nodenext` remains useful when you intentionally track latest Node module behavior.
- `Inference (modern browser apps)`: enabling `--noUncheckedSideEffectImports` (5.6) is high-value for typo detection, but teams importing CSS/assets via side-effect imports should add explicit ambient module declarations.
- `Inference (skill baseline)`: because `--module node20` lands in 5.9, a skill that recommends it as a standard preset should set its baseline to 5.9+ instead of claiming 5.8 compatibility.

## First-Seen Lookup (Compact)

| Option/Behavior | First seen | Why it matters |
|---|---|---|
| Inferred type predicates | 5.5 | Better narrowing through `filter`-style predicates. |
| Control-flow narrowing for constant indexed access | 5.5 | Fewer false positives on `obj[key]` checks. |
| `isolatedDeclarations` | 5.5 | Faster/simpler declaration generation workflows. |
| `${configDir}` in `tsconfig` | 5.5 | Shareable base configs in monorepos. |
| `transpileDeclaration` API | 5.5 | Single-file declaration emit for tooling pipelines. |
| `--noUncheckedSideEffectImports` | 5.6 | Catches unresolved side-effect imports. |
| `--noCheck` | 5.6 | Split emit and type-check phases in CI/dev loops. |
| `tsc -b` continues with intermediate errors | 5.6 | Unblocks downstream project migration work. |
| Node format detection in `node_modules` across module modes | 5.6 | Safer ESM/CJS interop in Node and bundler builds. |
| `--rewriteRelativeImportExtensions` | 5.7 | Enables TS-in-source imports with JS output paths. |
| `--target es2024` / `--lib es2024` | 5.7 | Aligns types with newer JS runtime APIs. |
| JSON import validation in `--module nodenext` | 5.7 | Prevents runtime JSON import mismatches. |
| `--module node18` | 5.8 | Stable Node 18 module semantics. |
| `require(ESM)` support in `--module nodenext` | 5.8 | Better CJS-to-ESM interop for Node-oriented codebases. |
| `--erasableSyntaxOnly` | 5.8 | Guardrail for runtime type-stripping compatibility. |
| `--libReplacement` | 5.8 | Avoid unnecessary `@typescript/lib-*` lookup/watch overhead. |
| `--module node20` | 5.9 | Stable Node 20 module model (`nodenext` alternative). |
| `import defer` | 5.9 | Deferred module evaluation for startup/side-effect control. |
| Type argument inference leak fixes | 5.9 | May introduce new generic inference errors. |
| `ArrayBuffer`/typed-array `lib.d.ts` relationship change | 5.9 | New assignability errors at Node/browser binary boundaries. |

## Primary Sources

- https://devblogs.microsoft.com/typescript/announcing-typescript-5-5/
- https://devblogs.microsoft.com/typescript/announcing-typescript-5-6/
- https://devblogs.microsoft.com/typescript/announcing-typescript-5-7/
- https://devblogs.microsoft.com/typescript/announcing-typescript-5-8/
- https://devblogs.microsoft.com/typescript/announcing-typescript-5-9/
- https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-5.html
- https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-6.html
- https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-7.html
- https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-8.html
- https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-9.html
- https://www.typescriptlang.org/tsconfig/isolatedDeclarations.html
- https://www.typescriptlang.org/tsconfig/noCheck.html
- https://www.typescriptlang.org/tsconfig/noUncheckedSideEffectImports.html
- https://www.typescriptlang.org/tsconfig/rewriteRelativeImportExtensions.html
- https://www.typescriptlang.org/tsconfig/erasableSyntaxOnly.html
- https://www.typescriptlang.org/tsconfig/libReplacement.html
- https://www.typescriptlang.org/tsconfig/module.html
