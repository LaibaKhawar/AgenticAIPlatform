'use client'

import { useState } from 'react'
import { AlertIcon, Badge, ShieldIcon } from '@/components/ui/primitives'
import { formatDate, humanise } from '@/lib/format'
import type { EvidenceItem } from '@/lib/types'

/**
 * One evidence record, shown with full attribution: source type, source date,
 * the original content, and the relevance score when retrieval produced one.
 *
 * Document content is customer-authored and therefore untrusted. Where the
 * platform neutralised an instruction-like passage, that is stated on the card
 * rather than hidden — a reviewer should know the document tried it.
 */
export function EvidenceCard({ item, compact = false }: { item: EvidenceItem; compact?: boolean }) {
  const [expanded, setExpanded] = useState(false)
  const isMetric = item.source_type === 'USAGE_METRIC'
  const detections = Array.isArray(item.metadata?.injection_detections)
    ? (item.metadata.injection_detections as string[])
    : []
  const relevance = item.relevance_score
  const long = item.content.length > 320
  const body = expanded || !long ? item.content : `${item.content.slice(0, 320).trimEnd()}…`

  return (
    <article
      id={`evidence-${item.reference}`}
      className="scroll-mt-24 rounded-card border border-[var(--line)] bg-surface-sunken p-3"
    >
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <span className="rounded-md bg-accent-wash px-1.5 py-0.5 font-mono text-[11px] font-semibold text-accent">
          {item.reference}
        </span>
        <Badge tone={isMetric ? 'accent' : 'muted'} icon={isMetric ? <ShieldIcon className="h-3 w-3" /> : undefined}>
          {isMetric ? 'Computed metric' : humanise(item.source_type)}
        </Badge>
        <span className="font-mono text-[10.5px] text-ink-muted">{formatDate(item.source_date)}</span>
        {relevance !== null && relevance !== undefined ? (
          <span
            className="font-mono text-[10.5px] text-ink-muted"
            title="Cosine similarity between the retrieval query and this chunk. With the local deterministic embedder these values are small in absolute terms; the ranking is what carries meaning."
          >
            relevance {relevance.toFixed(3)}
          </span>
        ) : null}
        {detections.length > 0 ? (
          <Badge tone="critical" icon={<AlertIcon className="h-3 w-3" />} title={detections.join(', ')}>
            Injection attempt neutralised
          </Badge>
        ) : null}
      </header>

      {item.title && !compact ? (
        <p className="mb-1 text-[12.5px] font-medium text-ink">{item.title}</p>
      ) : null}

      <p className="whitespace-pre-line text-[12.5px] leading-relaxed text-ink-secondary">{body}</p>

      {long ? (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="mt-1.5 text-[11.5px] text-accent underline-offset-2 hover:underline"
        >
          {expanded ? 'Show less' : 'Show full source'}
        </button>
      ) : null}

      {!isMetric ? (
        <p className="mt-2 border-t border-[var(--line)] pt-1.5 font-mono text-[10px] text-ink-muted">
          Customer-authored content · treated as data, never as instructions
        </p>
      ) : null}
    </article>
  )
}
