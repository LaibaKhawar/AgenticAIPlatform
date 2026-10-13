/**
 * The Veriflow mark: the flow, compressed into a tile.
 *
 * Three thin streams (far, so thin) enter from the right, are pulled into one
 * knot — verification — and leave as a single tapered ribbon that widens as it
 * nears the viewer, exiting past the bottom-left. A Georgia Peach pulse rides
 * the near ribbon: the verified result. Same story, same direction and same
 * palette as the dashboard flow.
 *
 * Keep the geometry in step with src/app/icon.svg (the favicon).
 */

import { useId } from 'react'

export function FlowMark({ className, title }: { className?: string; title?: string }) {
  const id = useId().replace(/:/g, '')
  const tile = `${id}-tile`
  const glow = `${id}-glow`
  const far = `${id}-far`
  const near = `${id}-near`
  const clip = `${id}-clip`

  return (
    <svg
      viewBox="0 0 32 32"
      className={className}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <defs>
        <linearGradient id={tile} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2b3160" />
          <stop offset="0.5" stopColor="#252a50" />
          <stop offset="1" stopColor="#171a38" />
        </linearGradient>
        <radialGradient id={glow} cx="1" cy="0" r="0.75">
          <stop offset="0" stopColor="#f97272" stopOpacity="0.32" />
          <stop offset="1" stopColor="#f97272" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={far} x1="30" y1="0" x2="18" y2="0" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#8a93d6" />
          <stop offset="1" stopColor="#85ced1" />
        </linearGradient>
        <linearGradient id={near} x1="18" y1="16" x2="1" y2="26" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#85ced1" />
          <stop offset="1" stopColor="#beecee" />
        </linearGradient>
        <clipPath id={clip}>
          <rect width="32" height="32" rx="8" />
        </clipPath>
      </defs>

      <rect width="32" height="32" rx="8" fill={`url(#${tile})`} />
      <g clipPath={`url(#${clip})`}>
        <rect width="32" height="32" fill={`url(#${glow})`} />

        {/* Objective, Data, Evidence: thin and distant */}
        <g fill="none" stroke={`url(#${far})`} strokeWidth="1.5" strokeLinecap="round">
          <path d="M31 8.5C25 8.5 22 12.4 18.2 16.3" />
          <path d="M31 14C25 14 22 15.2 18.2 16.3" />
          <path d="M31 19.5C25 19.5 22 18.4 18.2 16.3" />
        </g>

        {/* The conclusion: one ribbon, widening as it approaches */}
        <path d="M18.2 15.7C14.2 18 9 21.1 -1 23.6L-1 29.4C9.6 26.4 14.8 21.4 18.6 16.9Z" fill={`url(#${near})`} />

        {/* Verification knot */}
        <circle cx="18.2" cy="16.3" r="1.7" fill="#252a50" stroke="#c7c9ef" strokeWidth="0.9" />

        {/* A verified result travelling toward the viewer */}
        <circle cx="9.6" cy="22.9" r="2" fill="#f97272" stroke="#252a50" strokeWidth="0.7" />
      </g>
      <rect
        x="0.5"
        y="0.5"
        width="31"
        height="31"
        rx="7.5"
        fill="none"
        stroke="#ffffff"
        strokeOpacity="0.12"
      />
    </svg>
  )
}
