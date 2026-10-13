'use client'

/**
 * Per-viewer display preferences.
 *
 * Stored in localStorage (they are conveniences, not data), synced across every
 * component and tab through `useLocalValue`, and applied to <html> in exactly
 * one place — `PreferenceEffects` — plus the inline pre-paint script in
 * layout.tsx, so there is no flash of the wrong theme or of unwanted motion.
 */

import { useEffect } from 'react'
import { useLocalValue } from './hooks'

export const THEME_KEY = 'veriflow-theme'
export const MOTION_KEY = 'veriflow-motion'
export const SCENE_KEY = 'veriflow-scene'

export type ThemePreference = 'system' | 'dark' | 'light'
/** There is deliberately no "force full motion": an OS request to reduce motion always wins. */
export type MotionPreference = 'system' | 'reduce'
export type ScenePreference = 'on' | 'off'

function narrow<T extends string>(value: string, allowed: readonly T[], fallback: T): T {
  return (allowed as readonly string[]).includes(value) ? (value as T) : fallback
}

export function useThemePreference(): [ThemePreference, (value: ThemePreference) => void] {
  const [value, set] = useLocalValue(THEME_KEY, 'system')
  return [narrow(value, ['system', 'dark', 'light'], 'system'), set]
}

export function useMotionPreference(): [MotionPreference, (value: MotionPreference) => void] {
  const [value, set] = useLocalValue(MOTION_KEY, 'system')
  return [narrow(value, ['system', 'reduce'], 'system'), set]
}

export function useScenePreference(): [ScenePreference, (value: ScenePreference) => void] {
  const [value, set] = useLocalValue(SCENE_KEY, 'on')
  return [narrow(value, ['on', 'off'], 'on'), set]
}

/** Reflects the preferences onto <html> as data attributes the CSS reads. */
export function PreferenceEffects() {
  const [theme] = useThemePreference()
  const [motion] = useMotionPreference()

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => {
    const root = document.documentElement
    if (motion === 'reduce') root.setAttribute('data-motion', 'reduce')
    else root.removeAttribute('data-motion')
  }, [motion])

  return null
}
