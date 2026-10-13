'use client'

/**
 * Accessible tabs (WAI-ARIA tabs pattern) with a sliding active indicator.
 *
 * Roving tabindex, Left/Right (and Up/Down) to move, Home/End to jump, and
 * automatic activation. Triggers and panels expose `data-state="active" |
 * "inactive"`, so styles written for Radix-style tabs (`data-[state=active]:…`)
 * work unchanged. The active pill is a shared-layout motion element, so it
 * slides between triggers (and simply appears under reduced motion).
 */

import clsx from 'clsx'
import { motion } from 'motion/react'
import {
  createContext,
  useCallback,
  useContext,
  useId,
  useMemo,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react'

type TabsContextValue = {
  value: string
  setValue: (value: string) => void
  baseId: string
}

const TabsContext = createContext<TabsContextValue | null>(null)

function useTabs(component: string): TabsContextValue {
  const context = useContext(TabsContext)
  if (!context) throw new Error(`${component} must be used within <Tabs>`)
  return context
}

export function Tabs({
  defaultValue,
  value: controlledValue,
  onValueChange,
  className,
  children,
}: {
  defaultValue: string
  value?: string
  onValueChange?: (value: string) => void
  className?: string
  children: ReactNode
}) {
  const [uncontrolled, setUncontrolled] = useState(defaultValue)
  const value = controlledValue ?? uncontrolled
  const baseId = useId()

  const setValue = useCallback(
    (next: string) => {
      if (controlledValue === undefined) setUncontrolled(next)
      onValueChange?.(next)
    },
    [controlledValue, onValueChange],
  )

  const context = useMemo(() => ({ value, setValue, baseId }), [value, setValue, baseId])

  return (
    <TabsContext.Provider value={context}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  )
}

export function TabsList({
  className,
  children,
  label,
}: {
  className?: string
  children: ReactNode
  /** Accessible name for the tab list. */
  label: string
}) {
  const { value, setValue } = useTabs('TabsList')

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Read the order from the DOM at keypress time: it is the source of truth,
    // and tracking it through ref callbacks drifts as triggers re-render.
    const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
    const index = tabs.findIndex((tab) => tab.dataset.value === value)
    let next: HTMLButtonElement | undefined
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = tabs[(index + 1) % tabs.length]
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp')
      next = tabs[(index - 1 + tabs.length) % tabs.length]
    else if (event.key === 'Home') next = tabs[0]
    else if (event.key === 'End') next = tabs[tabs.length - 1]
    if (!next?.dataset.value) return
    event.preventDefault()
    setValue(next.dataset.value)
    next.focus()
  }

  return (
    <div role="tablist" aria-label={label} onKeyDown={onKeyDown} className={className}>
      {children}
    </div>
  )
}

export function TabsTrigger({
  value: tab,
  className,
  indicatorClassName,
  children,
}: {
  value: string
  className?: string
  /** Classes for the sliding active pill. */
  indicatorClassName?: string
  children: ReactNode
}) {
  const { value, setValue, baseId } = useTabs('TabsTrigger')
  const active = value === tab

  return (
    <button
      type="button"
      role="tab"
      id={`${baseId}-tab-${tab}`}
      aria-selected={active}
      aria-controls={`${baseId}-panel-${tab}`}
      tabIndex={active ? 0 : -1}
      data-state={active ? 'active' : 'inactive'}
      data-value={tab}
      onClick={() => setValue(tab)}
      className={clsx('relative isolate', className)}
    >
      {active ? (
        <motion.span
          aria-hidden
          layoutId={`${baseId}-indicator`}
          transition={{ type: 'spring', bounce: 0.18, duration: 0.45 }}
          className={clsx('pointer-events-none absolute inset-0 -z-10', indicatorClassName)}
        />
      ) : null}
      {children}
    </button>
  )
}

export function TabsContent({
  value: tab,
  className,
  children,
}: {
  value: string
  className?: string
  children: ReactNode
}) {
  const { value, baseId } = useTabs('TabsContent')
  if (value !== tab) return null
  return (
    <div
      role="tabpanel"
      id={`${baseId}-panel-${tab}`}
      aria-labelledby={`${baseId}-tab-${tab}`}
      data-state="active"
      tabIndex={0}
      className={className}
    >
      {children}
    </div>
  )
}
