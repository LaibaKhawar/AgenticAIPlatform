'use client'

/**
 * TextShimmer — adapted from motion-primitives by ibelick (MIT).
 * https://github.com/ibelick/motion-primitives
 *
 * A light band that sweeps across text. Use it ONLY for work that is actually
 * in flight (a run executing, a request being queued): the shimmer is a status
 * signal, not decoration.
 *
 * Same API as upstream. Changes:
 *  - a CSS keyframe instead of a per-frame JS animation of background-position:
 *    nothing runs on the main thread, and it obeys both the OS reduced-motion
 *    setting and the in-app one (upstream animates background-position, which
 *    motion's reducedMotion does not cover);
 *  - upstream called `motion.create(Component)` inside render, which creates a
 *    new component type on every render and remounts the element each time;
 *  - colours come from the theme tokens, so the resting text is ink-muted
 *    (>= 4.5:1 in both themes) and the band is full-strength ink.
 */

import clsx from 'clsx'
import { memo, useMemo, type CSSProperties, type ElementType, type ReactNode } from 'react'

export type TextShimmerProps = {
  children: string
  as?: ElementType<{ className?: string; style?: CSSProperties; children?: ReactNode }>
  className?: string
  /** Seconds per sweep. */
  duration?: number
  /** Band width, in px per character of text. */
  spread?: number
  /** Merged with the shimmer's own variables (e.g. `--shimmer-base`). */
  style?: CSSProperties
}

function TextShimmerComponent({
  children,
  as: Component = 'p',
  className,
  duration = 2,
  spread = 2,
  style,
}: TextShimmerProps) {
  const dynamicSpread = useMemo(() => children.length * spread, [children, spread])

  return (
    <Component
      className={clsx('text-shimmer', className)}
      style={
        {
          ...style,
          '--spread': `${dynamicSpread}px`,
          '--shimmer-duration': `${duration}s`,
        } as CSSProperties
      }
    >
      {children}
    </Component>
  )
}

export const TextShimmer = memo(TextShimmerComponent)
