'use client'

/**
 * Veriflow's page transition: the flow escapes the "Every conclusion…" card
 * and briefly takes over the content area.
 *
 *   cover   (~420ms)  the flow grows out of the card (or, on pages without the
 *                     card, out of a distant point on the right) to fill the
 *                     content area, while the camera dollies into it and the
 *                     Beacon Blue plane closes over the old page;
 *   hold              the route changes underneath, unseen — including the
 *                     scroll back to the top;
 *   reveal  (~640ms)  the flow rushes past the viewer and the plane wipes away
 *                     right-to-left, the direction the flow travels.
 *
 * It runs only when the top-level section changes (Dashboard -> Runs, not
 * /runs -> /runs/123), only for plain left-clicks on same-origin links, and
 * never under reduced motion or with Flow turned off in Settings. Back/forward
 * navigation cannot be delayed, so it paints the covered frame synchronously,
 * before the browser shows the new page, then reveals.
 */

import { usePathname, useRouter } from 'next/navigation'
import { useCallback, useEffect, useLayoutEffect, useRef, type RefObject } from 'react'
import { usePrefersReducedMotion } from '@/lib/motion'
import { useScenePreference } from '@/lib/preferences'
import { flowClock } from './FlowCanvas'
import { createFlowRenderer, type FlowRenderer, type Rect } from './flowEngine'

export const COVER_MS = 420
export const REVEAL_MS = 640
const HOLD_TIMEOUT_MS = 3000

type Phase = 'idle' | 'cover' | 'hold' | 'reveal'

const section = (pathname: string) => pathname.split('/')[1] ?? ''

const lerp = (a: number, b: number, t: number) => a + (b - a) * t
const lerpRect = (a: Rect, b: Rect, t: number): Rect => ({
  x: lerp(a.x, b.x, t),
  y: lerp(a.y, b.y, t),
  w: lerp(a.w, b.w, t),
  h: lerp(a.h, b.h, t),
})
const easeInOutCubic = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)
const easeOutCubic = (t: number) => 1 - (1 - t) ** 3
const smooth = (t: number) => {
  const c = Math.max(0, Math.min(1, t))
  return c * c * (3 - 2 * c)
}

