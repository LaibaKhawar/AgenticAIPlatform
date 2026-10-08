'use client'

/**
 * UI primitives.
 *
 * Every state the product can be in has a component here — loading, empty,
 * error, disabled — so a page never renders a blank region or a spinner with
 * no explanation.
 */

import clsx from 'clsx'
import Link from 'next/link'
import type { ReactNode } from 'react'

/* -------------------------------------------------------------------------- */
/* Surfaces                                                                   */
/* -------------------------------------------------------------------------- */

export function GlassPanel({
  children,
  className,
  strong = false,
  as: Component = 'div',
}: {
  children: ReactNode
  className?: string
  strong?: boolean
  as?: 'div' | 'section' | 'aside' | 'article'
}) {
  return (
    <Component className={clsx('glass', strong && 'glass-strong', className)}>
      <div className="relative z-1">{children}</div>
    </Component>
  )
}

export function Panel({
  children,
  className,
  as: Component = 'section',
}: {
  children: ReactNode
  className?: string
  as?: 'div' | 'section' | 'article'
}) {
  return <Component className={clsx('panel', className)}>{children}</Component>
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: {
  eyebrow?: string
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('flex flex-wrap items-end justify-between gap-4', className)}>
      <div className="min-w-0">
        {eyebrow ? (
          <div className="mb-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
            {eyebrow}
          </div>
        ) : null}
        <h2 className="text-lg font-semibold tracking-[-0.01em] text-ink">{title}</h2>
        {description ? <p className="mt-1 max-w-2xl text-[13px] text-ink-secondary">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Badges                                                                    */
/* -------------------------------------------------------------------------- */

export type Tone = 'neutral' | 'accent' | 'good' | 'warning' | 'serious' | 'critical' | 'muted'

const TONE_CLASSES: Record<Tone, string> = {
  neutral: 'bg-[color-mix(in_srgb,var(--ink-muted)_14%,transparent)] text-ink-secondary ring-[color-mix(in_srgb,var(--ink-muted)_30%,transparent)]',
  accent: 'bg-accent-wash text-accent ring-[var(--accent-ring)]',
  good: 'bg-[color-mix(in_srgb,var(--status-good)_16%,transparent)] text-[var(--status-good)] ring-[color-mix(in_srgb,var(--status-good)_40%,transparent)]',
  warning:
    'bg-[color-mix(in_srgb,var(--status-warning)_18%,transparent)] text-[color-mix(in_srgb,var(--status-warning)_82%,var(--ink))] ring-[color-mix(in_srgb,var(--status-warning)_45%,transparent)]',
  serious:
    'bg-[color-mix(in_srgb,var(--status-serious)_18%,transparent)] text-[color-mix(in_srgb,var(--status-serious)_85%,var(--ink))] ring-[color-mix(in_srgb,var(--status-serious)_45%,transparent)]',
  critical:
    'bg-[color-mix(in_srgb,var(--status-critical)_16%,transparent)] text-[color-mix(in_srgb,var(--status-critical)_92%,var(--ink))] ring-[color-mix(in_srgb,var(--status-critical)_45%,transparent)]',
  muted: 'bg-surface-sunken text-ink-muted ring-[var(--line)]',
}

export function Badge({
  children,
  tone = 'neutral',
  icon,
  className,
  title,
}: {
  children: ReactNode
  tone?: Tone
  icon?: ReactNode
  className?: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap ring-1 ring-inset',
        TONE_CLASSES[tone],
        className,
      )}
    >
      {icon ? <span aria-hidden className="shrink-0">{icon}</span> : null}
      {children}
    </span>
  )
}

/* -------------------------------------------------------------------------- */
/* Buttons                                                                   */
/* -------------------------------------------------------------------------- */

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success'

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-[var(--accent-ink)] hover:bg-accent-strong shadow-[0_8px_24px_-12px_var(--accent-ring)]',
  secondary: 'bg-surface-raised text-ink ring-1 ring-inset ring-[var(--line-strong)] hover:bg-surface-sunken',
  ghost: 'text-ink-secondary hover:bg-surface-sunken hover:text-ink',
  danger:
    'bg-[color-mix(in_srgb,var(--status-critical)_90%,black)] text-white hover:bg-[var(--status-critical)]',
  success: 'bg-[color-mix(in_srgb,var(--status-good)_88%,black)] text-white hover:bg-[var(--status-good)]',
}

