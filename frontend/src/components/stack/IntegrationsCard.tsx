'use client'

/**
 * A titled grid of technology cards.
 *
 * Shaped after the integrations-card pattern (title + items, each with an
 * icon, small-caps "entities" line, description, tags, two footer stats and an
 * availability badge). Every value shown is real: the footer stats are the
 * version and where that version was read from, and the badge reflects what
 * the running system reported.
 */

import clsx from 'clsx'
import type { CSSProperties, ReactNode } from 'react'
import { useSpotlight } from '@/lib/motion'

export type AvailabilityTone = 'live' | 'down' | 'bundled' | 'dev' | 'unknown'

export interface IntegrationItem {
  id: string
  name: string
  /** Small-caps line under the name — here, where the technology runs. */
  entities: string
  description: string
  tags: string[]
  stats: Array<{ label: string; value: ReactNode }>
  availability: { tone: AvailabilityTone; label: string; title?: string }
  icon: ReactNode
  /** Brand variables (--brand, --mark-*, --tile-*) for the icon tile and hover rim. */
  accentStyle: CSSProperties
}

const AVAILABILITY_CLASSES: Record<AvailabilityTone, string> = {
  live: 'bg-[color-mix(in_srgb,var(--status-good)_16%,transparent)] text-[var(--status-good)] ring-[color-mix(in_srgb,var(--status-good)_40%,transparent)]',
  down: 'bg-[color-mix(in_srgb,var(--status-critical)_16%,transparent)] text-[color-mix(in_srgb,var(--status-critical)_92%,var(--ink))] ring-[color-mix(in_srgb,var(--status-critical)_45%,transparent)]',
  bundled: 'bg-accent-wash text-accent ring-[var(--accent-ring)]',
  dev: 'bg-surface-sunken text-ink-muted ring-[var(--line)]',
  unknown: 'bg-surface-sunken text-ink-muted ring-[var(--line)]',
}

function IntegrationTile({ item }: { item: IntegrationItem }) {
  const { onPointerMove } = useSpotlight<HTMLElement>()
  return (
    <article
      onPointerMove={onPointerMove}
      style={item.accentStyle}
      className="lift spotlight panel flex h-full flex-col rounded-card p-4 hover:border-[color-mix(in_srgb,var(--brand)_45%,var(--line))]"
    >
      <div className="relative z-1 flex items-start gap-3">
        <div
          aria-hidden
          className="brand-tile grid h-10 w-10 shrink-0 place-items-center rounded-xl ring-1 ring-inset ring-[color-mix(in_srgb,var(--brand)_28%,transparent)]"
        >
          {item.icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="truncate text-[14.5px] font-semibold tracking-[-0.01em] text-ink">{item.name}</h3>
            <span
              title={item.availability.title}
              className={clsx(
                'shrink-0 rounded-full px-2 py-0.5 text-[10.5px] font-medium whitespace-nowrap ring-1 ring-inset',
                AVAILABILITY_CLASSES[item.availability.tone],
              )}
            >
              {item.availability.label}
            </span>
          </div>
          <p className="mt-0.5 truncate font-mono text-[9.5px] tracking-[0.12em] text-ink-muted uppercase">
            {item.entities}
          </p>
        </div>
      </div>

      <p className="relative z-1 mt-3 flex-1 text-[12.5px] leading-relaxed text-ink-secondary">{item.description}</p>

      <ul className="relative z-1 mt-3 flex flex-wrap gap-1.5" aria-label="Tags">
        {item.tags.map((tag) => (
          <li
            key={tag}
            className="rounded-md bg-surface-sunken px-1.5 py-0.5 text-[10.5px] text-ink-muted ring-1 ring-inset ring-[var(--line)]"
          >
            {tag}
          </li>
        ))}
      </ul>

      {/* Pinned to the bottom so footers line up across a row of cards. */}
      <dl className="relative z-1 mt-4 grid grid-cols-2 gap-3 border-t border-[var(--line)] pt-3">
        {item.stats.map((stat) => (
          <div key={stat.label} className="min-w-0">
            <dt className="font-mono text-[9.5px] tracking-[0.12em] text-ink-muted uppercase">{stat.label}</dt>
            <dd className="num mt-0.5 truncate text-[12.5px] font-medium text-ink">{stat.value}</dd>
          </div>
        ))}
      </dl>
    </article>
  )
}

export function IntegrationsCard({
  title,
  description,
  items,
  actions,
}: {
  title: string
  description?: ReactNode
  items: IntegrationItem[]
  actions?: ReactNode
}) {
  return (
    <section aria-label={title}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-[-0.01em] text-ink">
            {title} <span className="num ml-1 text-[13px] font-medium text-ink-muted">{items.length}</span>
          </h2>
          {description ? <p className="mt-1 max-w-2xl text-[13px] text-ink-secondary">{description}</p> : null}
        </div>
        {actions}
      </div>
      <ul className="stagger grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <li key={item.id}>
            <IntegrationTile item={item} />
          </li>
        ))}
      </ul>
    </section>
  )
}
