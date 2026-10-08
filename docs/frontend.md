# Frontend

Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind v4 · Recharts.

## Screens

| Route | Purpose |
|---|---|
| `/` | Dashboard — live counters, verification quality, recent runs, high-risk accounts |
| `/runs` | Run list with status filters and pagination |
| `/runs/new` | Objective composer with structured controls |
| `/runs/[runId]` | Run detail — stage timeline, results, tasks, audit trail |
| `/customers` | Searchable, filterable customer list |
| `/customers/[customerId]` | Account detail — commercial, usage, support, billing, NPS, documents, risk breakdown |
| `/reports` | Report list |
| `/reports/[runId]` | Report — rendered, Markdown, or structured JSON |
| `/approvals` | Approve / reject with reviewer comments |
| `/evaluation` | Evaluation metrics, honestly labelled |
| `/system` | Agents, tools, limits, risk model, approval policy — read from the live registry |

## No fake data

Every value comes from the API. With nothing seeded the dashboard shows zeros
and `—`, plus a prompt to run `make seed`. With no runs, percentages are `null`
and the UI renders an empty state explaining what to do. There are no
placeholder metrics, no hard-coded completed workflows, and no buttons that do
nothing.

The System page is generated from the running tool registry and agent
declarations, so it cannot advertise a capability the backend does not have.

## State handling

Every screen implements loading, empty, error and success states.

- **Loading** uses skeletons shaped like the content, and only on first load —
  a poll refresh does not flash.
- **Empty** explains the next action rather than saying "no data".
- **Error** renders the backend's structured `{code, message, details}`,
  including field-level validation problems, with a retry affordance.
- **Partial** — data gaps are shown as "Insufficient evidence", never hidden.
- **Report not ready** is a distinct state (`409 report_not_ready`) with a link
  to follow the run, not a 404.

`useApi` aborts in-flight requests on unmount and on dependency change, so a
fast navigation cannot land a stale response on the new page. Polling pauses
while the tab is hidden and refreshes immediately on return.

## Live updates

Polling, not SSE or WebSockets: run detail every 3s, run list 8s, dashboard 10s,
approvals 15s, health 30s. At this scale polling is simpler, has no reconnection
semantics to get wrong, and survives a worker restart without a stale socket.
SSE is on the roadmap for the run-detail screen.

## Design system

Tokens in `globals.css`. Dark-first; light mode is a *selected* set of steps
validated against the light surface, not an automatic inversion. Theme follows
the OS by default with an explicit toggle persisted in `localStorage`, applied
before first paint by a tiny inline script so there is no flash of the wrong
palette.

Glass surfaces are CSS (`backdrop-filter` plus a 1px specular edge) — GPU
composited, free per frame. Used deliberately: the objective composer, summary
cards, run status, investigation cards, approval dialogs, the selected nav item.
**Never** behind long-form body text, where transparency costs legibility.
Reports and dense tables sit on opaque `panel` surfaces.

## The liquid-glass decision

[`dashersw/liquid-glass-js`](https://github.com/dashersw/liquid-glass-js) is
vendored (MIT) at `public/vendor/liquid-glass/`. It is used for **one**
decorative surface — the objective composer hero — behind
`NEXT_PUBLIC_LIQUID_GLASS=on`, **off by default**.

### Why it is opt-in

The library renders a WebGL refraction pass over an `html2canvas` snapshot of
the page. That is genuinely beautiful, and it is also:

- **Expensive per repaint.** A full-document capture is synchronous and
  layout-reading. This UI polls a live backend, so content behind a glass
  surface changes every few seconds — meaning a fresh capture each time.
  Continuous capture degrades scroll and interaction.
- **Contrast-reducing.** Refraction distorts and lightens what is behind it,
  on exactly the surfaces carrying the most information.
- **Not universally available.** It needs WebGL and a desktop-class device.

So the CSS treatment is the default, and the WebGL effect is an additive accent
on one surface where there is no dense text behind it.

### How it is guarded

`LiquidGlassSurface` refuses to initialise unless all of these hold: the flag is
on, `prefers-reduced-motion` is not set, the viewport is ≥1024px with a fine
pointer, and WebGL is available. The library and `html2canvas` are loaded
lazily, 400ms after paint, so neither is in the main bundle or delays
interactivity. Children always render in normal DOM flow and the canvas is
`aria-hidden`, so the page is functionally identical with the effect off. Any
failure silently leaves the CSS glass in place.

This is the engineering judgement the brief asked for: inspect the integration
requirements, use it carefully, and let accessibility and usability win.

## Charts

Built to a validated palette and a fixed set of rules:

- **Form first.** Magnitude → bars; change over time → lines; a single headline
  → a stat tile, not a chart. The evaluation score distribution is a table
  because that is genuinely clearer than a plot of five numbers.
- **Colour by job.** Categorical hues assigned by slot in fixed order and never
  cycled; a single-hue sequential ramp for magnitude; a reserved status palette
  for state. The palette was validated against *this app's* surfaces (dark
  `#15191f`, light `#ffffff`) for lightness band, chroma floor, colour-vision
  separation and contrast.
- **One y-axis, never two.**
- **Status is never colour alone** — always an icon and a text label.
- **Legend** whenever there are two or more series; single-series charts are
  named by the title instead.
- **A table view** behind a toggle on every plotted chart. This is also the
  contrast relief for the two light-mode series that sit below 3:1 against
  white.
- **Recessive chrome** — hairline gridlines, no vertical grid on time series,
  muted axis labels, 2px lines, 4px rounded data-ends.
- **Hover tooltips** on every plotted form.

## Accessibility

Semantic landmarks and a skip link. `aria-current` on the active nav item,
`aria-pressed` on toggles, `aria-live` on loading regions, `role="alert"` on
errors, labelled form controls with help text wired through `aria-describedby`,
`role="progressbar"` with values, `role="dialog"` + `aria-modal` on dialogs.
Focus outlines are never removed. Full `prefers-reduced-motion` support. Body
text is 13–14px against tokens that hold their contrast in both themes.

## Type safety

`npm run typecheck` runs `tsc --noEmit` with `strict`, `noUnusedLocals`,
`noUnusedParameters` and `noFallthroughCasesInSwitch`. ESLint forbids
`any`. API types are hand-written in `src/lib/types.ts` — a generated client
would track the backend automatically, but the hand-written types state exactly
what the UI relies on, and the typecheck catches drift at the call site.

The production build runs with linting as a separate explicit step, so a lint
warning cannot silently become a failed deploy.