const BUTTON_SIZES = {
  sm: 'h-8 px-3 text-[12px]',
  md: 'h-9.5 px-4 text-[13px]',
  lg: 'h-11 px-5 text-sm',
} as const

interface ButtonBaseProps {
  variant?: ButtonVariant
  size?: keyof typeof BUTTON_SIZES
  className?: string
  children: ReactNode
  icon?: ReactNode
}

export function Button({
  variant = 'secondary',
  size = 'md',
  className,
  children,
  icon,
  loading = false,
  disabled,
  ...rest
}: ButtonBaseProps &
  React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-50',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
    >
      {loading ? <Spinner /> : icon ? <span aria-hidden>{icon}</span> : null}
      {children}
    </button>
  )
}

export function LinkButton({
  href,
  variant = 'secondary',
  size = 'md',
  className,
  children,
  icon,
}: ButtonBaseProps & { href: string }) {
  return (
    <Link
      href={href}
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors',
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        className,
      )}
    >
      {icon ? <span aria-hidden>{icon}</span> : null}
      {children}
    </Link>
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={clsx('h-3.5 w-3.5 animate-spin', className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

/* -------------------------------------------------------------------------- */
/* States                                                                    */
/* -------------------------------------------------------------------------- */

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('skeleton', className)} aria-hidden />
}

export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={clsx('space-y-2', className)} aria-hidden>
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton key={index} className={clsx('h-3', index === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  )
}

