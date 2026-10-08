'use client'

import Link from 'next/link'
import { useState } from 'react'
import {
  DocIcon,
  EmptyState,
  ErrorState,
  LinkButton,
  Pagination,
  Panel,
  Skeleton,
  SparkIcon,
} from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { useApi } from '@/lib/hooks'
import { formatNumber, formatRelative, truncate } from '@/lib/format'

const PAGE_SIZE = 10

export default function ReportsPage() {
  const [offset, setOffset] = useState(0)
  const { data, error, initialLoading, refresh } = useApi(
    (signal) => api.reports({ limit: PAGE_SIZE, offset }, signal),
    [offset],
  )

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
          Output
        </div>
        <h1 className="text-[26px] font-semibold tracking-[-0.025em] text-ink">Reports</h1>
        <p className="mt-1.5 max-w-2xl text-[13px] text-ink-secondary">
          Each report is assembled from verified material only, and stored as both structured JSON and
          Markdown so it can be rendered, exported or diffed.
        </p>
      </div>

      {error ? <ErrorState error={error} onRetry={refresh} /> : null}

      {initialLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-28 rounded-card" />
          ))}
        </div>
      ) : !data || data.items.length === 0 ? (
        <Panel>
          <EmptyState
            icon={<DocIcon />}
            title="No reports yet"
            description="A report is produced at the end of every investigation — including when no account crosses the risk threshold, in which case it says so explicitly."
            action={
              <LinkButton href="/runs/new" variant="primary" size="sm" icon={<SparkIcon className="h-3.5 w-3.5" />}>
                Start an investigation
              </LinkButton>
            }
          />
        </Panel>
      ) : (
        <>
          <div className="space-y-3">
            {data.items.map((report) => (
              <Link key={report.id} href={`/reports/${report.run_id}`} className="block">
                <Panel className="p-4 transition-colors hover:border-[var(--line-strong)] hover:bg-surface-sunken">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h2 className="text-[14.5px] font-semibold tracking-[-0.01em] text-ink">
                        {report.title}
                      </h2>
                      <p className="mt-1 max-w-3xl text-[12.5px] leading-snug text-ink-secondary">
                        {truncate(report.executive_summary, 260)}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <div className="font-mono text-[11px] text-ink-muted">
                        {formatRelative(report.created_at)}
                      </div>
                      <div className="mt-1 text-[12px] font-medium text-ink">
                        {formatNumber(report.account_count)} account
                        {report.account_count === 1 ? '' : 's'}
                      </div>
                    </div>
                  </div>
                  {report.objective ? (
                    <p className="mt-2.5 border-t border-[var(--line)] pt-2 font-mono text-[10.5px] text-ink-muted">
                      {truncate(report.objective, 150)}
                    </p>
                  ) : null}
                </Panel>
              </Link>
            ))}
          </div>
          <Panel>
            <Pagination
              total={data.total}
              limit={data.limit}
              offset={data.offset}
              onChange={setOffset}
              label="reports"
            />
          </Panel>
        </>
      )}
    </div>
  )
}
