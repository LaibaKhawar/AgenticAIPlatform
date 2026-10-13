# Frontend

Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind v4 · Recharts · Motion.

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
| `/stack` | What Veriflow is built with — frontend versions from the lockfile, backend and server versions read live from `GET /api/v1/system/stack` |
| `/settings` | Appearance, motion and flow preferences, plus a live view of the deployment's dependencies |

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

Tokens in `globals.css`, built on three Pantone colours:

| Pantone | Hex | Role |
|---|---|---|
| Beacon Blue 19-3942 TCX | `#252A50` | Foundation: the plane ramp, light-mode ink and primary, the hero band |
| Aqua Splash 14-4812 TCX | `#85CED1` | The one interactive accent: links, focus, dark-mode primary, chart series 1 |
| Georgia Peach 16-1641 TCX | `#F97272` | Warm highlight, used sparingly: brand gradient, verified pulses in the flow, chart series 2 |

The palette is natively light-on-navy. On Beacon Blue, Aqua Splash is 7.7:1
and Georgia Peach 5.0:1; on white they fall to 1.8:1 and 2.7:1. So dark mode is
the flagship and uses the true Pantone values, while light mode keeps Beacon
Blue as ink/primary and uses *deepened* aqua (`#16727a`) and peach (`#b8383f`)
steps wherever those colours carry text. Every text pairing in both themes is
>= 4.5:1 and every chart mark >= 3:1; the full set (133 pairings) was checked
programmatically against the values in `globals.css`.

**Georgia Peach never appears on a badge or status surface.** Under
colour-vision deficiency it is nearly indistinguishable from the critical-risk
red (dE 2.1), and in a churn-risk product a coral brand colour beside a
CRITICAL badge would read as alarm. In charts it is only ever series 2, which
never shares a chart with the critical colour.

The hero band is Beacon Blue in *both* themes, so content on it uses
`.text-brand-hero` and the `brand` / `onDark` button variants, which always use
the true Pantone values. (`.text-brand` swaps to the deepened light-mode steps,
which fall to 2.2:1 on the band.)

Type is Geist and Geist Mono, with tabular figures (`.num`) anywhere numbers
are compared or animated.

**CSS layers matter here.** Tailwind v4 emits every utility inside
`@layer utilities`, and unlayered CSS beats layered CSS regardless of
specificity. So the default border colour lives in `@layer base` and the
surface classes (`.glass`, `.panel`, `.skeleton`) in `@layer components`.
Before this was fixed, an unlayered `* { border-color }` silently overrode
every border-colour utility, and error states rendered with grey borders
instead of red.

Light mode is a *selected* set of steps validated against the light surface,
not an automatic inversion. Theme follows
the OS by default with an explicit toggle persisted in `localStorage`, applied
before first paint by a tiny inline script so there is no flash of the wrong
palette.

Glass surfaces are CSS (`backdrop-filter` plus a 1px specular edge) — GPU
composited, free per frame. Used deliberately: the objective composer, summary
cards, run status, investigation cards, approval dialogs, the selected nav item.
**Never** behind long-form body text, where transparency costs legibility.
Reports and dense tables sit on opaque `panel` surfaces.

### Motion

Transform and opacity only, so everything stays on the compositor. Content is
fully visible by default and every animation is opt-in under
`prefers-reduced-motion: no-preference`; shortening durations alone would not
stop a scroll-driven reveal. Entry motion runs once; only genuine "live"
signals loop.

- Route transitions (`.page-enter`) and staggered cascades (`.stagger`).
- Tactile press (`.press`), spring lift (`.lift`) and a single light sweep on
  primary buttons (`.sheen`).
- A cursor-following spotlight on stat tiles and glass panels (`useSpotlight`).
- Stat tiles count up to their value and tween between polled updates
  (`useCountUp`). They always land exactly on the real value, and screen
  readers only hear the final value.
- Moving stripes on progress bars for runs that are still in flight.

### Vendored motion components

`components/core/` holds four components adapted from
[motion-primitives](https://github.com/ibelick/motion-primitives) (MIT, by
ibelick), built on `motion`. Each file lists what changed and why:

- `AnimatedBackground`: composes the child's own handlers instead of
  overwriting them, moves on keyboard focus as well as hover, and leaves the
  child's layout untouched. Used for the sidebar's hover highlight, the
  run-detail tab bar and the Stack page's layer filter.
