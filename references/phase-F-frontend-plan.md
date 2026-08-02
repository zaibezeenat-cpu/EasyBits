# Phase F — Frontend Implementation Plan (RIPER)

**Status:** RESEARCH complete, PLAN written. Not yet executed.
**Skills applied:** `/typescript-conventions`, `/vibe-proof`, `/ui-critique`,
`/ui-responsive`, `ui-ux-pro-max`, `design-principles`.

---

## 1. RESEARCH — measured, not assumed

### The build works (my earlier concern was wrong)

I had flagged that the frontend "may need a rewrite" because it imports
`@/components/ui/*` and I had not found a components directory. That was wrong —
it exists, and the project builds on the first attempt:

```
bun install   -> 10 packages, no errors
bun run build -> Compiled successfully in 6.2s, TypeScript passed, 9 routes
bunx tsc --noEmit -> clean
bun run lint  -> 0 errors, 6 warnings (all unused imports)
```

Stack: **Next.js 16.2.10 + Turbopack, React 19, Tailwind 3.4, bun 1.3.14.**

**Scope is therefore much smaller than feared: extend, do not rebuild.**

### What exists

| Area | State |
|---|---|
| Pages | 9 build: dashboard, batches, batches/[id], products, products/[id], quick-add, settings, taxonomy, templates |
| UI components | **only 3** — button, card, input |
| Design tokens | `accent #561491`, `accentSoft #F7A800` in `tailwind.config.ts` + `lib/designTokens.ts` |
| TS strict | `true` |
| API client | `lib/apiClient.ts`, typed methods |

### Gaps found

**Broken links — pages the dashboard already links to but do not exist:**
`/review-queue`, `/audit-log`, `/batches/new`, `/login`.

**Missing components** for the screens requested: table, dialog, switch/toggle,
select, badge, toast, skeleton.

**Backend endpoints that do not exist yet** (needed by the requested screens):
- brand official link — add/edit
- source priority — reorder
- `source_mode` setting — strict vs priority

**tsconfig gaps vs `/typescript-conventions`:** `noUncheckedIndexedAccess`,
`noImplicitOverride`, `exactOptionalPropertyTypes` are all unset.

**Auth is not wired into the frontend at all.** The backend now requires a
bearer token on every `/api/*` call; `apiClient.ts` sends none, so **every page
will 401 at runtime even though the build passes.** This is the single most
important finding — a green build hides it completely.

### Design system (from `ui-ux-pro-max`, with one deliberate override)

The generator recommended **"Data-Dense Dashboard"** — correct for this product
(tables, KPI cards, grid layout, maximum data visibility, WCAG AA).

It also recommended a blue palette (`#1E40AF`). **Overridden:** the dashboard
must match the live WoodMart store, so `#561491` / `#F7A800` stay. Its "Product
Demo + Features" pattern is a landing-page pattern and does not apply to an
internal tool.

Adopted from the skill: row highlighting on hover, tooltips, visible loading
states, no emoji icons (Lucide SVG only), `cursor-pointer` on interactives,
150–300ms transitions, focus rings, 4.5:1 contrast, `prefers-reduced-motion`.

---

## 2. PLAN — ordered by risk, highest first

### F0. Auth wiring — **do first, nothing works without it**
Login page + token storage + `Authorization: Bearer` on every request +
401 redirect. Without this every screen is dead on arrival.

### F1. Component foundation
`table`, `dialog`, `switch`, `select`, `badge`, `toast`, `skeleton` — built on
the existing token system, keyboard accessible, focus-visible rings.

### F2. Backend endpoints for the requested screens
- `PATCH /api/taxonomy/brands/{id}/official-site`
- `PATCH /api/sources/trusted-secondary/{id}` (priority)
- `GET|PUT /api/settings/source-mode` (`strict` | `priority`)
- `source_discovery.py` reads the mode

### F3. Taxonomy Manager
Brands table with inline **official link** editing; categories as a **parent →
child tree**; active toggles. Casing warning shown, because a wrong casing
creates a NEW brand in live WooCommerce.

### F4. Sources Manager
Priority reorder (up/down), active toggles, add/remove, and the **Strict vs
Priority** mode toggle with a plain-language explanation of the trade-off.

### F5. Missing pages
`/login`, `/review-queue`, `/audit-log`, `/batches/new`.

### F6. Responsive + a11y pass
375 / 768 / 1024 / 1440. Tables become cards on mobile; 44px touch targets;
sidebar collapses to bottom nav.

### F7. Verification gate
`bun run build` + `bunx tsc --noEmit` + `bun run lint` all zero, plus a manual
click-through against the running backend.

---

## 3. Decisions needed before EXECUTE

1. **Default source mode** — recommendation: **strict** (only configured
   sources; anything else escalates). It matches the no-guess principle the rest
   of the system is built on. Toggle ships either way.
2. **Categories** — tree view (recommended) or flat list.
3. Turn on the three strict tsconfig flags now, or after the screens are built?
   Turning them on first is cheaper than retrofitting.

---

## 4. Verification

- Build, typecheck, lint — all must be zero.
- Every new interactive element: keyboard reachable, visible focus ring.
- No raw hex in components; tokens only.
- No horizontal scroll at 375px.
- Manual: log in, create batch, watch SSE progress, open QA panel, edit taxonomy,
  reorder sources, export CSV.
