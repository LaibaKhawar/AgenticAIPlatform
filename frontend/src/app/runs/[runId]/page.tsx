'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { VerificationSplit } from '@/components/charts/charts'
import { InvestigationCard } from '@/components/runs/InvestigationCard'
import { StageTimeline } from '@/components/runs/StageTimeline'
import {
  AlertIcon,
  ArrowRightIcon,
  Badge,
  Button,
  Cell,
  DocIcon,
  EmptyState,
  ErrorState,
  GlassPanel,
  KeyValue,
  LinkButton,
  Panel,
  ProgressBar,
  Row,
  SectionHeader,
  ShieldIcon,
  Skeleton,
  SkeletonText,
  Table,
} from '@/components/ui/primitives'
import { LiveDot, RunStatusBadge, TaskStatusBadge } from '@/components/ui/status'
import { ApiError, api, isRunActive } from '@/lib/api'
import { useApi } from '@/lib/hooks'
import {
  formatCost,
  formatDateTime,
  formatDuration,
  formatMillis,
  formatNumber,
  formatTime,
  formatTokens,
  humanise,
} from '@/lib/format'

type Tab = 'overview' | 'results' | 'tasks' | 'audit'

export default function RunDetailPage() {
  const params = useParams<{ runId: string }>()
  const runId = params.runId
  const [tab, setTab] = useState<Tab>('overview')
  const [cancelling, setCancelling] = useState(false)
  const [actionError, setActionError] = useState<ApiError | null>(null)

  const run = useApi((signal) => api.run(runId, signal), [runId], { intervalMs: 3_000, enabled: Boolean(runId) })
  const active = run.data ? isRunActive(run.data.run.status) : false

  const investigations = useApi(
    (signal) => api.investigations(runId, signal),
    [runId],
    { intervalMs: active ? 5_000 : 0, enabled: Boolean(runId) },
  )

  async function cancel() {
    setCancelling(true)
    setActionError(null)
    try {
      await api.cancelRun(runId)
      run.refresh()
    } catch (caught) {
      setActionError(
        caught instanceof ApiError ? caught : new ApiError(0, 'unexpected_error', String(caught)),
      )
    } finally {
      setCancelling(false)
    }
  }

  if (run.error) {
    return (
      <div className="space-y-4">
        <h1 className="text-[22px] font-semibold text-ink">Investigation</h1>
        <ErrorState error={run.error} onRetry={run.refresh} />
        <LinkButton href="/runs" variant="secondary" size="sm">
          Back to all runs
        </LinkButton>
      </div>
    )
  }

  if (run.initialLoading || !run.data) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-24 rounded-card" />
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-72 rounded-card lg:col-span-2" />
          <Skeleton className="h-72 rounded-card" />
        </div>
      </div>
    )
  }

  const detail = run.data
  const { run: meta } = detail
  const pendingApprovals = detail.approvals.filter((approval) => approval.status === 'PENDING')
  const verification = detail.verification
  const canCancel = !['COMPLETED', 'FAILED', 'CANCELLED'].includes(meta.status)

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="mb-1.5 flex items-center gap-2">
            <Link href="/runs" className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted hover:text-ink">
              Investigations
            </Link>
            <span aria-hidden className="text-ink-muted">/</span>
            <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted">Run</span>
          </div>
          <h1 className="max-w-3xl text-[20px] font-semibold leading-snug tracking-[-0.02em] text-ink">
            {meta.objective}
          </h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-ink-muted">
            <span>{meta.id}</span>
            <span>{humanise(meta.workflow_type)}</span>
            <span>mode {meta.workflow_mode}</span>
            <span>by {meta.created_by}</span>
            <span>{formatDateTime(meta.created_at)}</span>
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {detail.has_report ? (
            <LinkButton
              href={`/reports/${meta.id}`}
              variant="primary"
              icon={<DocIcon className="h-3.5 w-3.5" />}
            >
              View report
            </LinkButton>
          ) : null}
          {canCancel ? (
            <Button variant="secondary" loading={cancelling} onClick={cancel}>
              Cancel run
            </Button>
          ) : null}
        </div>
      </div>

      {actionError ? <ErrorState error={actionError} /> : null}

      {/* Live status strip */}
      <GlassPanel className="px-4 py-3.5">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex items-center gap-2.5">
            <LiveDot active={active} />
            <RunStatusBadge status={meta.status} />
            <span className="text-[12.5px] capitalize text-ink-secondary">
              {meta.current_stage.replace(/_/g, ' ')}
            </span>
          </div>
          <div className="flex min-w-[180px] flex-1 items-center gap-3">
            <ProgressBar
              value={meta.progress}
              tone={
                meta.status === 'FAILED'
                  ? 'critical'
                  : meta.status === 'COMPLETED'
                    ? 'good'
                    : meta.status === 'WAITING_FOR_APPROVAL'
                      ? 'warning'
                      : 'accent'
              }
              label={`Run progress ${meta.progress}%`}
            />
            <span className="font-mono text-[11.5px] tabular-nums text-ink-secondary">{meta.progress}%</span>
          </div>
          <dl className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-[11px]">
            <Bit label="Accounts" value={formatNumber(meta.investigation_count)} />
            <Bit label="Duration" value={formatDuration(meta.duration_seconds)} />
            {detail.llm_usage ? (
              <>
                <Bit label="LLM calls" value={formatNumber(detail.llm_usage.calls)} />
                <Bit label="Tokens" value={formatTokens(detail.llm_usage.total_tokens)} />
                <Bit label="Cost" value={formatCost(detail.llm_usage.estimated_cost_usd)} />
              </>
            ) : null}
          </dl>
          {active ? (
            <span className="font-mono text-[10.5px] text-ink-muted">refreshing every 3s</span>
          ) : null}
        </div>

        {meta.status === 'RETRYING' ? (
          <p className="mt-3 rounded-md border border-[color-mix(in_srgb,var(--status-warning)_30%,transparent)] bg-[color-mix(in_srgb,var(--status-warning)_8%,transparent)] px-3 py-2 text-[12.5px] text-ink-secondary">
            A task hit a transient failure and is being retried with exponential backoff. No action is needed.
          </p>
        ) : null}

        {meta.status === 'FAILED' && meta.error_message ? (
          <div className="mt-3 rounded-md border border-[color-mix(in_srgb,var(--status-critical)_30%,transparent)] bg-[color-mix(in_srgb,var(--status-critical)_8%,transparent)] px-3 py-2">
            <p className="flex items-center gap-2 text-[12.5px] font-medium text-ink">
              <AlertIcon className="h-3.5 w-3.5 text-[var(--status-critical)]" />
              This run failed at the {meta.current_stage.replace(/_/g, ' ')} stage
            </p>
            <p className="mt-1 font-mono text-[11.5px] leading-snug text-ink-secondary">{meta.error_message}</p>
          </div>
        ) : null}
      </GlassPanel>

      {/* Pending approvals banner */}
      {pendingApprovals.length > 0 ? (
        <GlassPanel className="border-[color-mix(in_srgb,var(--status-warning)_35%,transparent)] px-4 py-3.5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-start gap-3">
              <ShieldIcon className="mt-0.5 h-4 w-4 shrink-0 text-[color-mix(in_srgb,var(--status-warning)_85%,var(--ink))]" />
              <div>
                <h3 className="text-[13px] font-semibold text-ink">
                  {pendingApprovals.length} sensitive action
                  {pendingApprovals.length === 1 ? '' : 's'} awaiting approval
                </h3>
                <p className="mt-0.5 max-w-2xl text-[12.5px] text-ink-secondary">
                  The run is paused and nothing has been sent, changed or offered to any customer. It
                  resumes once every request is approved or rejected.
                </p>
              </div>
            </div>
            <LinkButton
              href={`/approvals?run_id=${meta.id}`}
              variant="primary"
              size="sm"
              icon={<ArrowRightIcon className="h-3.5 w-3.5" />}
            >
              Review approvals
            </LinkButton>
          </div>
        </GlassPanel>
      ) : null}

      {/* Tabs */}
      <nav className="flex gap-1 border-b border-[var(--line)]" aria-label="Run detail sections">
        {(
          [
            ['overview', 'Overview'],
            ['results', `Results${investigations.data ? ` (${investigations.data.length})` : ''}`],
            ['tasks', `Tasks (${detail.tasks.length})`],
            ['audit', `Audit trail (${detail.events.length})`],
          ] as Array<[Tab, string]>
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-current={tab === id ? 'page' : undefined}
            onClick={() => setTab(id)}
            className={
              tab === id
                ? '-mb-px border-b-2 border-accent px-3 py-2 text-[13px] font-medium text-ink'
                : '-mb-px border-b-2 border-transparent px-3 py-2 text-[13px] text-ink-secondary hover:text-ink'
            }
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === 'overview' ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <Panel className="p-4 lg:col-span-2">
            <SectionHeader
              eyebrow="Execution"
              title="Workflow stages"
              description="Derived from persisted task state — not an animation."
            />
            <div className="mt-4">
              <StageTimeline stages={detail.stages} />
            </div>
          </Panel>

          <div className="space-y-4">
            <Panel className="p-4">
              <SectionHeader eyebrow="Trust" title="Verification" />
              <div className="mt-3">
                {verification && verification.total > 0 ? (
                  <>
                    <VerificationSplit
                      counts={{
                        supported: verification.counts.SUPPORTED ?? 0,
                        partial: verification.counts.PARTIALLY_SUPPORTED ?? 0,
                        rejected:
                          (verification.counts.UNSUPPORTED ?? 0) + (verification.counts.CONTRADICTED ?? 0),
                        pending: verification.counts.PENDING ?? 0,
                      }}
                      total={verification.total}
                    />
                    <p className="mt-3 text-[11.5px] leading-snug text-ink-muted">
                      {verification.counts.UNSUPPORTED || verification.counts.CONTRADICTED
                        ? 'Rejected claims are listed on each account card and excluded from the report.'
                        : 'Every material claim was supported by its cited evidence.'}
                    </p>
                  </>
                ) : (
                  <p className="text-[12.5px] text-ink-muted">
                    Claims appear here once the investigation and verification stages have run.
                  </p>
                )}
              </div>
            </Panel>

            <Panel className="p-4">
              <SectionHeader eyebrow="Scope" title="Parameters" />
              <dl className="mt-2">
                {Object.entries(detail.parameters).map(([key, value]) => (
                  <KeyValue
                    key={key}
                    label={key.replace(/_/g, ' ')}
                    value={value === null ? 'any' : String(value)}
                    mono
                  />
                ))}
              </dl>
            </Panel>

            {detail.plan ? (
              <Panel className="p-4">
                <SectionHeader
                  eyebrow="Planner"
                  title="Validated plan"
                  description={`${detail.plan.tasks.length} tasks`}
                />
                {detail.plan.reasoning ? (
                  <p className="mt-2 rounded-md bg-surface-sunken p-2.5 text-[11.5px] leading-snug text-ink-secondary">
                    {detail.plan.reasoning}
                  </p>
                ) : null}
                <ol className="mt-2.5 space-y-1.5">
                  {detail.plan.tasks.map((task) => (
                    <li key={task.id} className="font-mono text-[11px]">
                      <span className="text-ink">{task.id}</span>
                      <span className="text-ink-muted"> · {task.agent}</span>
                      {task.dependencies.length > 0 ? (
                        <span className="text-ink-muted"> ← {task.dependencies.join(', ')}</span>
                      ) : null}
                    </li>
                  ))}
                </ol>
              </Panel>
            ) : null}
          </div>
        </div>
      ) : null}

      {tab === 'results' ? (
        <div className="space-y-4">
          {investigations.error ? <ErrorState error={investigations.error} onRetry={investigations.refresh} /> : null}
          {investigations.initialLoading ? (
            <Panel className="p-4">
              <SkeletonText lines={5} />
            </Panel>
          ) : !investigations.data || investigations.data.length === 0 ? (
            <Panel>
              <EmptyState
                icon={<ShieldIcon />}
                title={
                  isRunActive(meta.status)
                    ? 'Investigations are still running'
                    : 'No account crossed the risk threshold'
                }
                description={
                  isRunActive(meta.status)
                    ? 'Account investigations execute concurrently. Results appear here as each one finishes.'
                    : 'The deterministic screen found no account above the configured threshold. That is a valid outcome — the report states it explicitly.'
                }
                action={
                  detail.has_report ? (
                    <LinkButton href={`/reports/${meta.id}`} variant="secondary" size="sm">
                      Read the report
                    </LinkButton>
                  ) : undefined
                }
              />
            </Panel>
          ) : (
            investigations.data.map((investigation) => (
              <InvestigationCard key={investigation.id} investigation={investigation} />
            ))
          )}
        </div>
      ) : null}

      {tab === 'tasks' ? (
        <Panel>
          <Table head={['Task', 'Agent', 'Stage', 'Status', 'Dependencies', 'Retries', 'Duration', 'Error']}>
            {detail.tasks.map((task) => (
              <Row key={task.id}>
                <Cell mono className="text-ink">
                  {task.task_key}
                </Cell>
                <Cell>
                  <Badge tone="muted">{task.agent_type}</Badge>
                </Cell>
                <Cell className="whitespace-nowrap capitalize">{task.stage.replace(/_/g, ' ')}</Cell>
                <Cell>
                  <TaskStatusBadge status={task.status} />
                </Cell>
                <Cell mono className="max-w-[16rem] truncate text-ink-muted">
                  {task.dependencies.length ? task.dependencies.join(', ') : '—'}
                </Cell>
                <Cell numeric>
                  {task.retry_count > 0 ? (
                    <span className="text-[color-mix(in_srgb,var(--status-warning)_82%,var(--ink))]">
                      {task.retry_count}/{task.max_retries}
                    </span>
                  ) : (
                    <span className="text-ink-muted">0</span>
                  )}
                </Cell>
                <Cell numeric className="whitespace-nowrap">
                  {formatMillis(task.duration_ms)}
                </Cell>
                <Cell className="max-w-[20rem]">
                  {task.error_message ? (
                    <span className="block truncate font-mono text-[11px] text-[color-mix(in_srgb,var(--status-critical)_90%,var(--ink))]" title={task.error_message}>
                      {task.error_message}
                    </span>
                  ) : (
                    <span className="text-ink-muted">—</span>
                  )}
                </Cell>
              </Row>
            ))}
          </Table>
        </Panel>
      ) : null}

      {tab === 'audit' ? (
        <Panel className="p-4">
          <SectionHeader
            eyebrow="Provenance"
            title="Audit trail"
            description="Every state change, tool call, verification verdict and human decision, in order."
          />
          <ol className="mt-4 space-y-2.5">
            {detail.events.map((event) => (
              <li key={event.id} className="flex gap-3">
                <time className="w-20 shrink-0 pt-0.5 font-mono text-[10.5px] tabular-nums text-ink-muted">
                  {formatTime(event.created_at)}
                </time>
                <div className="min-w-0 flex-1 border-b border-[var(--line)] pb-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[10.5px] font-medium text-ink">{event.event_type}</span>
                    <Badge tone="muted">{event.actor_id}</Badge>
                    <span className="font-mono text-[10px] text-ink-muted">{event.actor_type.toLowerCase()}</span>
                  </div>
                  <p className="mt-1 text-[12.5px] leading-snug text-ink-secondary">{event.message}</p>
                </div>
              </li>
            ))}
          </ol>
          {detail.events.length === 0 ? (
            <p className="mt-3 text-[12.5px] text-ink-muted">No audit events recorded yet.</p>
          ) : null}
        </Panel>
      ) : null}
    </div>
  )
}

function Bit({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="font-medium tabular-nums text-ink">{value}</dd>
    </div>
  )
}
