'use client'

/**
 * The header's Display menu: theme, motion and the flow, one click away
 * from any page. Built on MorphingPopover — the trigger's label morphs into
 * the popover's heading (shared layoutId), exactly as in the motion-primitives
 * example. Every control writes the same synced preference the Settings page
 * uses, so the two never disagree.
 */

import clsx from 'clsx'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { motion } from 'motion/react'
import { useEffect, useId, useState } from 'react'
import {
  MorphingPopover,
  MorphingPopoverContent,
  MorphingPopoverTrigger,
} from '@/components/core/morphing-popover'
import { ArrowRightIcon, MonitorIcon, MoonIcon, SunIcon } from '@/components/ui/primitives'
import {
  useMotionPreference,
  useScenePreference,
  useThemePreference,
  type MotionPreference,
  type ScenePreference,
  type ThemePreference,
} from '@/lib/preferences'

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: Array<{ value: T; label: string }>
  onChange: (value: T) => void
}) {
  const name = useId()
  return (
    <fieldset className="grid grid-cols-3 items-center gap-3">
      <legend className="sr-only">{label}</legend>
      <span aria-hidden className="text-[12px] text-ink-muted">
        {label}
      </span>
      <div className="col-span-2 flex rounded-lg bg-surface-sunken p-0.5 ring-1 ring-inset ring-[var(--line)]">
        {options.map((option) => {
          const checked = option.value === value
          return (
            <label
              key={option.value}
              className={clsx(
                'press relative flex-1 cursor-pointer rounded-md px-1.5 py-1 text-center text-[11.5px] font-medium',
                'has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--accent)]',
                checked
                  ? 'bg-surface-raised text-ink shadow-[0_2px_8px_-4px_rgb(4_6_20/0.5)] ring-1 ring-inset ring-[var(--line-strong)]'
                  : 'text-ink-muted hover:text-ink',
              )}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={checked}
                onChange={() => onChange(option.value)}
                className="sr-only"
              />
              {option.label}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

export function DisplayMenu() {
  const [theme, setTheme] = useThemePreference()
  const [motionPreference, setMotion] = useMotionPreference()
  const [scene, setScene] = useScenePreference()
  const TriggerIcon = theme === 'light' ? SunIcon : theme === 'dark' ? MoonIcon : MonitorIcon
  // The header outlives page changes, so close the menu on navigation.
  const [open, setOpen] = useState(false)
  const pathname = usePathname()
  useEffect(() => setOpen(false), [pathname])

  return (
    <MorphingPopover open={open} onOpenChange={setOpen}>
      <MorphingPopoverTrigger className="press inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px] font-medium text-ink-secondary ring-1 ring-inset ring-[var(--line)] hover:bg-accent-wash hover:text-ink">
        <TriggerIcon className="h-3.5 w-3.5" />
        <motion.span layoutId="display-menu-label" layout="position">
          Display
        </motion.span>
      </MorphingPopoverTrigger>

      <MorphingPopoverContent label="Display settings" className="top-0 right-0 w-[19rem] p-4">
        <div className="grid gap-4">
          <div className="space-y-1">
            <motion.h2
              layoutId="display-menu-label"
              layout="position"
              className="text-[14px] leading-none font-semibold text-ink"
            >
              Display
            </motion.h2>
            <p className="text-[12px] text-ink-muted">Saved in this browser. Applies immediately.</p>
          </div>

          <div className="grid gap-2.5">
            <Segmented<ThemePreference>
              label="Theme"
              value={theme}
              onChange={setTheme}
              options={[
                { value: 'system', label: 'System' },
                { value: 'dark', label: 'Dark' },
                { value: 'light', label: 'Light' },
              ]}
            />
            <Segmented<MotionPreference>
              label="Motion"
              value={motionPreference}
              onChange={setMotion}
              options={[
                { value: 'system', label: 'System' },
                { value: 'reduce', label: 'Reduce' },
              ]}
            />
            <Segmented<ScenePreference>
              label="Flow"
              value={scene}
              onChange={setScene}
              options={[
                { value: 'on', label: 'On' },
                { value: 'off', label: 'Off' },
              ]}
            />
          </div>

          <Link
            href="/settings#appearance"
            onClick={() => setOpen(false)}
            className="press inline-flex items-center justify-between rounded-lg px-2 py-1.5 text-[12.5px] font-medium text-accent hover:bg-accent-wash"
          >
            All settings
            <ArrowRightIcon className="h-3.5 w-3.5" />
          </Link>
        </div>
      </MorphingPopoverContent>
    </MorphingPopover>
  )
}
