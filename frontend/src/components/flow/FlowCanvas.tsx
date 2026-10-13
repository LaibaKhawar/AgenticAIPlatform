'use client'

/**
 * Hosts the Veriflow Flow inside a card (the dashboard hero, the 404 page).
 *
 * - measures layout size (offsetWidth/Height), not the transformed box, so the
 *   page-entrance scale animation cannot freeze it at the wrong size;
 * - renders frames only while on screen and while the tab is visible;
 * - under reduced motion (OS or in-app), or with Flow turned off in Settings,
 *   it draws a single still frame — the flow is still legible, it just rests;
 * - uses the shared clock, so a page transition starting from this card picks
 *   up exactly the frame on screen.
 */

import clsx from 'clsx'
import { useEffect, useRef } from 'react'
import { useInView, usePageVisible, usePrefersReducedMotion } from '@/lib/motion'
import { useScenePreference } from '@/lib/preferences'
import { createFlowRenderer, type FlowRenderer } from './flowEngine'

/** The moment shown when the flow is at rest: streams spread, pulses mid-journey. */
export const STILL_TIME = 7.25

export const flowClock = () => performance.now() / 1000

export function FlowCanvas({ className, labels = true }: { className?: string; labels?: boolean }) {
  const { ref, inView } = useInView<HTMLDivElement>()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const renderer = useRef<FlowRenderer | null>(null)
  const size = useRef({ w: 0, h: 0 })
  const pointer = useRef({ x: 0, y: 0 })
  const visible = usePageVisible()
  const reduced = usePrefersReducedMotion()
  const [flow] = useScenePreference()
  const animate = inView && visible && !reduced && flow === 'on'

  // Create the renderer and keep it sized to the host's layout box.
  useEffect(() => {
    const canvas = canvasRef.current
    const host = ref.current
    if (!canvas || !host) return
    try {
      renderer.current = createFlowRenderer(canvas)
    } catch {
      renderer.current = null // no Canvas 2D: the card's own gradient stands alone
      return
    }
    const measure = () => {
      const w = host.offsetWidth
      const h = host.offsetHeight
      if (w === size.current.w && h === size.current.h) return
      size.current = { w, h }
      renderer.current?.resize(w, h, Math.min(window.devicePixelRatio || 1, 1.75))
      renderer.current?.render({ time: STILL_TIME, layout: { x: 0, y: 0, w, h }, labels: labels && w > 720 })
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(host)
    return () => {
      observer.disconnect()
      renderer.current?.destroy()
      renderer.current = null
    }
  }, [ref, labels])

  // The render loop, or a single still frame when the flow should rest.
  useEffect(() => {
    const draw = (time: number, dt: number) => {
      const { w, h } = size.current
      renderer.current?.render({
        time,
        dt,
        layout: { x: 0, y: 0, w, h },
        pointer: pointer.current,
        labels: labels && w > 720,
      })
    }
    if (!animate) {
      draw(STILL_TIME, 0)
      return
    }
    let frame = 0
    let last = flowClock()
    const loop = () => {
      const now = flowClock()
      draw(now, Math.min(0.05, now - last))
      last = now
      frame = requestAnimationFrame(loop)
    }
    frame = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(frame)
  }, [animate, labels])

  // Gentle parallax, eased so the camera drifts rather than snaps.
  useEffect(() => {
    if (!animate) return
    let target = { x: 0, y: 0 }
    let frame = 0
    const onMove = (event: PointerEvent) => {
      target = { x: (event.clientX / window.innerWidth) * 2 - 1, y: (event.clientY / window.innerHeight) * 2 - 1 }
    }
    const ease = () => {
      pointer.current = {
        x: pointer.current.x + (target.x - pointer.current.x) * 0.06,
        y: pointer.current.y + (target.y - pointer.current.y) * 0.06,
      }
      frame = requestAnimationFrame(ease)
    }
    window.addEventListener('pointermove', onMove, { passive: true })
    frame = requestAnimationFrame(ease)
    return () => {
      window.removeEventListener('pointermove', onMove)
      cancelAnimationFrame(frame)
    }
  }, [animate])

  return (
    <div ref={ref} aria-hidden className={clsx('pointer-events-none', className)}>
      <canvas ref={canvasRef} className="block h-full w-full" />
    </div>
  )
}
