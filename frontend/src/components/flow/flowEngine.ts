/**
 * The Veriflow Flow — a dependency-free Canvas 2D renderer.
 *
 * The metaphor is the product itself: information enters as separate streams
 * (Objective, Data, Evidence), is routed together through Investigation,
 * branches and is pulled tight again at Verification, and emerges as one
 * trusted conclusion.
 *
 * Depth is real, not faked per effect. Every point on every strand is a 3D
 * position projected through a pinhole camera, so scale, ribbon thickness,
 * softness, apparent speed and parallax all fall out of one model:
 *
 *   right of the frame  — the far end:  small, thin, soft, slow, dim
 *   left of the frame   — the near end: large, thick, crisp, fast, bright
 *
 * The same scene drives the dashboard card and the page transition. A
 * transition renders it into a rectangle that grows from the card to the whole
 * content area while the camera dollies forward into the flow ("the flow
 * escapes its container"), then wipes away right-to-left, in the direction the
 * flow travels.
 *
 * Cost: one filled polygon per strand plus one soft halo, sprite-blitted
 * pulses, a capped device-pixel ratio, and no work at all while paused.
 */

export const STAGE = {
  investigation: 0.38,
  verification: 0.7,
} as const

const COLOURS = {
  lavender: [138, 147, 214],
  paleLavender: [199, 201, 239],
  aqua: [133, 206, 209],
  aquaBright: [190, 236, 238],
  peach: [249, 114, 114],
  label: [169, 174, 214], // #a9aed6 — validated at 5.7:1 on the Beacon band
} as const

type Rgb = readonly [number, number, number]

const rgba = ([r, g, b]: Rgb, a: number) => `rgba(${r},${g},${b},${Math.max(0, Math.min(1, a)).toFixed(3)})`

const Z_FAR = 9
const Z_NEAR = 1.3
const Z_CULL = 0.32
const SAMPLES = 56