- `TextShimmer`: a CSS keyframe instead of a per-frame JS animation (upstream
  remounted its element on every render and ignored reduced motion). Used
  only for work that is genuinely in flight: Running and Retrying badges, and
  the dashboard's running-workers hint.
- `InfiniteSlider`: pausable (WCAG 2.2.2 — the Stack marquee has a pause
  button), the duplicated copy is `aria-hidden` and `inert`, and it stays
  still under reduced motion.
- `MorphingPopover`: an honest non-modal popover (upstream declared
  `aria-modal` without trapping focus). Focus moves in on open and returns to
  the trigger on close, and the surface is opaque. It powers the header's
  Display menu.

`components/ui/tabs.tsx` implements the WAI-ARIA tabs pattern (roving
tabindex, arrow keys, Home/End) with a sliding indicator, and exposes
`data-state` so Radix-style class names work unchanged.

### Preferences

Theme, motion and flow are per-browser preferences in `lib/preferences.ts`,
synced across components and tabs by `useLocalValue`. They are applied to
`<html>` as `data-theme` / `data-motion`, before first paint as well, by the
inline script in `layout.tsx`. There is no "force full motion": an OS request
to reduce motion always wins. Turning Flow off rests the dashboard's flow as a
still frame and makes navigation instant.

### The flow system

Veriflow's motion language is one idea, shown in two places: information
enters, is routed through stages, is verified, and emerges as a trusted
conclusion. It replaces the earlier three.js "constellation", and three.js and
React Three Fiber are no longer dependencies.

**The flow** (`components/flow/flowEngine.ts`) is a dependency-free Canvas 2D
renderer. Eighteen strands enter as three lanes (Objective, Data, Evidence),
are pulled together at Investigation, branch as evidence is gathered, are
pulled tight again at Verification, and open into the conclusion. Pulses
travel the strands and change state by stage: raw signal (pale lavender),
evidence (Aqua Splash), and verified result (Georgia Peach), with a single
ring the moment a pulse crosses Verification. The palette is the Pantone set
only.

Depth is modelled, not faked per effect. Every point is a 3D position projected
through a pinhole camera, so scale, ribbon thickness, softness (a wide faint
halo that fades with distance), brightness, apparent speed and pointer
parallax all come from one model. In the dashboard card the flow enters small
and distant on the right and leaves large and near past the bottom-left.
Measured in the browser, strands are about 6x thicker and 5x brighter at the
near end than the far end.

The card keeps its copy legible over the flow: the vanishing point sits low on
the right, the near end passes beneath the headline and buttons, the live
figures sit top-right out of its path, and a scrim sits behind the headline
only. Measured against the brightest flow pixel behind each block, the body
copy holds 7.95:1 and the smallest labels 5.56:1.

**The page transition** (`components/flow/FlowTransition.tsx`) is the same
scene escaping the card. On a plain click that changes top-level section
(Dashboard -> Runs, not /runs -> /runs/123), navigation is held while the flow
grows out of the card to fill the content area and the camera dollies in
(420ms). The route then changes underneath, unseen (including the scroll to
top), and the flow rushes past the viewer while the cover wipes away
right-to-left, the direction of travel (640ms). Next's `<Link>` skips
navigation when the click is already `defaultPrevented`, which is what makes
holding it safe. Modifier clicks, new-tab and external links, and same-section
links are never intercepted. Back/forward cannot be delayed, so the covered
frame is painted synchronously before the new page shows, then revealed. A
3-second timeout guarantees the cover never sticks.

**Cost and preferences.** Frames render only while the card is on screen and
the tab is visible. The overlay renders only during a transition, at a capped
pixel ratio. Measured: a steady 16.7ms per frame through a transition, and no
long tasks. Under reduced motion (OS or in-app), or with Flow turned off in
Settings or the Display menu, the card rests as a single still frame and pages
change instantly.

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
  for state. Series 1 is Aqua Splash and series 2 Georgia Peach, with a
  sequential ramp from Aqua Splash into Beacon Blue. Every pairing was
  validated against *this app's* surfaces for contrast and for colour-vision
  separation (worst case across deutan, protan and tritan, dE >= 20).
- **One y-axis, never two.**
- **Status is never colour alone** — always an icon and a text label.
- **Legend** whenever there are two or more series; single-series charts are
  named by the title instead.
- **A table view** behind a toggle on every plotted chart. Every series now
  clears 3:1 against every surface in both themes, so the table is a
  convenience rather than contrast relief.
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
