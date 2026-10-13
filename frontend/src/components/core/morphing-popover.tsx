'use client'

/**
 * MorphingPopover — adapted from motion-primitives by ibelick (MIT).
 * https://github.com/ibelick/motion-primitives
 *
 * The trigger morphs into the popover (shared layoutId). Same compound API as
 * upstream. Changes:
 *  - honest semantics: upstream declared role="dialog" aria-modal="true" but
 *    neither trapped nor moved focus. This is a non-modal popover: focus moves
 *    into it on open and returns to the trigger on close; Escape, a click
 *    outside, or tabbing away all close it;
 *  - the trigger exposes aria-haspopup / aria-expanded / aria-controls;
 *  - `asChild` is dropped: upstream implemented it with `motion.create()`
 *    inside render, which remounts the child on every render;
 *  - an opaque raised surface, not translucent glass: a popover sits over
 *    live page content, and glass let the buttons and text underneath show
 *    through its controls.
 */

import clsx from 'clsx'
import { AnimatePresence, MotionConfig, motion, type Transition, type Variants } from 'motion/react'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from 'react'

const TRANSITION: Transition = { type: 'spring', bounce: 0.1, duration: 0.4 }

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

type ContextValue = {
  isOpen: boolean
  open: () => void
  close: (options?: { restoreFocus?: boolean }) => void
  uniqueId: string
  variants?: Variants
  triggerRef: React.RefObject<HTMLButtonElement | null>
}

const MorphingPopoverContext = createContext<ContextValue | null>(null)

function usePopoverContext(component: string): ContextValue {
  const context = useContext(MorphingPopoverContext)
  if (!context) throw new Error(`${component} must be used within MorphingPopover`)
  return context
}

export type MorphingPopoverProps = {
  children: ReactNode
  transition?: Transition
  defaultOpen?: boolean
  open?: boolean
  onOpenChange?: (open: boolean) => void
  variants?: Variants
  className?: string
} & ComponentProps<'div'>

export function MorphingPopover({
  children,
  transition = TRANSITION,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  variants,
  className,
  ...props
}: MorphingPopoverProps) {
  const uniqueId = useId()
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen)
  const isOpen = controlledOpen ?? uncontrolledOpen
  const triggerRef = useRef<HTMLButtonElement | null>(null)

  const open = useCallback(() => {
    if (controlledOpen === undefined) setUncontrolledOpen(true)
    onOpenChange?.(true)
  }, [controlledOpen, onOpenChange])

  const close = useCallback(
    ({ restoreFocus = true }: { restoreFocus?: boolean } = {}) => {
      if (controlledOpen === undefined) setUncontrolledOpen(false)
      onOpenChange?.(false)
      // The trigger re-mounts as the popover morphs back; focus it next frame.
      if (restoreFocus) requestAnimationFrame(() => triggerRef.current?.focus())
    },
    [controlledOpen, onOpenChange],
  )

  const value = useMemo(
    () => ({ isOpen, open, close, uniqueId, variants, triggerRef }),
    [isOpen, open, close, uniqueId, variants],
  )

  return (
    <MorphingPopoverContext.Provider value={value}>
      <MotionConfig transition={transition}>
        <div className={clsx('relative flex items-center justify-center', className)} {...props}>
          {children}
        </div>
      </MotionConfig>
    </MorphingPopoverContext.Provider>
  )
}

export type MorphingPopoverTriggerProps = {
  children: ReactNode
  className?: string
} & Omit<ComponentProps<typeof motion.button>, 'children'>

export function MorphingPopoverTrigger({ children, className, ...props }: MorphingPopoverTriggerProps) {
  const context = usePopoverContext('MorphingPopoverTrigger')

  return (
    <motion.div layoutId={`popover-trigger-${context.uniqueId}`}>
      <motion.button
        type="button"
        {...props}
        ref={context.triggerRef}
        layoutId={`popover-label-${context.uniqueId}`}
        className={className}
        onClick={context.open}
        aria-haspopup="dialog"
        aria-expanded={context.isOpen}
        aria-controls={`popover-content-${context.uniqueId}`}
      >
        {children}
      </motion.button>
    </motion.div>
  )
}

export type MorphingPopoverContentProps = {
  children: ReactNode
  className?: string
  /** Accessible name for the popover. */
  label?: string
} & Omit<ComponentProps<typeof motion.div>, 'children'>

export function MorphingPopoverContent({ children, className, label, ...props }: MorphingPopoverContentProps) {
  const context = usePopoverContext('MorphingPopoverContent')
  const ref = useRef<HTMLDivElement>(null)
  const { isOpen, close } = context

  useEffect(() => {
    if (!isOpen) return

    // Move focus inside once the popover has mounted.
    const frame = requestAnimationFrame(() => {
      const first = ref.current?.querySelector<HTMLElement>(FOCUSABLE)
      ;(first ?? ref.current)?.focus()
    })

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        close()
      }
    }
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node
      // Inside the popover, or on its own trigger (which would otherwise
      // close and immediately reopen it): not an outside click.
      if (ref.current?.contains(target) || context.triggerRef.current?.contains(target)) return
      // Clicking somewhere else hands focus to wherever was clicked.
      close({ restoreFocus: false })
    }
    const onFocusIn = (event: FocusEvent) => {
      const target = event.target as Node
      if (!ref.current?.contains(target) && !context.triggerRef.current?.contains(target)) {
        close({ restoreFocus: false })
      }
    }

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('focusin', onFocusIn)
    return () => {
      cancelAnimationFrame(frame)
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('focusin', onFocusIn)
    }
  }, [isOpen, close, context.triggerRef])

  return (
    <AnimatePresence>
      {isOpen ? (
        <motion.div
          {...props}
          ref={ref}
          layoutId={`popover-trigger-${context.uniqueId}`}
          id={`popover-content-${context.uniqueId}`}
          role="dialog"
          aria-label={label}
          tabIndex={-1}
          className={clsx(
            'absolute z-50 overflow-hidden rounded-[16px] border border-[var(--line-strong)] bg-surface-raised p-2 text-ink outline-none',
            'shadow-[0_24px_60px_-20px_rgb(4_6_20/0.7),0_2px_8px_-2px_rgb(4_6_20/0.35)]',
            className,
          )}
          initial="initial"
          animate="animate"
          exit="exit"
          variants={context.variants}
        >
          {children}
        </motion.div>
      ) : null}
    </AnimatePresence>
  )
}
