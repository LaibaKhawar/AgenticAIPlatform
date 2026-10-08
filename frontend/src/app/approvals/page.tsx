'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'
import {
  AlertIcon,
  Badge,
  Button,
  CheckIcon,
  CrossIcon,
  EmptyState,
  ErrorState,
  GlassPanel,
  Panel,
  SectionHeader,
  ShieldIcon,
  Skeleton,
  StatTile,
} from '@/components/ui/primitives'
import { ApprovalStatusBadge } from '@/components/ui/status'
import { ApiError, api } from '@/lib/api'
import { useApi, useLocalValue } from '@/lib/hooks'
import { formatDateTime, formatRelative, humanise, truncate } from '@/lib/format'
import type { Approval, ApprovalStatus } from '@/lib/types'

const FILTERS: Array<{ value: ApprovalStatus | ''; label: string }> = [
  { value: 'PENDING', label: 'Pending' },
  { value: 'APPROVED', label: 'Approved' },
  { value: 'REJECTED', label: 'Rejected' },
  { value: '', label: 'All' },
]

function ApprovalsList() {
  const searchParams = useSearchParams()
  const runFilter = searchParams.get('run_id') ?? ''
  const [status, setStatus] = useState<ApprovalStatus | ''>('PENDING')
  const [reviewer, setReviewer] = useLocalValue('veriflow-reviewer', 'operator')
  const [active, setActive] = useState<Approval | null>(null)

  const { data, error, initialLoading, refresh } = useApi(
    (signal) =>
      api.approvals({ status: status || undefined, run_id: runFilter || undefined, limit: 50 }, signal),
    [status, runFilter],
    { intervalMs: 15_000 },
  )

  const pending = data?.items.filter((item) => item.status === 'PENDING') ?? []

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
          Human in the loop
        </div>
        <h1 className="text-[26px] font-semibold tracking-[-0.025em] text-ink">Approvals</h1>
        <p className="mt-1.5 max-w-3xl text-[13px] text-ink-secondary">
          Sensitive actions never execute automatically. Whether an action needs approval is decided by
          deterministic application policy — a model proposes an action type, it never decides that review
          can be skipped.
        </p>
      </div>

      {runFilter ? (
        <div className="flex items-center gap-2 text-[12.5px] text-ink-secondary">
          <span>
            Filtered to run <span className="font-mono text-ink">{runFilter}</span>
          </span>
          <Link href="/approvals" className="text-accent hover:underline">
            Clear filter
          </Link>
        </div>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile
          label="Awaiting review"
          value={status === 'PENDING' ? (data?.total ?? 0) : pending.length}
          hint="runs are paused until each is resolved"
          tone={(data?.total ?? 0) > 0 && status === 'PENDING' ? 'warning' : 'neutral'}
          icon={<ShieldIcon className="h-3.5 w-3.5" />}
          emphasis
        />
        <StatTile
          label="Reviewing as"
          value={<span className="text-[18px]">{reviewer || 'operator'}</span>}
          hint="recorded on every decision in the audit trail"
        />
        <GlassPanel className="px-4 py-3.5">
          <label
            htmlFor="reviewer"
            className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-ink-muted"
          >
            Reviewer name
          </label>
          <input
            id="reviewer"
            value={reviewer}
            onChange={(event) => setReviewer(event.target.value)}
            placeholder="your name"
            className="mt-2 h-9 w-full rounded-lg border border-[var(--line-strong)] bg-surface-sunken px-3 text-[13px] text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
          />
        </GlassPanel>
      </div>

      <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter approvals by status">
        {FILTERS.map((filter) => {
          const selected = status === filter.value
          return (
            <button
              key={filter.value || 'all'}
              type="button"
              aria-pressed={selected}
              onClick={() => setStatus(filter.value)}
              className={
                selected
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

      {initialLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-32 rounded-card" />
          ))}
        </div>
      ) : !data || data.items.length === 0 ? (
        <Panel>
          <EmptyState
            icon={<CheckIcon />}
            title={status === 'PENDING' ? 'Nothing to review' : 'No approval records'}
            description={
              status === 'PENDING'
                ? 'No run is waiting on a human. When an investigation recommends a customer-facing or commercial action, it appears here and the run pauses.'
                : 'Approval records appear once a run has reached its approval stage.'
            }
          />
        </Panel>
      ) : (
        <div className="space-y-3">
          {data.items.map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              reviewer={reviewer}
              onReviewed={refresh}
              onOpen={() => setActive(approval)}
            />
          ))}
        </div>
      )}

      {active ? (
        <ApprovalDialog
          approval={active}
          reviewer={reviewer}
          onClose={() => setActive(null)}
          onReviewed={() => {
            setActive(null)
            refresh()
          }}
        />
      ) : null}
    </div>
  )
}

