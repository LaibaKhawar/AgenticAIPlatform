'use client'

/**
 * InfiniteSlider — adapted from motion-primitives by ibelick (MIT).
 * https://github.com/ibelick/motion-primitives
 *
 * A seamless marquee. Same props as upstream, plus `paused`. Changes:
 *  - one position advanced per frame (useAnimationFrame) instead of a looping
 *    tween that restarts whenever speed changes, so pausing, resuming and
 *    slowing on hover never jump back to the start;
 *  - `paused` exists so pages can offer a pause control: moving content that
 *    runs for more than five seconds must be pausable (WCAG 2.2.2);
 *  - the duplicated copy that makes the loop seamless is aria-hidden and
 *    inert, so screen readers and the keyboard meet each item exactly once;
 *  - with reduced motion (OS or in-app) nothing moves: the items render once,
 *    wrapped and centred.
 */

import clsx from 'clsx'
import { motion, useAnimationFrame, useMotionValue } from 'motion/react'
import { useRef, useState, type ReactNode } from 'react'
import useMeasure from 'react-use-measure'
import { usePrefersReducedMotion } from '@/lib/motion'

export type InfiniteSliderProps = {
  children: ReactNode
  gap?: number
  /** Pixels per second. */
  speed?: number
  speedOnHover?: number
  direction?: 'horizontal' | 'vertical'
  reverse?: boolean
  paused?: boolean
  className?: string
}

export function InfiniteSlider({
  children,
  gap = 16,
  speed = 100,
  speedOnHover,
  direction = 'horizontal',
  reverse = false,
  paused = false,
  className,
}: InfiniteSliderProps) {
  const reduced = usePrefersReducedMotion()
  const [isHovering, setIsHovering] = useState(false)
  const [ref, { width, height }] = useMeasure({ offsetSize: true })
  const translation = useMotionValue(0)
  const offset = useRef(0)
  const horizontal = direction === 'horizontal'

  useAnimationFrame((_, delta) => {
    if (reduced || paused) return
    // One full copy plus the gap that separates it from the duplicate.
    const loop = (horizontal ? width : height) / 2 + gap / 2
    if (loop <= 0) return
    const current = isHovering && speedOnHover !== undefined ? speedOnHover : speed
    offset.current = (offset.current + (current * delta) / 1000) % loop
    translation.set(reverse ? offset.current - loop : -offset.current)
  })

  if (reduced) {
    return (
      <div className={clsx('overflow-hidden', className)}>
        <div className="flex flex-wrap items-center justify-center" style={{ gap }}>
          {children}
        </div>
      </div>
    )
  }

  return (
    <div className={clsx('overflow-hidden', className)}>
      <motion.div
        ref={ref}
        className="flex w-max"
        style={{
          ...(horizontal ? { x: translation } : { y: translation }),
          gap,
          flexDirection: horizontal ? 'row' : 'column',
        }}
        onHoverStart={() => setIsHovering(true)}
        onHoverEnd={() => setIsHovering(false)}
      >
        <div className="flex shrink-0" style={{ gap, flexDirection: horizontal ? 'row' : 'column' }}>
          {children}
        </div>
        <div
          aria-hidden
          inert
          className="flex shrink-0"
          style={{ gap, flexDirection: horizontal ? 'row' : 'column' }}
        >
          {children}
        </div>
      </motion.div>
    </div>
  )
}
