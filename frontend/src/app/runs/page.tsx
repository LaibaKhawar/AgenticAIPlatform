'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'
import {
  Cell,
  EmptyState,
  ErrorState,
  FlowIcon,
  LinkButton,
  Pagination,
  Panel,
  ProgressBar,
  Row,
  Skeleton,
  SparkIcon,
  Table,
} from '@/components/ui/primitives'
import { LiveDot, RunStatusBadge } from '@/components/ui/status'
import { api, isRunActive } from '@/lib/api'
import { useApi } from '@/lib/hooks'
import { formatDuration, formatNumber, formatRelative, truncate } from '@/lib/format'
import type { RunStatus } from '@/lib/types'

const FILTERS: Array<{ value: RunStatus | ''; label: string }> = [
  { value: '', label: 'All' },
  { value: 'RUNNING', label: 'Running' },
  { value: 'WAITING_FOR_APPROVAL', label: 'Awaiting approval' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'CANCELLED', label: 'Cancelled' },
]

const PAGE_SIZE = 20

function RunsList() {
  const searchParams = useSearchParams()
  const initialStatus = (searchParams.get('status') ?? '') as RunStatus | ''
  const [status, setStatus] = useState<RunStatus | ''>(initialStatus)
  const [offset, setOffset] = useState(0)

  const { data, error, initialLoading, refresh } = useApi(
    (signal) => api.runs({ status: status || undefined, limit: PAGE_SIZE, offset }, signal),
    [status, offset],
    { intervalMs: 8_000 },
  )

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="mb-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
            Execution
          </div>
          <h1 className="text-[26px] font-semibold tracking-[-0.025em] text-ink">Investigations</h1>
          <p className="mt-1.5 max-w-2xl text-[13px] text-ink-secondary">
            Every run is a persisted workflow: its plan, tasks, retries, evidence, claims and approvals are
            all recoverable after the fact.
          </p>
        </div>
        <LinkButton href="/runs/new" variant="primary" icon={<SparkIcon className="h-4 w-4" />}>
          New investigation
        </LinkButton>
      </div>

      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter runs by status">
        {FILTERS.map((filter) => {
          const active = status === filter.value
          return (
            <button
              key={filter.value || 'all'}
              type="button"
              aria-pressed={active}
              onClick={() => {
                setStatus(filter.value)
                setOffset(0)
              }}
              className={
                active
                  ? 'rounded-full bg-accent-wash px-3 py-1 text-[12px] font-medium text-accent ring-1 ring-inset ring-[var(--accent-ring)]'
                  : 'rounded-full px-3 py-1 text-[12px] text-ink-secondary ring-1 ring-inset ring-[var(--line)] hover:bg-surface-sunken hover:text-ink'
              }
            >
              {filter.label}
            </button>
          )
        })}
      </div>

      {error ? <ErrorState error={error} onRetry={refresh} /> : null}

      <Panel>
        {initialLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-11" />
            ))}
          </div>
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            icon={<FlowIcon />}
            title={status ? `No ${status.toLowerCase().replace(/_/g, ' ')} runs` : 'No investigations yet'}
            description={
              status
                ? 'Try a different filter, or start a new investigation.'
                : 'Submit a business objective and the planner will build a task graph for the workers to execute.'
            }
            action={
              <LinkButton href="/runs/new" variant="primary" size="sm" icon={<SparkIcon className="h-3.5 w-3.5" />}>
                Start an investigation
              </LinkButton>
            }
          />
        ) : (
          <>
            <Table head={['Objective', 'Status', 'Stage', 'Progress', 'Accounts', 'Approvals', 'Duration', 'Created']}>
              {data.items.map((run) => (
                <Row key={run.id}>
                  <Cell className="max-w-[24rem]">
                    <Link href={`/runs/${run.id}`} className="group flex items-start gap-2">
                      <span className="mt-1.5">
                        <LiveDot active={isRunActive(run.status)} />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-ink group-hover:text-accent">
                          {truncate(run.objective, 96)}
                        </span>
                        <span className="block font-mono text-[10.5px] text-ink-muted">{run.id}</span>
                      </span>
                    </Link>
                  </Cell>
                  <Cell>
                    <RunStatusBadge status={run.status} />
                  </Cell>
                  <Cell className="whitespace-nowrap capitalize">
                    {run.current_stage.replace(/_/g, ' ')}
                  </Cell>
                  <Cell className="w-28">
                    <div className="flex items-center gap-2">
                      <ProgressBar
                        value={run.progress}
                        tone={
                          run.status === 'FAILED'
                            ? 'critical'
                            : run.status === 'COMPLETED'
                              ? 'good'
                              : run.status === 'WAITING_FOR_APPROVAL'
                                ? 'warning'
                                : 'accent'
                        }
                        label={`Progress ${run.progress}%`}
                        className="w-14"
                      />
                      <span className="font-mono text-[11px] tabular-nums text-ink-muted">{run.progress}%</span>
                    </div>
                  </Cell>
                  <Cell numeric>{formatNumber(run.investigation_count)}</Cell>
                  <Cell numeric>
                    {run.pending_approvals > 0 ? (
                      <Link
                        href={`/approvals?run_id=${run.id}`}
                        className="font-medium text-[color-mix(in_srgb,var(--status-warning)_80%,var(--ink))] hover:underline"
                      >
                        {run.pending_approvals} pending
                      </Link>
                    ) : (
                      <span className="text-ink-muted">—</span>
                    )}
                  </Cell>
                  <Cell numeric className="whitespace-nowrap">
                    {formatDuration(run.duration_seconds)}
                  </Cell>
                  <Cell className="whitespace-nowrap text-ink-muted">{formatRelative(run.created_at)}</Cell>
                </Row>
              ))}
            </Table>
            <Pagination
              total={data.total}
              limit={data.limit}
              offset={data.offset}
              onChange={setOffset}
              label="runs"
            />
          </>
        )}
      </Panel>
    </div>
  )
}

export default function RunsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 rounded-card" />}>
      <RunsList />
    </Suspense>
  )
}
