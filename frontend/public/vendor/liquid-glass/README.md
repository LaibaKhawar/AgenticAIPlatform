# liquid-glass-js (vendored)

Source: https://github.com/dashersw/liquid-glass-js — MIT, see `LICENSE`.

`container.js` is vendored verbatim. It renders a WebGL refraction pass over a
snapshot of the page, which is why it needs `html2canvas` and a real repaint
whenever the content behind it changes.

## Why it is opt-in here

Veriflow's UI is an information-dense dashboard that polls a live backend, so the
content behind a glass surface changes every couple of seconds. Each change
requires a fresh `html2canvas` capture of the whole document — an expensive,
synchronous, layout-reading operation. Running that continuously behind live data
degrades scroll and interaction, and the refraction pass reduces text contrast on
exactly the surfaces that carry the most information.

So the WebGL effect is applied to **one** decorative surface — the objective
composer's hero panel — and only when `NEXT_PUBLIC_LIQUID_GLASS=on`. Everything
else uses the CSS glass treatment in `globals.css` (`backdrop-filter` plus a
specular edge), which is GPU-composited, costs nothing per frame, and keeps text
on an opaque-enough plane to stay legible.

The React wrapper (`src/components/ui/LiquidGlassSurface.tsx`) additionally:

- loads the library and `html2canvas` lazily, so neither is in the main bundle;
- refuses to initialise without WebGL, under `prefers-reduced-motion`, on
  pointer-coarse (touch) devices, or at viewports under 1024px;
- always renders its children in normal DOM flow, so the page is identical with
  the effect off — the canvas is purely additive.

See `docs/frontend.md` for the full reasoning.
