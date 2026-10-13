'use client'

/**
 * AnimatedBackground — adapted from motion-primitives by ibelick (MIT).
 * https://github.com/ibelick/motion-primitives
 *
 * A highlight that slides between its children (on click, or on hover).
 * Changes from upstream:
 *  - keyboard parity: in hover mode, focus moves the highlight too;
 *  - the child's own handlers (onClick, onMouseEnter, …) are composed, not
 *    overwritten, so a tab button keeps its own click behaviour;
 *  - the child's layout is left untouched: the highlight is a -z-10 layer in
 *    an isolated stacking context, instead of wrapping the child's content in
 *    an extra div that breaks flex rows;
 *  - motion honours the app's reduced-motion setting via the surrounding
 *    <MotionConfig>.
 */

import clsx from 'clsx'
import { AnimatePresence, motion, type Transition } from 'motion/react'
import {
  Children,
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useState,
  type Attributes,
  type FocusEvent,
  type MouseEvent,
  type ReactElement,
  type ReactNode,
} from 'react'

type ChildProps = {
  'data-id': string
  'data-checked'?: string
  className?: string
  children?: ReactNode
  onClick?: (event: MouseEvent<HTMLElement>) => void
  onMouseEnter?: (event: MouseEvent<HTMLElement>) => void
  onMouseLeave?: (event: MouseEvent<HTMLElement>) => void
  onFocus?: (event: FocusEvent<HTMLElement>) => void
  onBlur?: (event: FocusEvent<HTMLElement>) => void
}

export type AnimatedBackgroundProps = {
  children: ReactElement<ChildProps>[] | ReactElement<ChildProps>
  defaultValue?: string
  onValueChange?: (newActiveId: string | null) => void
  className?: string
  transition?: Transition
  enableHover?: boolean
}

export function AnimatedBackground({
  children,
  defaultValue,
  onValueChange,
  className,
  transition,
  enableHover = false,
}: AnimatedBackgroundProps) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const uniqueId = useId()

  const handleSetActiveId = (id: string | null) => {
    setActiveId(id)
    onValueChange?.(id)
  }

  useEffect(() => {
    if (defaultValue !== undefined) setActiveId(defaultValue)
  }, [defaultValue])

  return Children.map(children, (child, index) => {
    if (!isValidElement<ChildProps>(child)) return child
    const id = child.props['data-id']
    const own = child.props

    const interactionProps = enableHover
      ? {
          onMouseEnter: (event: MouseEvent<HTMLElement>) => {
            own.onMouseEnter?.(event)
            handleSetActiveId(id)
          },
          onMouseLeave: (event: MouseEvent<HTMLElement>) => {
            own.onMouseLeave?.(event)
            handleSetActiveId(null)
          },
          onFocus: (event: FocusEvent<HTMLElement>) => {
            own.onFocus?.(event)
            handleSetActiveId(id)
          },
          onBlur: (event: FocusEvent<HTMLElement>) => {
            own.onBlur?.(event)
            handleSetActiveId(null)
          },
        }
      : {
          onClick: (event: MouseEvent<HTMLElement>) => {
            own.onClick?.(event)
            handleSetActiveId(id)
          },
        }

    const injected: Partial<ChildProps> & Attributes = {
      key: index,
      className: clsx('relative isolate', own.className),
      'data-checked': activeId === id ? 'true' : 'false',
      ...interactionProps,
    }

    return cloneElement(
      child,
      injected,
      <>
        <AnimatePresence initial={false}>
          {activeId === id ? (
            <motion.span
              aria-hidden
              layoutId={`background-${uniqueId}`}
              className={clsx('pointer-events-none absolute inset-0 -z-10', className)}
              transition={transition}
              initial={{ opacity: defaultValue ? 1 : 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            />
          ) : null}
        </AnimatePresence>
        {own.children}
      </>,
    )
  })
}
