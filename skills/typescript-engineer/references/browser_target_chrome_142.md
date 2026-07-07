# Browser Target Reference (Chrome 142 Baseline)

Scope: frontend TypeScript intended for modern browsers around Chrome 142.

Verified on 2026-03-02 from Chrome 142 release notes.

## Baseline Assumption

- Chrome 142 stable release date: 2025-10-28.
- Treat this as a modern-web baseline where ESM-first architecture and minimal transpilation are usually viable.

Practical default:
- Prefer `target` around `ES2022` or newer for app bundles unless product requirements include older browsers.
- Avoid heavy polyfill bundles by default; add only what real compatibility requirements demand.

## Chrome 142 Changes Worth Noting for Frontend Engineering

From release notes and updates:
- Local network access restrictions for subresource requests from public websites.
- `pointerrawupdate` event support in secure contexts.
- CSS additions including range syntax for style container queries and `if()`.
- View transitions improvement via `document.activeViewTransition`.

Practical implications:
- If your app calls local-network devices/services from browser context, expect stricter behavior and plan for permission/UX handling.
- Features gated to secure contexts should be tested under HTTPS dev/prod parity.
- New CSS and transition APIs can simplify UI logic; keep fallbacks when cross-browser parity matters.

## TypeScript Frontend Defaults for This Baseline

- Use bundler-native module resolution (`moduleResolution: "Bundler"`).
- Keep `strict: true`, `noUncheckedIndexedAccess: true`, and `exactOptionalPropertyTypes: true`.
- Use DOM lib types (`"lib": ["DOM", "DOM.Iterable", "ES2023"]` or project equivalent).
- Prefer typed boundary validation for runtime data (`unknown` + parser/schema) instead of trusting API response shape.
- Keep browser-only types separate from server/shared modules where possible.

## When Not to Use This Baseline

Do not assume Chrome-142-only behavior if:
- The app must support Safari/Firefox versions with stricter constraints.
- The app ships as an embeddable widget in unknown host environments.
- Enterprise requirements enforce older browser versions.

In those cases, set explicit browser support policy first, then adjust transpile/polyfill strategy.

## Primary Sources

- https://developer.chrome.com/release-notes/142
- https://developer.chrome.com/blog/new-in-chrome-142