/** Deterministic PRNG, so the flow is the same on every load and in every instance. */
function mulberry32(seed: number) {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const smooth = (t: number) => t * t * (3 - 2 * t)

/** Piecewise-smooth interpolation through (u, value) keys. */
function keyed(keys: ReadonlyArray<readonly [number, number]>, u: number): number {
  if (u <= keys[0]![0]) return keys[0]![1]
  for (let i = 1; i < keys.length; i++) {
    const [u1, v1] = keys[i]!
    const [u0, v0] = keys[i - 1]!
    if (u <= u1) return v0 + (v1 - v0) * smooth((u - u0) / (u1 - u0))
  }
  return keys[keys.length - 1]![1]
}

/**
 * How far apart the streams are along the journey: separate inputs, pulled
 * together at Investigation, branching as evidence is gathered, tight at
 * Verification, then opening gently into the conclusion.
 */
const SPREAD: ReadonlyArray<readonly [number, number]> = [
  [0, 1],
  [0.2, 0.6],
  [STAGE.investigation, 0.1],
  [0.53, 0.42],
  [STAGE.verification, 0.04],
  [0.86, 0.16],
  [1, 0.22],
]

interface Strand {
  lane: -1 | 0 | 1
  fan: number
  depth: number
  width: number
  phase: number
  waveFreq: number
  waveAmp: number
  warm: boolean
  alpha: number
}

interface Pulse {
  strand: number
  u: number
  speed: number
  flash: number // seconds since crossing Verification; < 0 when idle
}

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export interface FrameOptions {
  /** Seconds. Use a shared clock (performance.now() / 1000) so instances line up. */
  time: number
  /** Where the flow lives, in CSS pixels within the canvas. */
  layout: Rect
  /** Advance pulses by this many seconds (0 for a static frame). */
  dt?: number
  /** Pointer in [-1, 1] for a subtle parallax. */
  pointer?: { x: number; y: number }
  /** Camera dolly into the flow, in world units (0 at rest). */
  dolly?: number
  /** Global opacity multiplier for the strands and pulses. */
  intensity?: number
  /** Draw the stage labels. */
  labels?: boolean
  /** Clip the flow to this rounded rectangle. */
  clip?: Rect & { radius: number }
  /**
   * Fill the clip with the Beacon Blue plane (the transition's cover).
   * `reveal` (0..1) wipes it away right-to-left, the direction of travel.
   */
  plane?: { alpha: number; reveal?: number }
}

export interface FlowRenderer {
  resize: (cssWidth: number, cssHeight: number, dpr: number) => void
  render: (options: FrameOptions) => void
  destroy: () => void
}

function buildStrands(): Strand[] {
  const random = mulberry32(20261009)
  const strands: Strand[] = []
  const lanes: Array<-1 | 0 | 1> = [-1, 0, 1]
  for (let i = 0; i < 18; i++) {
    const lane = lanes[i % 3]!
    strands.push({
      lane,
      fan: random() * 2 - 1,
      depth: random() * 0.5 - 0.18,
      width: 0.35 + random() * 0.65,
      phase: random() * Math.PI * 2,
      waveFreq: 0.8 + random() * 1.4,
      waveAmp: 0.08 + random() * 0.16,
      warm: i % 7 === 3, // a few strands carry the verified, Georgia Peach tone
      alpha: 0.55 + random() * 0.45,
    })
  }
  // Paint far strands first.
  return strands.sort((a, b) => b.depth - a.depth)
}

function buildPulses(strandCount: number): Pulse[] {
  const random = mulberry32(7)
  return Array.from({ length: 26 }, () => ({
    strand: Math.floor(random() * strandCount),
    u: random(),
    speed: 0.075 + random() * 0.07,
    flash: -1,
  }))
}

/** A soft round sprite per colour, so pulses glow instead of being hard dots. */
function makeSprite(colour: Rgb): HTMLCanvasElement {
  const size = 64
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const context = canvas.getContext('2d')!
  const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  gradient.addColorStop(0, rgba(COLOURS.aquaBright, 1))
  gradient.addColorStop(0.18, rgba(colour, 1))
  gradient.addColorStop(0.45, rgba(colour, 0.35))
  gradient.addColorStop(1, rgba(colour, 0))
  context.fillStyle = gradient
  context.fillRect(0, 0, size, size)
  return canvas
}

interface Point {
  x: number
  y: number
  z: number
  /** Projected scale (pixels per world unit at this depth). */
  s: number
}

export function createFlowRenderer(canvas: HTMLCanvasElement): FlowRenderer {
  const context = canvas.getContext('2d', { alpha: true })
  if (!context) throw new Error('Canvas 2D is unavailable')
  const ctx = context
  // Canvas fonts cannot resolve CSS variables, so read the real family name
  // that next/font assigned to --font-geist-mono.
  const monoFamily =
    getComputedStyle(document.documentElement).getPropertyValue('--font-geist-mono').trim() || 'ui-monospace'
  const labelFont = `600 9.5px ${monoFamily}, ui-monospace, monospace`

  const strands = buildStrands()
  const pulses = buildPulses(strands.length)
  const sprites = {
    raw: makeSprite(COLOURS.paleLavender),
    evidence: makeSprite(COLOURS.aqua),
    verified: makeSprite(COLOURS.peach),
  }
  let width = 0
  let height = 0
  let ratio = 1
  const points: Point[] = Array.from({ length: SAMPLES + 1 }, () => ({ x: 0, y: 0, z: 0, s: 0 }))

  function resize(cssWidth: number, cssHeight: number, dpr: number) {
    width = cssWidth
    height = cssHeight
    ratio = dpr
    canvas.width = Math.max(1, Math.round(cssWidth * dpr))
    canvas.height = Math.max(1, Math.round(cssHeight * dpr))
  }

  /** The scene's rest pose, expressed relative to the layout rectangle. */
  function scene(layout: Rect) {
    const { x, y, w, h } = layout
    const farX = x + w * 0.93
    const farY = y + h * 0.61
    const nearX = x - w * 0.08
    const nearY = y + h * 1.12
    const f = Math.max(w, h) * 0.9
    return {
      farX,
      farY,
      nearX,
      nearY,
      f,
      // The vanishing point is the far end: dollying in rushes everything
      // outward from where the information first appears.
      cx: farX,
      cy: farY,
      laneGap: (h * 0.092 * Z_FAR) / f,
      widthWorld: (Math.max(4, h * 0.02) * Z_NEAR) / f,
      pulseWorld: (Math.max(2.2, h * 0.0085) * Z_NEAR) / f,
    }
  }

  type Scene = ReturnType<typeof scene>

  /** World position of a point on a strand, then projected through the camera. */
  function sample(
    sc: Scene,
    strand: Strand,
    u: number,
    time: number,
    cam: { x: number; y: number; dolly: number },
    out: Point,
  ): boolean {
    // Rest-pose screen path: drifts left, and descends as it approaches.
    const sx = sc.farX + (sc.nearX - sc.farX) * Math.pow(u, 1.25)
    const sy = sc.farY + (sc.nearY - sc.farY) * Math.pow(u, 1.6)
    // Geometric depth, so the approach feels steady rather than sudden.
    const z = Z_FAR * Math.pow(Z_NEAR / Z_FAR, Math.pow(u, 0.9)) * (1 + strand.depth * (1 - 0.6 * u))

    const breathe = 1 + 0.08 * Math.sin(time * 0.4 + strand.lane * 1.7)
    const spread = keyed(SPREAD, u) * breathe
    const wave =
      Math.sin(u * Math.PI * 2 * strand.waveFreq - time * 0.9 + strand.phase) *
      strand.waveAmp *
      sc.laneGap *
      (0.35 + 0.65 * (1 - u))
    const laneWorld = (strand.lane * sc.laneGap + strand.fan * sc.laneGap * 0.38) * spread + wave

    // Reconstruct the world point from the rest pose, then apply the camera.
    const wx = ((sx - sc.cx) * z) / sc.f
    const wy = ((sy - sc.cy) * z) / sc.f + laneWorld
    const zc = z - cam.dolly
    if (zc <= Z_CULL) return false
    const s = sc.f / zc
    out.x = sc.cx + (wx - cam.x) * s
    out.y = sc.cy + (wy - cam.y) * s
    out.z = zc
    out.s = s
    return true
  }

  function ribbon(count: number, widthAt: (p: Point) => number) {
    ctx.beginPath()
    for (let i = 0; i < count; i++) {
      const p = points[i]!
      const a = points[Math.max(0, i - 1)]!
      const b = points[Math.min(count - 1, i + 1)]!
      let nx = -(b.y - a.y)
      let ny = b.x - a.x
      const length = Math.hypot(nx, ny) || 1
      nx /= length
      ny /= length
      const half = widthAt(p) / 2
      if (i === 0) ctx.moveTo(p.x + nx * half, p.y + ny * half)
      else ctx.lineTo(p.x + nx * half, p.y + ny * half)
    }
    for (let i = count - 1; i >= 0; i--) {
      const p = points[i]!
      const a = points[Math.max(0, i - 1)]!
      const b = points[Math.min(count - 1, i + 1)]!
      let nx = -(b.y - a.y)
      let ny = b.x - a.x
      const length = Math.hypot(nx, ny) || 1
      nx /= length
      ny /= length
      const half = widthAt(p) / 2
      ctx.lineTo(p.x - nx * half, p.y - ny * half)
    }
    ctx.closePath()
  }

  function drawStrands(sc: Scene, time: number, cam: { x: number; y: number; dolly: number }, intensity: number) {
    const maxWidth = Math.min(width, height) * 0.3
    for (const strand of strands) {
      let count = 0
      for (let i = 0; i <= SAMPLES; i++) {
        if (!sample(sc, strand, i / SAMPLES, time, cam, points[count]!)) break
        count++
      }
      if (count < 3) continue
      const first = points[0]!
      const last = points[count - 1]!
      const base = strand.width * sc.widthWorld

      // Depth of field: the far end is soft (a wide, faint halo), the near end crisp.
      const halo = ctx.createLinearGradient(first.x, first.y, last.x, last.y)
      halo.addColorStop(0, rgba(COLOURS.lavender, 0))
      halo.addColorStop(0.12, rgba(COLOURS.lavender, 0.1 * strand.alpha * intensity))
      halo.addColorStop(0.55, rgba(COLOURS.aqua, 0.06 * strand.alpha * intensity))
      halo.addColorStop(1, rgba(COLOURS.aqua, 0.02 * strand.alpha * intensity))
      ctx.fillStyle = halo
      ribbon(count, (p) => {
        const farness = Math.min(1, Math.max(0, (p.z - Z_NEAR) / (Z_FAR - Z_NEAR)))
        return Math.min(maxWidth, base * p.s * (1.6 + 5 * farness) + 1.5)
      })
      ctx.fill()

      const core = ctx.createLinearGradient(first.x, first.y, last.x, last.y)
      const a = strand.alpha * intensity
      core.addColorStop(0, rgba(COLOURS.lavender, 0))
      core.addColorStop(0.07, rgba(COLOURS.lavender, 0.32 * a))
      core.addColorStop(0.42, rgba(COLOURS.aqua, 0.55 * a))
      if (strand.warm) {
        core.addColorStop(0.72, rgba(COLOURS.aqua, 0.7 * a))
        core.addColorStop(0.88, rgba(COLOURS.peach, 0.78 * a))
        core.addColorStop(1, rgba(COLOURS.peach, 0.85 * a))
      } else {
        core.addColorStop(0.72, rgba(COLOURS.aqua, 0.72 * a))
        core.addColorStop(1, rgba(COLOURS.aquaBright, 0.88 * a))
      }
      ctx.fillStyle = core
      ribbon(count, (p) => Math.min(maxWidth, Math.max(0.6, base * p.s)))
      ctx.fill()
    }
  }

  const scratch: Point = { x: 0, y: 0, z: 0, s: 0 }

  function drawPulses(
    sc: Scene,
    time: number,
    dt: number,
    cam: { x: number; y: number; dolly: number },
    intensity: number,
  ) {
    for (const pulse of pulses) {
      const before = pulse.u
      pulse.u += dt * pulse.speed
      if (pulse.flash >= 0) pulse.flash += dt
      if (before < STAGE.verification && pulse.u >= STAGE.verification) pulse.flash = 0
      if (pulse.u >= 1) {
        pulse.u -= 1
        pulse.flash = -1
      }
    }

    // Near pulses last, so they pass in front.
    const order = [...pulses].sort((a, b) => a.u - b.u)
    for (const pulse of order) {
      const strand = strands[pulse.strand]!
      // Raw signal -> evidence -> verified result, by stage.
      const sprite =
        pulse.u < STAGE.investigation ? sprites.raw : pulse.u < STAGE.verification ? sprites.evidence : sprites.verified
      const fadeIn = Math.min(1, pulse.u / 0.06)

      // A short comet tail along the same path, so pulses travel *with* the flow.
      for (let k = 5; k >= 0; k--) {
        const u = pulse.u - k * 0.011
        if (u <= 0) continue
        if (!sample(sc, strand, u, time, cam, scratch)) continue
        const size = Math.min(80, sc.pulseWorld * scratch.s * (k === 0 ? 4.2 : 3.4 - k * 0.45))
        ctx.globalAlpha = intensity * fadeIn * (k === 0 ? 0.95 : 0.32 - k * 0.05)
        ctx.drawImage(sprite, scratch.x - size / 2, scratch.y - size / 2, size, size)
      }

      // The moment a claim is verified: a single expanding ring.
      if (pulse.flash >= 0 && pulse.flash < 0.7 && sample(sc, strand, pulse.u, time, cam, scratch)) {
        const t = pulse.flash / 0.7
        ctx.globalAlpha = intensity * (1 - t) * 0.7
        ctx.strokeStyle = rgba(COLOURS.peach, 1)
        ctx.lineWidth = Math.max(0.75, sc.pulseWorld * scratch.s * 0.35)
        ctx.beginPath()
        ctx.arc(scratch.x, scratch.y, sc.pulseWorld * scratch.s * (1.5 + t * 5), 0, Math.PI * 2)
        ctx.stroke()
      }
    }
    ctx.globalAlpha = 1
  }

  function drawLabels(sc: Scene, time: number, cam: { x: number; y: number; dolly: number }, intensity: number) {
    const marks: Array<{ text: string; u: number; lane: -1 | 0 | 1 | null; dx: number; dy: number; align: CanvasTextAlign }> = [
      { text: 'OBJECTIVE', u: 0.03, lane: -1, dx: 0, dy: -9, align: 'right' },
      { text: 'DATA', u: 0.03, lane: 0, dx: 0, dy: -9, align: 'right' },
      { text: 'EVIDENCE', u: 0.03, lane: 1, dx: 0, dy: -9, align: 'right' },
      { text: 'INVESTIGATION', u: STAGE.investigation, lane: null, dx: 0, dy: -12, align: 'center' },
      { text: 'VERIFICATION', u: STAGE.verification, lane: null, dx: 0, dy: -12, align: 'center' },
    ]
    ctx.font = labelFont
    try {
      ;(ctx as CanvasRenderingContext2D & { letterSpacing: string }).letterSpacing = '1.4px'
    } catch {
      /* older engines: default spacing */
    }
    const centre: Strand = { lane: 0, fan: 0, depth: 0, width: 1, phase: 0, waveFreq: 0, waveAmp: 0, warm: false, alpha: 1 }
    for (const mark of marks) {
      const strand = mark.lane === null ? centre : { ...centre, lane: mark.lane }
      if (!sample(sc, strand, mark.u, time, cam, scratch)) continue
      const anchorX = scratch.x
      const anchorY = scratch.y
      // A stage label clears the whole bundle: find its topmost strand edge here.
      let top = anchorY
      if (mark.lane === null) {
        for (const other of strands) {
          if (sample(sc, other, mark.u, time, cam, scratch)) {
            top = Math.min(top, scratch.y - (other.width * sc.widthWorld * scratch.s) / 2)
          }
        }
      }
      scratch.x = anchorX
      scratch.y = anchorY
      const x = anchorX + mark.dx
      const y = (mark.lane === null ? top : anchorY) + mark.dy
      if (x < 8 || x > width - 8 || y < 10 || y > height - 4) continue
      ctx.globalAlpha = 0.85 * intensity
      ctx.fillStyle = rgba(COLOURS.label, 1)
      ctx.textAlign = mark.align
      ctx.textBaseline = 'alphabetic'
      ctx.fillText(mark.text, mark.align === 'right' ? x - 10 : x, y)
      ctx.beginPath()
      ctx.arc(scratch.x, scratch.y, mark.lane === null ? 3 : 2.2, 0, Math.PI * 2)
      ctx.strokeStyle = rgba(COLOURS.label, 0.8)
      ctx.lineWidth = 1
      ctx.stroke()
    }
    ctx.globalAlpha = 1
  }

  function roundedRect(rect: Rect & { radius: number }) {
    const r = Math.max(0, Math.min(rect.radius, rect.w / 2, rect.h / 2))
    ctx.beginPath()
    ctx.moveTo(rect.x + r, rect.y)
    ctx.arcTo(rect.x + rect.w, rect.y, rect.x + rect.w, rect.y + rect.h, r)
    ctx.arcTo(rect.x + rect.w, rect.y + rect.h, rect.x, rect.y + rect.h, r)
    ctx.arcTo(rect.x, rect.y + rect.h, rect.x, rect.y, r)
    ctx.arcTo(rect.x, rect.y, rect.x + rect.w, rect.y, r)
    ctx.closePath()
  }

  /** The Beacon Blue plane, matching the card's .hero-band background. */
  function drawPlane(rect: Rect, alpha: number, reveal: number) {
    if (alpha <= 0) return
    const base = ctx.createLinearGradient(rect.x, rect.y, rect.x + rect.w, rect.y + rect.h)
    base.addColorStop(0, '#2b3160')
    base.addColorStop(0.46, '#252a50')
    base.addColorStop(1, '#171a38')
    ctx.globalAlpha = alpha
    ctx.fillStyle = base
    if (reveal > 0) {
      // A soft wipe edge travelling right-to-left: pixels right of it are revealed.
      const feather = Math.max(80, width * 0.12)
      const edge = rect.x + rect.w + feather - reveal * (rect.w + feather * 2)
      ctx.save()
      // destination-out removes where the mask is opaque: keep the covered
      // side (left), dissolve toward the leading edge (right).
      const mask = ctx.createLinearGradient(edge - feather, 0, edge, 0)
      mask.addColorStop(0, 'rgba(0,0,0,0)')
      mask.addColorStop(1, 'rgba(0,0,0,1)')
      ctx.fillRect(rect.x, rect.y, Math.max(0, Math.min(rect.w, edge - rect.x)), rect.h)
      ctx.globalCompositeOperation = 'destination-out'
      ctx.fillStyle = mask
      ctx.fillRect(edge - feather, rect.y, feather + 2, rect.h)
      ctx.restore()
    } else {
      ctx.fillRect(rect.x, rect.y, rect.w, rect.h)
      const glow = ctx.createRadialGradient(rect.x + rect.w, rect.y, 0, rect.x + rect.w, rect.y, rect.w * 0.6)
      glow.addColorStop(0, 'rgba(249,114,114,0.18)')
      glow.addColorStop(1, 'rgba(249,114,114,0)')
      ctx.fillStyle = glow
      ctx.fillRect(rect.x, rect.y, rect.w, rect.h)
    }
    ctx.globalAlpha = 1
  }

  function render(options: FrameOptions) {
    const { time, layout, dt = 0, pointer = { x: 0, y: 0 }, dolly = 0, intensity = 1, labels = false, clip, plane } =
      options
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0)
    ctx.clearRect(0, 0, width, height)
    if (layout.w <= 0 || layout.h <= 0) return

    const sc = scene(layout)
    // Parallax: shift the camera, so near strands move more than far ones.
    const cam = {
      x: (pointer.x * 22 * Z_NEAR) / sc.f,
      y: (pointer.y * 12 * Z_NEAR) / sc.f,
      dolly,
    }

    ctx.save()
    if (clip) {
      roundedRect(clip)
      ctx.clip()
    }
    if (plane && clip) drawPlane(clip, plane.alpha, plane.reveal ?? 0)
    ctx.globalCompositeOperation = 'lighter'
    drawStrands(sc, time, cam, intensity)
    drawPulses(sc, time, dt, cam, intensity)
    ctx.globalCompositeOperation = 'source-over'
    if (labels) drawLabels(sc, time, cam, intensity)
    ctx.restore()
  }

  return {
    resize,
    render,
    destroy: () => {
      canvas.width = canvas.height = 0
    },
  }
}