export function LoadingBlock({ label, rows = 3 }: { label: string; rows?: number }) {
  return (
    <div role="status" aria-live="polite" className="space-y-3">
      <span className="sr-only">{label}</span>
      <SkeletonText lines={rows} />
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode
  title: string
  description: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('flex flex-col items-center justify-center px-6 py-12 text-center', className)}>
      {icon ? (
        <div className="mb-3 grid h-11 w-11 place-items-center rounded-xl bg-surface-sunken text-ink-muted ring-1 ring-inset ring-[var(--line)]">
          {icon}
        </div>
      ) : null}
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      <p className="mt-1.5 max-w-sm text-[13px] text-ink-secondary">{description}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: { code?: string; message: string; problems?: Array<{ field: string; message: string }> }
  onRetry?: () => void
  className?: string
}) {
  const problems = error.problems ?? []
  return (
    <div
      role="alert"
      className={clsx(
        'rounded-card border border-[color-mix(in_srgb,var(--status-critical)_35%,transparent)]',
        'bg-[color-mix(in_srgb,var(--status-critical)_8%,transparent)] px-4 py-3.5',
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-[var(--status-critical)]" />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-ink">{error.message}</p>
          {error.code ? (
            <p className="mt-0.5 font-mono text-[11px] text-ink-muted">{error.code}</p>
          ) : null}
          {problems.length > 0 ? (
            <ul className="mt-2 space-y-1 text-[12px] text-ink-secondary">
              {problems.map((problem, index) => (
                <li key={index}>
                  {problem.field ? <span className="font-mono text-ink-muted">{problem.field}: </span> : null}
                  {problem.message}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        {onRetry ? (
          <Button size="sm" variant="secondary" onClick={onRetry}>
            Retry
          </Button>
        ) : null}
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Data display                                                              */
/* -------------------------------------------------------------------------- */

export function StatTile({
  label,
  value,
  hint,
  tone = 'neutral',
  icon,
  href,
  emphasis = false,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: Tone
  icon?: ReactNode
  href?: string
  emphasis?: boolean
}) {
  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <span className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted">
          {label}
        </span>
        {icon ? <span aria-hidden className="text-ink-muted">{icon}</span> : null}
      </div>
      <div
        className={clsx(
          'mt-2 font-semibold tabular-nums tracking-[-0.02em]',
          emphasis ? 'text-[30px] leading-none' : 'text-[24px] leading-none',
          tone === 'critical' && 'text-[var(--status-critical)]',
          tone === 'serious' && 'text-[var(--status-serious)]',
          tone === 'warning' && 'text-[color-mix(in_srgb,var(--status-warning)_85%,var(--ink))]',
          tone === 'good' && 'text-[var(--status-good)]',
          tone === 'accent' && 'text-accent',
          (tone === 'neutral' || tone === 'muted') && 'text-ink',
        )}
      >
        {value}
      </div>
      {hint ? <div className="mt-1.5 text-[11.5px] leading-tight text-ink-muted">{hint}</div> : null}
    </>
  )

  const classes =
    'glass rounded-card px-4 py-3.5 transition-colors' + (href ? ' hover:bg-[var(--glass-bg-strong)]' : '')

  if (href) {
    return (
      <Link href={href} className={classes}>
        <div className="relative z-1">{body}</div>
      </Link>
    )
  }
  return (
    <div className={classes}>
      <div className="relative z-1">{body}</div>
    </div>
  )
}

export function KeyValue({
  label,
  value,
  mono = false,
}: {
  label: string
  value: ReactNode
  mono?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-[var(--line)] py-2 last:border-0">
      <dt className="shrink-0 text-[12px] text-ink-muted">{label}</dt>
      <dd className={clsx('min-w-0 text-right text-[13px] text-ink', mono && 'font-mono text-[12px]')}>
        {value}
      </dd>
    </div>
  )
}

export function ProgressBar({
  value,
  tone = 'accent',
  label,
  className,
}: {
  value: number
  tone?: Tone
  label?: string
  className?: string
}) {
  const clamped = Math.max(0, Math.min(100, value))
  const colour =
    tone === 'critical'
      ? 'var(--status-critical)'
      : tone === 'good'
        ? 'var(--status-good)'
        : tone === 'warning'
          ? 'var(--status-warning)'
          : tone === 'muted'
            ? 'var(--ink-muted)'
            : 'var(--accent)'
  return (
    <div
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? 'Progress'}
      className={clsx('h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken', className)}
    >
      <div
        className="h-full rounded-full transition-[width] duration-500 ease-out"
        style={{ width: `${clamped}%`, background: colour }}
      />
    </div>
  )
}

export function Table({
  head,
  children,
  className,
}: {
  head: ReactNode[]
  children: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('overflow-x-auto', className)}>
      <table className="w-full min-w-[640px] border-collapse text-[13px]">
        <thead>
          <tr>
            {head.map((cell, index) => (
              <th
                key={index}
                scope="col"
                className="border-b border-[var(--line-strong)] px-3 py-2 text-left font-mono text-[10px] font-medium uppercase tracking-[0.1em] text-ink-muted whitespace-nowrap"
              >
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

export function Row({
  children,
  className,
  onClick,
}: {
  children: ReactNode
  className?: string
  onClick?: () => void
}) {
  return (
    <tr
      onClick={onClick}
      className={clsx(
        'border-b border-[var(--line)] last:border-0',
        onClick && 'cursor-pointer hover:bg-surface-sunken',
        className,
      )}
    >
      {children}
    </tr>
  )
}

export function Cell({
  children,
  className,
  mono = false,
  numeric = false,
}: {
  children: ReactNode
  className?: string
  mono?: boolean
  numeric?: boolean
}) {
  return (
    <td
      className={clsx(
        'px-3 py-2.5 align-middle text-ink-secondary',
        mono && 'font-mono text-[12px]',
        numeric && 'text-right tabular-nums',
        className,
      )}
    >
      {children}
    </td>
  )
}

export function Pagination({
  total,
  limit,
  offset,
  onChange,
  label,
}: {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
  label: string
}) {
  if (total === 0) return null
  const from = offset + 1
  const to = Math.min(offset + limit, total)
  const hasPrevious = offset > 0
  const hasNext = to < total

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[var(--line)] px-3 py-2.5">
      <p className="text-[12px] text-ink-muted">
        {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()} {label}
      </p>
      <div className="flex items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={!hasPrevious}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          Previous
        </Button>
        <Button size="sm" variant="secondary" disabled={!hasNext} onClick={() => onChange(offset + limit)}>
          Next
        </Button>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Icons — inline so there is no icon-font dependency                        */
/* -------------------------------------------------------------------------- */

type IconProps = { className?: string }

function icon(path: ReactNode, viewBox = '0 0 24 24') {
  return function Icon({ className }: IconProps) {
    return (
      <svg
        viewBox={viewBox}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={clsx('h-4 w-4', className)}
        aria-hidden
      >
        {path}
      </svg>
    )
  }
}

export const AlertIcon = icon(
  <>
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
    <path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
  </>,
)
export const CheckIcon = icon(<path d="m5 13 4 4L19 7" />)
export const CrossIcon = icon(
  <>
    <path d="M18 6 6 18" />
    <path d="m6 6 12 12" />
  </>,
)
export const ClockIcon = icon(
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </>,
)
export const SpinIcon = icon(
  <>
    <path d="M12 3a9 9 0 1 0 9 9" />
  </>,
)
export const PauseIcon = icon(
  <>
    <path d="M10 5v14" />
    <path d="M14 5v14" />
  </>,
)
export const DashIcon = icon(<path d="M5 12h14" />)
export const SkipIcon = icon(
  <>
    <path d="M5 5l9 7-9 7z" />
    <path d="M19 5v14" />
  </>,
)
export const ArrowRightIcon = icon(
  <>
    <path d="M5 12h14" />
    <path d="m13 6 6 6-6 6" />
  </>,
)
export const ArrowDownIcon = icon(
  <>
    <path d="M12 5v14" />
    <path d="m6 13 6 6 6-6" />
  </>,
)
export const ArrowUpIcon = icon(
  <>
    <path d="M12 19V5" />
    <path d="m6 11 6-6 6 6" />
  </>,
)
export const SparkIcon = icon(
  <>
    <path d="M12 3v4" />
    <path d="M12 17v4" />
    <path d="M3 12h4" />
    <path d="M17 12h4" />
    <path d="m6.3 6.3 2.8 2.8" />
    <path d="m14.9 14.9 2.8 2.8" />
    <path d="m17.7 6.3-2.8 2.8" />
    <path d="m9.1 14.9-2.8 2.8" />
  </>,
)
export const GridIcon = icon(
  <>
    <rect x="3" y="3" width="7" height="7" rx="1.5" />
    <rect x="14" y="3" width="7" height="7" rx="1.5" />
    <rect x="3" y="14" width="7" height="7" rx="1.5" />
    <rect x="14" y="14" width="7" height="7" rx="1.5" />
  </>,
)
export const FlowIcon = icon(
  <>
    <circle cx="5" cy="6" r="2.2" />
    <circle cx="19" cy="6" r="2.2" />
    <circle cx="12" cy="18" r="2.2" />
    <path d="M5 8.2v3a2 2 0 0 0 2 2h3" />
    <path d="M19 8.2v3a2 2 0 0 1-2 2h-3" />
  </>,
)
export const UsersIcon = icon(
  <>
    <path d="M16 19v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 17.5V19" />
    <circle cx="10" cy="8" r="3.2" />
    <path d="M20 19v-1.5a3.5 3.5 0 0 0-2.6-3.4" />
    <path d="M15.5 5.2a3.2 3.2 0 0 1 0 5.6" />
  </>,
)
export const DocIcon = icon(
  <>
    <path d="M14 3v5h5" />
    <path d="M19 10v9a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7Z" />
    <path d="M9 13h6" />
    <path d="M9 17h4" />
  </>,
)
export const ShieldIcon = icon(
  <>
    <path d="M12 3 5 6v5.5c0 4.2 2.9 7.8 7 9.5 4.1-1.7 7-5.3 7-9.5V6l-7-3Z" />
    <path d="m9 12 2 2 4-4" />
  </>,
)
export const GaugeIcon = icon(
  <>
    <path d="M4 18a8 8 0 1 1 16 0" />
    <path d="m12 14 3.5-3.5" />
    <circle cx="12" cy="14" r="1.2" />
  </>,
)
export const PulseIcon = icon(<path d="M3 12h3l2.5-6 3.5 12 3-8 2 2h4" />)
export const SearchIcon = icon(
  <>
    <circle cx="11" cy="11" r="6.5" />
    <path d="m16 16 4.5 4.5" />
  </>,
)
export const LinkIcon = icon(
  <>
    <path d="M9.5 14.5 14.5 9.5" />
    <path d="M12.5 7.5 14 6a3.5 3.5 0 0 1 5 5l-1.5 1.5" />
    <path d="M11.5 16.5 10 18a3.5 3.5 0 0 1-5-5L6.5 11.5" />
  </>,
)
export const DownloadIcon = icon(
  <>
    <path d="M12 4v10" />
    <path d="m7.5 10.5 4.5 4.5 4.5-4.5" />
    <path d="M5 19h14" />
  </>,
)
export const SunIcon = icon(
  <>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" />
  </>,
)
export const MoonIcon = icon(<path d="M20 13.5A8 8 0 0 1 10.5 4a8 8 0 1 0 9.5 9.5Z" />)
export const MenuIcon = icon(
  <>
    <path d="M4 7h16" />
    <path d="M4 12h16" />
    <path d="M4 17h16" />
  </>,
)