function ApprovalCard({
  approval,
  reviewer,
  onReviewed,
  onOpen,
}: {
  approval: Approval
  reviewer: string
  onReviewed: () => void
  onOpen: () => void
}) {
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const pending = approval.status === 'PENDING'
  const payload = approval.action_payload as {
    risk_score?: number
    risk_level?: string
    rationale?: string
    priority?: number
  }

  async function decide(decision: 'approve' | 'reject') {
    setBusy(decision)
    setError(null)
    try {
      if (decision === 'approve') await api.approve(approval.id, { reviewed_by: reviewer || 'operator' })
      else await api.reject(approval.id, { reviewed_by: reviewer || 'operator' })
      onReviewed()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, 'unexpected_error', String(caught)))
    } finally {
      setBusy(null)
    }
  }

  return (
    <GlassPanel className="px-4 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[11.5px] font-semibold text-ink">{approval.action_type}</span>
            <ApprovalStatusBadge status={approval.status} />
            {approval.customer_id ? (
              <span className="text-[12.5px] text-ink-secondary">{approval.company_name}</span>
            ) : null}
            {payload.risk_level ? (
              <Badge tone={payload.risk_level === 'CRITICAL' ? 'critical' : 'serious'}>
                {payload.risk_level}
                {payload.risk_score !== undefined ? ` · ${payload.risk_score.toFixed(0)}` : ''}
              </Badge>
            ) : null}
            {payload.priority ? (
              <span className="font-mono text-[10.5px] text-ink-muted">priority {payload.priority}</span>
            ) : null}
          </div>

          <p className="mt-2 text-[13.5px] font-medium leading-snug text-ink">{approval.proposed_action}</p>

          {payload.rationale ? (
            <p className="mt-1 text-[12px] leading-snug text-ink-secondary">{payload.rationale}</p>
          ) : null}

          <p className="mt-2 flex items-start gap-2 text-[11.5px] leading-snug text-ink-muted">
            <ShieldIcon className="mt-0.5 h-3 w-3 shrink-0" />
            {approval.reason}
          </p>

          <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.5px] text-ink-muted">
            <Link href={`/runs/${approval.run_id}`} className="text-accent hover:underline">
              run {approval.run_id.slice(0, 8)}
            </Link>
            <span>requested {formatRelative(approval.requested_at)}</span>
            {approval.reviewed_at ? (
              <span>
                {humanise(approval.status)} by {approval.reviewed_by} · {formatDateTime(approval.reviewed_at)}
              </span>
            ) : null}
          </p>

          {approval.reviewer_comment ? (
            <p className="mt-2 rounded-md bg-surface-sunken px-2.5 py-1.5 text-[12px] italic text-ink-secondary">
              “{approval.reviewer_comment}”
            </p>
          ) : null}

          {approval.run_objective ? (
            <p className="mt-2 text-[11.5px] text-ink-muted">{truncate(approval.run_objective, 150)}</p>
          ) : null}
        </div>

        {pending ? (
          <div className="flex shrink-0 flex-col gap-2 sm:flex-row sm:items-start">
            <Button
              variant="success"
              size="sm"
              loading={busy === 'approve'}
              disabled={busy !== null}
              onClick={() => decide('approve')}
              icon={busy === 'approve' ? undefined : <CheckIcon className="h-3.5 w-3.5" />}
            >
              Approve
            </Button>
            <Button
              variant="danger"
              size="sm"
              loading={busy === 'reject'}
              disabled={busy !== null}
              onClick={() => decide('reject')}
              icon={busy === 'reject' ? undefined : <CrossIcon className="h-3.5 w-3.5" />}
            >
              Reject
            </Button>
            <Button variant="ghost" size="sm" onClick={onOpen}>
              Add comment
            </Button>
          </div>
        ) : null}
      </div>

      {error ? (
        <div className="mt-3">
          <ErrorState error={error} />
        </div>
      ) : null}
    </GlassPanel>
  )
}

function ApprovalDialog({
  approval,
  reviewer,
  onClose,
  onReviewed,
}: {
  approval: Approval
  reviewer: string
  onClose: () => void
  onReviewed: () => void
}) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<ApiError | null>(null)

  async function decide(decision: 'approve' | 'reject') {
    setBusy(decision)
    setError(null)
    try {
      const body = { reviewed_by: reviewer || 'operator', comment: comment.trim() || null }
      if (decision === 'approve') await api.approve(approval.id, body)
      else await api.reject(approval.id, body)
      onReviewed()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, 'unexpected_error', String(caught)))
      setBusy(null)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Review sensitive action"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
    >
      <GlassPanel strong className="w-full max-w-lg">
        <div className="px-5 py-4">
          <SectionHeader
            eyebrow="Review required"
            title={approval.action_type}
            description={approval.proposed_action}
          />

          <div className="mt-3 flex items-start gap-2 rounded-md bg-surface-sunken px-3 py-2 text-[12px] text-ink-secondary">
            <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[color-mix(in_srgb,var(--status-warning)_85%,var(--ink))]" />
            <span>
              Nothing has been sent or changed. Approving records the decision and lets the workflow
              continue; rejecting records it and the action is not taken.
            </span>
          </div>

          <label htmlFor="comment" className="mt-4 block text-[12.5px] font-medium text-ink">
            Reviewer comment <span className="font-normal text-ink-muted">(optional)</span>
          </label>
          <textarea
            id="comment"
            rows={3}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={2000}
            placeholder="Why are you approving or rejecting this?"
            className="mt-1.5 w-full resize-y rounded-lg border border-[var(--line-strong)] bg-surface-sunken px-3 py-2 text-[13px] text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
          />

          {error ? (
            <div className="mt-3">
              <ErrorState error={error} />
            </div>
          ) : null}

          <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
            <Button variant="ghost" onClick={onClose} disabled={busy !== null}>
              Cancel
            </Button>
            <Button
              variant="danger"
              loading={busy === 'reject'}
              disabled={busy !== null}
              onClick={() => decide('reject')}
            >
              Reject
            </Button>
            <Button
              variant="success"
              loading={busy === 'approve'}
              disabled={busy !== null}
              onClick={() => decide('approve')}
            >
              Approve
            </Button>
          </div>
        </div>
      </GlassPanel>
    </div>
  )
}

export default function ApprovalsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 rounded-card" />}>
      <ApprovalsList />
    </Suspense>
  )
}
