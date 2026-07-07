# TypeScript Config Presets

Use these as starting points. Merge with project-specific requirements rather than forcing a full replacement.

Scope note: aligned with TypeScript 5.9+ guidance as of 2026-03-10.

## 1) Node Runtime TS (Direct `node *.ts`)

Use when executing repo-internal TypeScript scripts directly in Node 24+ with built-in type stripping.

```json
{
  "compilerOptions": {
    "target": "ESNext",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "allowImportingTsExtensions": true,
    "rewriteRelativeImportExtensions": true,
    "verbatimModuleSyntax": true,
    "erasableSyntaxOnly": true,
    "noEmit": true,
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "useUnknownInCatchVariables": true
  }
}
```

Notes:
- Mirrors Node docs guidance for runtime TS flows.
- `erasableSyntaxOnly` keeps code compatible with Node's built-in type stripping.
- Reserve this for local scripts/tools with relative local imports. Do not use it for published packages, `.tsx`, or code that depends on `paths` aliases or package subpath remapping.

## 2) Node App/Library (Modern Node, Runtime-Aligned)

Use when producing JavaScript artifacts for deployment or publishing and the repo wants current Node module semantics.

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "rootDir": "src",
    "outDir": "dist",
    "rewriteRelativeImportExtensions": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "useUnknownInCatchVariables": true,
    "noImplicitOverride": true
  },
  "include": ["src/**/*.ts"]
}
```

Notes:
- Suitable for Node 24+ services and libraries that want TypeScript to follow current Node behavior.
- Choose this when the repo already targets modern Node and does not need a fixed older compatibility model.
- For dual ESM/CJS support, use explicit export maps and separate outputs.
- `rewriteRelativeImportExtensions` only rewrites relative local `.ts/.mts/.cts/.tsx` specifiers. It does not rewrite aliases, package subpaths, or `paths` mappings.

## 3) Node App/Library (Fixed Compatibility Target)

Use when producing JavaScript artifacts and the repo explicitly wants a stable compatibility model instead of following future Node module behavior.

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "Node20",
    "rootDir": "src",
    "outDir": "dist",
    "rewriteRelativeImportExtensions": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "useUnknownInCatchVariables": true,
    "noImplicitOverride": true
  },
  "include": ["src/**/*.ts"]
}
```

Notes:
- `module: "Node20"` requires TypeScript 5.9+.
- Choose this only when the repo must hold a fixed Node 20 compatibility model for consumers or tooling.
- Do not override module resolution unless the repo already has a proven need; let the compiler apply the matching Node-mode defaults.
- `rewriteRelativeImportExtensions` only handles relative local specifiers in emitted output.

## 4) Bun Runtime TS

Use when the repository already executes TypeScript with Bun (`bun.lock`, `bunfig.toml`, Bun scripts/CI).

```json
{
  "compilerOptions": {
    "target": "ESNext",
    "module": "Preserve",
    "moduleResolution": "Bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "noEmit": true,
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "useUnknownInCatchVariables": true
  }
}
```

Notes:
- Bun can execute `.ts` and `.tsx` directly, but keep `tsc --noEmit` in CI because runtime execution is not a substitute for type-checking.
- Prefer Bun-native commands and resolution behavior only in Bun-signaled repos.
- Validate Node-compat assumptions against the Bun compatibility docs before using Node-specific internals.

## 5) Frontend App (Modern Browser + Bundler)

Use when targeting modern browsers around Chrome 142 with Vite/Webpack/Rspack/esbuild pipelines.

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "lib": ["DOM", "DOM.Iterable", "ES2023"],
    "jsx": "react-jsx",
    "useDefineForClassFields": true,
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "allowJs": false,
    "isolatedModules": true,
    "noEmit": true
  },
  "include": ["src"]
}
```

Notes:
- Keep transpilation minimal by default for modern browser targets.
- Consider enabling `noUncheckedSideEffectImports` once asset-module declarations (for example `declare module "*.css" {}`) are in place.
- If supporting older browsers, lower `target` and add explicit polyfill/transpile policy.
