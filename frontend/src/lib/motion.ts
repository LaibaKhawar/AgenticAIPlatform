'use client'

/**
 * Motion hooks.
 *
 * Everything here degrades to "no motion" when the user has asked for reduced
 * motion, and none of it ever changes *what* is displayed — only how a real
 * value arrives on screen.
 */

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useMotionPreference } from './preferences'

const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)'

function subscribeReducedMotion(onChange: () => void): () => void {
  const query = window.matchMedia(REDUCED_MOTION_QUERY)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

/** Live OS `prefers-reduced-motion`. Server render assumes reduced (no motion). */
export function useSystemPrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia(REDUCED_MOTION_QUERY).matches,
    () => true,
  )
}

/**
 * Whether motion should be reduced: the OS asks for it, or the viewer chose
 * "Reduce motion" in Settings. Either one is enough.
 */
export function usePrefersReducedMotion(): boolean {
  const system = useSystemPrefersReducedMotion()
  const [preference] = useMotionPreference()
  return system || preference === 'reduce'
}

function easeOutCubic(t: number): number {
  return 1 - (1 - t) ** 3
}

/**
 * Tween a number towards `target`.
 *
 * On first mount it counts up from zero; on later changes (the dashboard polls
 * every few seconds) it tweens from the value currently shown, so a live
 * update reads as movement rather than a jump. It always lands exactly on the
 * real target. `null` passes straight through, so "no data" stays "no data".
 */
export function useCountUp(target: number | null, durationMs = 900): number | null {
  const reduced = usePrefersReducedMotion()
  const [display, setDisplay] = useState<number | null>(reduced ? target : target === null ? null : 0)
  const shownRef = useRef<number>(0)
  const frameRef = useRef<number | null>(null)

  useEffect(() => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)

    if (target === null) {
      setDisplay(null)
      return
    }
    if (reduced) {
      shownRef.current = target
      setDisplay(target)
      return
    }

    const from = shownRef.current
    if (from === target) {
      setDisplay(target)
      return
    }
    const started = performance.now()

    const step = (now: number) => {
      const progress = Math.min(1, (now - started) / durationMs)
      const value = from + (target - from) * easeOutCubic(progress)
      shownRef.current = value
      setDisplay(progress === 1 ? target : value)
      frameRef.current = progress === 1 ? null : requestAnimationFrame(step)
    }
    frameRef.current = requestAnimationFrame(step)

    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    }
  }, [target, reduced, durationMs])

  return display
}

/**
 * Cursor-following spotlight. Writes the pointer position into the `--mx` /
 * `--my` custom properties that the `.spotlight` CSS class reads; batched to
 * one write per animation frame.
 */
export function useSpotlight<T extends HTMLElement>() {
  const frame = useRef<number | null>(null)

  const onPointerMove = useCallback((event: React.PointerEvent<T>) => {
    const element = event.currentTarget
    const { clientX, clientY } = event
    if (frame.current !== null) return
    frame.current = requestAnimationFrame(() => {
      frame.current = null
      const rect = element.getBoundingClientRect()
      element.style.setProperty('--mx', `${clientX - rect.left}px`)
      element.style.setProperty('--my', `${clientY - rect.top}px`)
    })
  }, [])

  useEffect(
    () => () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current)
    },
    [],
  )

  return { onPointerMove }
}

/** Whether an element is on screen — used to pause the WebGL scene off-screen. */
export function useInView<T extends Element>(rootMargin = '120px') {
  const ref = useRef<T | null>(null)
  const [inView, setInView] = useState(false)

  useEffect(() => {
    const element = ref.current
    if (!element || typeof IntersectionObserver === 'undefined') {
      setInView(true)
      return
    }
    const observer = new IntersectionObserver(([entry]) => setInView(entry?.isIntersecting ?? false), {
      rootMargin,
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [rootMargin])

  return { ref, inView }
}

/** Whether the tab is visible — a hidden tab should not render frames. */
export function usePageVisible(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      document.addEventListener('visibilitychange', onChange)
      return () => document.removeEventListener('visibilitychange', onChange)
    },
    () => document.visibilityState === 'visible',
    () => false,
  )
}
