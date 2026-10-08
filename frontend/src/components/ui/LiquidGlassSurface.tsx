'use client'

/**
 * Optional WebGL liquid-glass accent (dashersw/liquid-glass-js, vendored under
 * `public/vendor/liquid-glass/`).
 *
 * The library renders a refraction pass over an `html2canvas` snapshot of the
 * page. That is beautiful and expensive, so it is used for exactly one
 * decorative surface — the objective composer — and only when the environment
 * opts in with `NEXT_PUBLIC_LIQUID_GLASS=on`.
 *
 * Guard rails, in order of application:
 *   1. the feature flag,
 *   2. `prefers-reduced-motion`,
 *   3. WebGL availability,
 *   4. fine pointer + >=1024px viewport (never on touch or small screens),
 *   5. lazy script loading, so neither the library nor html2canvas is in the
 *      main bundle.
 *
 * Children always render in normal DOM flow. The canvas the library injects is
 * purely additive and `aria-hidden`, so the page is functionally identical with
 * the effect off — which is also how the CSS-glass default looks.
 */

import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import type { ReactNode } from 'react'
import { config } from '@/lib/config'

const HTML2CANVAS_SRC = 'https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js'
const CONTAINER_SRC = '/vendor/liquid-glass/container.js'

declare global {
  interface Window {
    // Provided by the vendored library.
    Container?: new (options: Record<string, unknown>) => { element: HTMLElement }
    html2canvas?: unknown
    glassControls?: Record<string, number>
  }
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[data-src="${src}"]`)
    if (existing) {
      if (existing.dataset.loaded === 'true') resolve()
      else {
        existing.addEventListener('load', () => resolve(), { once: true })
        existing.addEventListener('error', () => reject(new Error(src)), { once: true })
      }
      return
    }
    const script = document.createElement('script')
    script.src = src
    script.async = true
    script.dataset.src = src
    script.addEventListener(
      'load',
      () => {
        script.dataset.loaded = 'true'
        resolve()
      },
      { once: true },
    )
    script.addEventListener('error', () => reject(new Error(`failed to load ${src}`)), { once: true })
    document.head.appendChild(script)
  })
}

function supported(): boolean {
  if (!config.liquidGlass) return false
  if (typeof window === 'undefined') return false
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false
  if (!window.matchMedia('(min-width: 1024px) and (pointer: fine)').matches) return false
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
}

export function LiquidGlassSurface({
  children,
  className,
  tintOpacity = 0.18,
  borderRadius = 20,
}: {
  children: ReactNode
  className?: string
  tintOpacity?: number
  borderRadius?: number
}) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState(false)

  useEffect(() => {
    if (!supported()) return
    let cancelled = false
    let injected: HTMLElement | null = null

    const start = async () => {
      try {
        await loadScript(HTML2CANVAS_SRC)
        await loadScript(CONTAINER_SRC)
        if (cancelled || !hostRef.current || typeof window.Container !== 'function') return

        // Calmer than the library's defaults: this sits behind text.
        window.glassControls = {
          ...(window.glassControls ?? {}),
          edgeIntensity: 0.012,
          rimIntensity: 0.045,
          baseIntensity: 0.006,
          blurRadius: 6,
          tintOpacity,
        }

        const instance = new window.Container({ borderRadius, type: 'rounded', tintOpacity })
        injected = instance.element
        injected.style.position = 'absolute'
        injected.style.inset = '0'
        injected.style.pointerEvents = 'none'
        injected.style.borderRadius = `${borderRadius}px`
        injected.setAttribute('aria-hidden', 'true')
        hostRef.current.appendChild(injected)
        if (!cancelled) setActive(true)
      } catch {
        // Any failure leaves the CSS glass treatment in place. The surface is
        // decorative, so a missing effect is never worth an error to the user.
        if (!cancelled) setActive(false)
      }
    }

    // Defer past first paint so the effect never delays interactivity.
    const handle = window.setTimeout(start, 400)
    return () => {
      cancelled = true
      window.clearTimeout(handle)
      injected?.remove()
    }
  }, [borderRadius, tintOpacity])

  return (
    <div
      ref={hostRef}
      data-liquid-glass={active ? 'on' : 'off'}
      className={clsx('glass glass-strong relative isolate', className)}
    >
      <div className="relative z-1">{children}</div>
    </div>
  )
}