export function FlowTransition({
  areaRef,
  headerRef,
}: {
  /** The content column (header + main + footer). */
  areaRef: RefObject<HTMLElement | null>
  /** The sticky header; the transition covers everything below it. */
  headerRef: RefObject<HTMLElement | null>
}) {
  const router = useRouter()
  const pathname = usePathname()
  const reduced = usePrefersReducedMotion()
  const [flow] = useScenePreference()
  const enabled = !reduced && flow === 'on'

  const canvasRef = useRef<HTMLCanvasElement>(null)
  const renderer = useRef<FlowRenderer | null>(null)
  const phase = useRef<Phase>('idle')
  const frame = useRef(0)
  const timeout = useRef<number | null>(null)
  const area = useRef<Rect>({ x: 0, y: 0, w: 0, h: 0 })
  const origin = useRef<Rect>({ x: 0, y: 0, w: 0, h: 0 })
  const lastSection = useRef(section(pathname))
  const enabledRef = useRef(enabled)
  const hiddenHero = useRef<HTMLElement | null>(null)
  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  /** Size and position the overlay over the content area, below the header. */
  const measure = useCallback(() => {
    const canvas = canvasRef.current
    const column = areaRef.current
    if (!canvas || !column) return false
    const columnRect = column.getBoundingClientRect()
    const top = Math.max(0, headerRef.current?.getBoundingClientRect().bottom ?? 0)
    const rect = { x: columnRect.left, y: top, w: columnRect.width, h: window.innerHeight - top }
    canvas.style.left = `${rect.x}px`
    canvas.style.top = `${rect.y}px`
    canvas.style.width = `${rect.w}px`
    canvas.style.height = `${rect.h}px`
    if (!renderer.current) {
      try {
        renderer.current = createFlowRenderer(canvas)
      } catch {
        return false
      }
    }
    renderer.current.resize(rect.w, rect.h, Math.min(window.devicePixelRatio || 1, 1.5))
    area.current = { x: 0, y: 0, w: rect.w, h: rect.h }

    // The card the flow escapes from, if it is on screen; otherwise a distant
    // point on the right, where the flow always enters.
    const hero = document.querySelector<HTMLElement>('[data-flow-origin]')
    const heroRect = hero?.getBoundingClientRect()
    const onScreen = heroRect && heroRect.bottom > top + 40 && heroRect.top < window.innerHeight - 40
    origin.current = onScreen
      ? { x: heroRect.left - rect.x, y: heroRect.top - rect.y, w: heroRect.width, h: heroRect.height }
      : { x: rect.w * 0.7, y: rect.h * 0.34, w: rect.w * 0.24, h: rect.h * 0.2 }
    return true
  }, [areaRef, headerRef])

  const show = (on: boolean) => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.style.visibility = on ? 'visible' : 'hidden'
    canvas.style.pointerEvents = on ? 'auto' : 'none'
  }

  const finish = useCallback(() => {
    cancelAnimationFrame(frame.current)
    if (timeout.current !== null) window.clearTimeout(timeout.current)
    timeout.current = null
    phase.current = 'idle'
    if (hiddenHero.current) hiddenHero.current.style.opacity = ''
    hiddenHero.current = null
    show(false)
  }, [])

  /** Frame of the covered state, also used to paint synchronously. */
  const drawCovered = useCallback((time: number, dt: number) => {
    renderer.current?.render({
      time,
      dt,
      layout: area.current,
      dolly: 0.5,
      clip: { ...area.current, radius: 0 },
      plane: { alpha: 1 },
    })
  }, [])

  const reveal = useCallback(() => {
    cancelAnimationFrame(frame.current)
    if (timeout.current !== null) window.clearTimeout(timeout.current)
    timeout.current = null
    phase.current = 'reveal'
    const start = flowClock()
    let last = start
    const step = () => {
      const now = flowClock()
      const p = Math.min(1, ((now - start) * 1000) / REVEAL_MS)
      const k = easeOutCubic(p)
      renderer.current?.render({
        time: now + 0.8,
        dt: Math.min(0.05, now - last) * 2.6,
        layout: area.current,
        dolly: 0.5 + k * 1.05, // the flow rushes past the viewer
        intensity: 1 - smooth((p - 0.3) / 0.7),
        clip: { ...area.current, radius: 0 },
        plane: { alpha: 1, reveal: easeInOutCubic(p) },
      })
      last = now
      if (p < 1) frame.current = requestAnimationFrame(step)
      else finish()
    }
    frame.current = requestAnimationFrame(step)
  }, [finish])

  const cover = useCallback(
    (href: string) => {
      if (!measure()) {
        router.push(href)
        return
      }
      phase.current = 'cover'
      show(true)
      // Hand the flow over: the card's own canvas steps back so the escaping
      // flow is not drawn twice.
      const heroCanvas = document.querySelector<HTMLElement>('[data-flow-origin] canvas')
      if (heroCanvas) {
        heroCanvas.style.opacity = '0'
        hiddenHero.current = heroCanvas
      }
      const start = flowClock()
      let last = start
      const step = () => {
        const now = flowClock()
        const p = Math.min(1, ((now - start) * 1000) / COVER_MS)
        const k = easeInOutCubic(p)
        const rect = lerpRect(origin.current, area.current, k)
        renderer.current?.render({
          time: now + k * 0.8,
          dt: Math.min(0.05, now - last) * (1 + 1.6 * k),
          layout: rect,
          dolly: k * 0.5,
          clip: { ...rect, radius: lerp(24, 0, k) },
          plane: { alpha: smooth(p * 1.6) },
        })
        last = now
        if (p < 1) {
          frame.current = requestAnimationFrame(step)
          return
        }
        // Fully covered: change the route underneath, and keep the flow alive
        // until the new page has rendered.
        phase.current = 'hold'
        router.push(href)
        timeout.current = window.setTimeout(reveal, HOLD_TIMEOUT_MS)
        const hold = () => {
          const t = flowClock()
          drawCovered(t + 0.8, Math.min(0.05, t - last) * 2.6)
          last = t
          frame.current = requestAnimationFrame(hold)
        }
        frame.current = requestAnimationFrame(hold)
      }
      frame.current = requestAnimationFrame(step)
    },
    [drawCovered, measure, reveal, router],
  )

  // Intercept plain clicks on links that change section. Capture phase runs
  // before Next's <Link> handler, which skips navigation when defaultPrevented.
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!enabledRef.current || event.defaultPrevented) return
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
      const anchor = (event.target as Element | null)?.closest?.('a[href]') as HTMLAnchorElement | null
      if (!anchor) return
      if ((anchor.target && anchor.target !== '_self') || anchor.hasAttribute('download')) return
      const url = new URL(anchor.href, window.location.href)
      if (url.origin !== window.location.origin) return
      if (section(url.pathname) === section(window.location.pathname)) return
      event.preventDefault()
      if (phase.current !== 'idle') return // one transition at a time
      lastSection.current = section(url.pathname)
      cover(url.pathname + url.search + url.hash)
    }
    document.addEventListener('click', onClick, true)
    return () => document.removeEventListener('click', onClick, true)
  }, [cover])

  // The route changed. Either our cover is waiting for it, or it was a
  // navigation we could not delay (back/forward), which still gets a reveal.
  useLayoutEffect(() => {
    const current = section(pathname)
    if (phase.current === 'hold' || phase.current === 'cover') {
      if (phase.current === 'hold') reveal()
      return
    }
    const changed = current !== lastSection.current
    lastSection.current = current
    if (!changed || !enabledRef.current || phase.current !== 'idle') return
    if (!measure()) return
    show(true)
    drawCovered(flowClock(), 0) // painted before the browser shows the new page
    reveal()
  }, [pathname, drawCovered, measure, reveal])

  useEffect(
    () => () => {
      cancelAnimationFrame(frame.current)
      if (timeout.current !== null) window.clearTimeout(timeout.current)
      renderer.current?.destroy()
    },
    [],
  )

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="fixed z-[25]"
      style={{ visibility: 'hidden', pointerEvents: 'none', left: 0, top: 0, width: 0, height: 0 }}
    />
  )
}
