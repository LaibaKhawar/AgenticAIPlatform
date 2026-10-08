'use client'

/** Data-fetching hooks: one request shape, one polling implementation. */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from './api'

export interface AsyncState<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
  /** True only for the first load, so refreshes don't flash skeletons. */
  initialLoading: boolean
  refresh: () => void
}

interface Options {
  /** Poll interval in ms. 0 or undefined disables polling. */
  intervalMs?: number
  /** When false the request is not issued at all (e.g. waiting on a route param). */
  enabled?: boolean
}

/**
 * Fetch once, optionally poll, and always abort in flight work on unmount or
 * when the dependency key changes — so a fast navigation cannot land a stale
 * response on the new page.
 *
 * Polling pauses while the tab is hidden: a background tab does not need to
 * keep a worker busy, and the first visible tick refreshes immediately.
 */
export function useApi<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  options: Options = {},
): AsyncState<T> {
  const { intervalMs = 0, enabled = true } = options
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [initialLoading, setInitialLoading] = useState(enabled)
  const [tick, setTick] = useState(0)

  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const refresh = useCallback(() => setTick((value) => value + 1), [])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      setInitialLoading(false)
      return
    }
    const controller = new AbortController()
    let cancelled = false

    setLoading(true)
    fetcherRef
      .current(controller.signal)
      .then((result) => {
        if (cancelled) return
        setData(result)
        setError(null)
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        if (caught instanceof DOMException && caught.name === 'AbortError') return
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError(0, 'unexpected_error', caught instanceof Error ? caught.message : String(caught)),
        )
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
        setInitialLoading(false)
      })

    return () => {
      cancelled = true
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick, enabled])

  useEffect(() => {
    if (!enabled || !intervalMs) return
    let timer: ReturnType<typeof setInterval> | null = null

    const start = () => {
      if (timer === null) timer = setInterval(refresh, intervalMs)
    }
    const stop = () => {
      if (timer !== null) {
        clearInterval(timer)
        timer = null
      }
    }
    const onVisibility = () => {
      if (document.hidden) {
        stop()
      } else {
        refresh()
        start()
      }
    }

    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [enabled, intervalMs, refresh])

  return { data, error, loading, initialLoading, refresh }
}

/** A local value persisted per browser, tolerant of blocked storage. */
export function useLocalValue(key: string, fallback: string): [string, (value: string) => void] {
  const [value, setValue] = useState(fallback)

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(key)
      if (stored !== null) setValue(stored)
    } catch {
      // Private mode or blocked storage: the fallback is correct.
    }
  }, [key])

  const update = useCallback(
    (next: string) => {
      setValue(next)
      try {
        window.localStorage.setItem(key, next)
      } catch {
        // Non-fatal: the value still applies for this session.
      }
    },
    [key],
  )

  return [value, update]
}
