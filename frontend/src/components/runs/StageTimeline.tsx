'use client'

import clsx from 'clsx'
import { StageStatusBadge } from '@/components/ui/status'
import { formatMillis } from '@/lib/format'
import type { RunStage } from '@/lib/types'

const DOT: Record<string, string> = {
  COMPLETED: 'bg-[var(--status-good)]',
  RUNNING: 'bg-accent',
  QUEUED: 'bg-accent',
  RETRYING: 'bg-[var(--status-warning)]',
  WAITING_FOR_APPROVAL: 'bg-[var(--status-warning)]',
  PARTIAL: 'bg-[var(--status-warning)]',
  FAILED: 'bg-[var(--status-critical)]',
  CANCELLED: 'bg-[var(--ink-muted)]',
  SKIPPED: 'bg-[var(--ink-muted)]',
  PENDING: 'bg-[var(--line-strong)]',
}

/**
 * The run's stage timeline, derived from real task state on the server — not a
 * script that advances on a timer. A stage with no tasks reads PENDING, a stage
 * whose tasks failed reads FAILED, and the failing stage shows its error.
 */
export function StageTimeline({ stages }: { stages: RunStage[] }) {
  return (
    <ol className="relative space-y-0">
      {stages.map((stage, index) => {
        const last = index === stages.length - 1
        const live = stage.status === 'RUNNING'
        return (
          <li key={stage.key} className="relative flex gap-3 pb-4 last:pb-0">
            {!last ? (
              <span
                aria-hidden
                className="absolute left-[5px] top-4 h-full w-[1px] bg-[var(--line)]"
              />
            ) : null}
            <span className="relative mt-1.5 flex h-2.5 w-2.5 shrink-0">
              <span className={clsx('h-2.5 w-2.5 rounded-full', DOT[stage.status] ?? DOT.PENDING)} />
              {live ? (
                <span className="live-dot absolute inset-0 rounded-full bg-accent text-accent" />
              ) : null}
            </span>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                <span
                  className={clsx(
                    'text-[13px] font-medium',
                    stage.status === 'PENDING' ? 'text-ink-muted' : 'text-ink',
                  )}
                >
                  {stage.label}
                </span>
                <StageStatusBadge status={stage.status} />
                {stage.retry_count > 0 ? (
                  <span className="font-mono text-[10.5px] text-[color-mix(in_srgb,var(--status-warning)_80%,var(--ink))]">
                    {stage.retry_count} retr{stage.retry_count === 1 ? 'y' : 'ies'}
                  </span>
                ) : null}
                {stage.duration_ms ? (
                  <span className="font-mono text-[10.5px] tabular-nums text-ink-muted">
                    {formatMillis(stage.duration_ms)}
                  </span>
                ) : null}
              </div>

              {stage.task_count > 0 ? (
                <p className="mt-0.5 font-mono text-[10.5px] text-ink-muted">
                  {stage.task_count} task{stage.task_count === 1 ? '' : 's'}
                  {stage.tasks.length > 0 && stage.tasks.length <= 3
                    ? ` · ${stage.tasks.join(', ')}`
                    : ''}
                </p>
              ) : null}

              {stage.error ? (
                <p className="mt-1.5 rounded-md border border-[color-mix(in_srgb,var(--status-critical)_30%,transparent)] bg-[color-mix(in_srgb,var(--status-critical)_8%,transparent)] px-2.5 py-1.5 font-mono text-[11px] leading-snug text-[color-mix(in_srgb,var(--status-critical)_92%,var(--ink))]">
                  {stage.error}
                </p>
              ) : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
