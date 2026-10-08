'use client'

import Link from 'next/link'
import { VerificationSplit } from '@/components/charts/charts'
import {
  ArrowRightIcon,
  Cell,
  EmptyState,
  ErrorState,
  FlowIcon,
  GlassPanel,
  LinkButton,
  Panel,
  ProgressBar,
  Row,
  SectionHeader,
  ShieldIcon,
  Skeleton,
  SparkIcon,
  StatTile,
  Table,
  UsersIcon,
} from '@/components/ui/primitives'
import { LiveDot, RiskBadge, RunStatusBadge } from '@/components/ui/status'
import { api, isRunActive } from '@/lib/api'
import { config } from '@/lib/config'
import { useApi } from '@/lib/hooks'
import {
  formatCost,
  formatCurrency,
  formatDate,
  formatDuration,
  formatNumber,
  formatPercent,
  formatRelative,
  formatTokens,
  truncate,
} from '@/lib/format'
import type { RiskLevel } from '@/lib/types'

export default function DashboardPage() {
  const { data, error, initialLoading, refresh } = useApi((signal) => api.dashboard(signal), [], {
    intervalMs: 10_000,
  })

  if (error) {
    return (
      <div className="space-y-4">
        <PageIntro />
        <ErrorState error={error} onRetry={refresh} />
      </div>
    )
  }

  if (initialLoading || !data) {
    return (
      <div className="space-y-6">
        <PageIntro />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton key={index} className="h-[86px] rounded-card" />
          ))}
        </div>
        <Skeleton className="h-64 rounded-card" />
      </div>
    )
  }

  const claimTotal = data.verified_claim_pct === null ? 0 : 1
  const hasRuns = data.runs_total > 0
  const datasetEmpty = data.total_customers === 0

  return (
    <div className="space-y-7">
      <PageIntro />

      {datasetEmpty ? (
        <GlassPanel className="px-5 py-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h3 className="text-sm font-semibold text-ink">The warehouse is empty</h3>
              <p className="mt-1 max-w-xl text-[13px] text-ink-secondary">
                No customers are loaded, so there is nothing to investigate yet. Run{' '}
                <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11.5px]">make seed</code>{' '}
                to generate the synthetic dataset — 3,000 accounts with correlated churn scenarios.
              </p>
            </div>
          </div>
        </GlassPanel>
      ) : null}

      {/* Operational counters — every value comes from the database. */}
      <section aria-labelledby="operations">
        <h2 id="operations" className="sr-only">
          Operational metrics
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile
            label="Investigations completed"
            value={formatNumber(data.investigations_completed)}
            hint={`across ${formatNumber(data.runs_total)} run${data.runs_total === 1 ? '' : 's'}`}
            icon={<FlowIcon className="h-3.5 w-3.5" />}
            href="/runs"
            emphasis
          />
          <StatTile
            label="Currently running"
            value={formatNumber(data.runs_running)}
            hint={data.runs_running > 0 ? 'workers are executing tasks' : 'no work in flight'}
            tone={data.runs_running > 0 ? 'accent' : 'neutral'}
            href="/runs"
            emphasis
          />
          <StatTile
            label="Failed investigations"
            value={formatNumber(data.runs_failed)}
            hint={data.runs_failed > 0 ? 'open a run to see the failing stage' : 'none'}
            tone={data.runs_failed > 0 ? 'critical' : 'neutral'}
            href="/runs?status=FAILED"
            emphasis
          />
          <StatTile
            label="Pending approvals"
            value={formatNumber(data.pending_approvals)}
            hint={data.pending_approvals > 0 ? 'sensitive actions awaiting review' : 'nothing to review'}
            tone={data.pending_approvals > 0 ? 'warning' : 'neutral'}
            icon={<ShieldIcon className="h-3.5 w-3.5" />}
            href="/approvals"
            emphasis
          />
        </div>
      </section>

      {/* Quality + portfolio */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="High-risk customers"
          value={formatNumber(data.high_risk_customers)}
          hint="investigated at HIGH or CRITICAL"
          tone={data.high_risk_customers > 0 ? 'serious' : 'neutral'}
        />
        <StatTile
          label="Avg run duration"
          value={formatDuration(data.avg_run_duration_seconds)}
          hint={data.avg_run_duration_seconds === null ? 'no completed runs yet' : 'completed runs only'}
        />
        <StatTile
          label="Verified claims"
          value={data.verified_claim_pct === null ? '—' : formatPercent(data.verified_claim_pct, 1)}
          hint={claimTotal === 0 ? 'no claims produced yet' : 'fully supported by evidence'}
          tone={data.verified_claim_pct === null ? 'neutral' : 'good'}
        />
        <StatTile
          label="Unsupported claims"
          value={data.unsupported_claim_pct === null ? '—' : formatPercent(data.unsupported_claim_pct, 1)}
          hint={claimTotal === 0 ? 'no claims produced yet' : 'rejected before reaching a report'}
          tone={data.unsupported_claim_pct === null ? 'neutral' : 'critical'}
        />
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Recent runs */}
        <Panel className="lg:col-span-2">
          <div className="flex items-center justify-between gap-3 border-b border-[var(--line)] px-4 py-3">
            <SectionHeader eyebrow="Execution" title="Recent runs" />
            <LinkButton href="/runs" size="sm" variant="ghost" icon={<ArrowRightIcon className="h-3.5 w-3.5" />}>
              All runs
            </LinkButton>
          </div>
          {data.recent_runs.length === 0 ? (
            <EmptyState
              icon={<FlowIcon />}
              title="No investigations yet"
              description="Submit a business objective and the planner will turn it into a validated task graph that the workers execute."
              action={
                <LinkButton href="/runs/new" variant="primary" size="sm" icon={<SparkIcon className="h-3.5 w-3.5" />}>
                  Start an investigation
                </LinkButton>
              }
            />
          ) : (
            <Table head={['Objective', 'Status', 'Progress', 'Accounts', 'Started']}>
              {data.recent_runs.map((run) => (
                <Row key={run.id}>
                  <Cell className="max-w-[26rem]">
                    <Link href={`/runs/${run.id}`} className="group flex items-center gap-2">
                      <LiveDot active={isRunActive(run.status)} />
                      <span className="truncate text-ink group-hover:text-accent">
                        {truncate(run.objective, 90)}
                      </span>
                    </Link>
                  </Cell>
                  <Cell>
                    <RunStatusBadge status={run.status} />
                  </Cell>
                  <Cell className="w-28">
                    <div className="flex items-center gap-2">
                      <ProgressBar
                        value={run.progress}
                        tone={run.status === 'FAILED' ? 'critical' : run.status === 'COMPLETED' ? 'good' : 'accent'}
                        label={`Run progress ${run.progress}%`}
                        className="w-14"
                      />
                      <span className="font-mono text-[11px] tabular-nums text-ink-muted">{run.progress}%</span>
                    </div>
                  </Cell>
                  <Cell numeric>{formatNumber(run.investigation_count)}</Cell>
                  <Cell className="whitespace-nowrap text-ink-muted">{formatRelative(run.created_at)}</Cell>
                </Row>
              ))}
            </Table>
          )}
        </Panel>

        {/* Verification quality + platform */}
        <div className="space-y-4">
          <Panel className="p-4">
            <SectionHeader
              eyebrow="Trust"
              title="Claim verification"
              description={
                hasRuns
                  ? 'Only fully supported claims become asserted conclusions.'
                  : 'Verification statistics appear once a run has produced claims.'
              }
            />
            <div className="mt-4">
              <VerificationSplit
                counts={{
                  supported: Math.round(data.verified_claim_pct ?? 0),
                  partial: Math.round(data.partially_supported_claim_pct ?? 0),
                  rejected: Math.round(data.unsupported_claim_pct ?? 0),
                  pending: 0,
                }}
                total={data.verified_claim_pct === null ? 0 : 100}
              />
            </div>
            <dl className="mt-4 space-y-0 border-t border-[var(--line)] pt-1">
              <KeyRow label="Evidence records" value={formatNumber(data.evidence_records)} />
              <KeyRow label="Embedded chunks" value={formatNumber(data.embedded_chunks)} />
              <KeyRow label="LLM calls" value={formatNumber(data.llm_usage.calls)} />
              <KeyRow label="Tokens used" value={formatTokens(data.llm_usage.total_tokens)} />
              <KeyRow label="Estimated cost" value={formatCost(data.llm_usage.estimated_cost_usd)} />
              <KeyRow
                label="Model"
                value={
                  <span className="font-mono text-[11.5px]">
                    {data.llm_usage.provider === 'fake' ? 'deterministic (offline)' : data.llm_usage.model}
                  </span>
                }
              />
            </dl>
          </Panel>

          <Panel className="p-4">
            <SectionHeader eyebrow="Portfolio" title="Dataset" />
            <dl className="mt-3">
              <KeyRow label="Customers" value={formatNumber(data.total_customers)} />
              <KeyRow label="Renewing in 90 days" value={formatNumber(data.renewing_within_90_days)} />
              <KeyRow label="Documents" value={formatNumber(data.dataset.documents)} />
              <KeyRow label="Total ACV" value={formatCurrency(data.dataset.total_acv)} />
              {Object.entries(data.dataset.outcomes)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([outcome, count]) => (
                  <KeyRow key={outcome} label={outcome.toLowerCase()} value={formatNumber(count)} />
                ))}
            </dl>
          </Panel>
        </div>
      </div>

      {/* Highest-risk accounts */}
      <Panel>
        <div className="flex items-center justify-between gap-3 border-b border-[var(--line)] px-4 py-3">
          <SectionHeader
            eyebrow="Priority"
            title="Latest high-risk accounts"
            description="Accounts an investigation placed at HIGH or CRITICAL risk."
          />
          <LinkButton href="/customers" size="sm" variant="ghost" icon={<UsersIcon className="h-3.5 w-3.5" />}>
            All customers
          </LinkButton>
        </div>
        {data.high_risk_accounts.length === 0 ? (
          <EmptyState
            icon={<ShieldIcon />}
            title="No high-risk accounts identified"
            description={
              hasRuns
                ? 'No investigated account crossed the HIGH threshold. That is a valid result, not an empty state.'
                : 'Run an investigation and any account above the risk threshold will appear here.'
            }
          />
        ) : (
          <Table head={['Account', 'Tier', 'Risk', 'MRR', 'Renewal', 'Investigated']}>
            {data.high_risk_accounts.map((account) => (
              <Row key={`${account.run_id}-${account.customer_id}`}>
                <Cell>
                  <Link
                    href={`/customers/${account.external_id}`}
                    className="font-medium text-ink hover:text-accent"
                  >
                    {account.company_name}
                  </Link>
                  <span className="ml-2 font-mono text-[11px] text-ink-muted">{account.external_id}</span>
                </Cell>
                <Cell className="whitespace-nowrap">{account.account_tier.replace('_', ' ')}</Cell>
                <Cell>
                  <RiskBadge level={account.risk_level as RiskLevel} score={account.risk_score} />
                </Cell>
                <Cell numeric>{formatCurrency(account.monthly_recurring_revenue)}</Cell>
                <Cell className="whitespace-nowrap">{formatDate(account.renewal_date)}</Cell>
                <Cell>
                  <Link href={`/runs/${account.run_id}`} className="text-ink-muted hover:text-accent">
                    {formatRelative(account.created_at)}
                  </Link>
                </Cell>
              </Row>
            ))}
          </Table>
        )}
      </Panel>
    </div>
  )
}

function KeyRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-[var(--line)] py-1.5 last:border-0">
      <dt className="text-[12px] capitalize text-ink-muted">{label}</dt>
      <dd className="text-[12.5px] font-medium tabular-nums text-ink">{value}</dd>
    </div>
  )
}

function PageIntro() {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="mb-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
          Operations
        </div>
        <h1 className="text-[26px] font-semibold tracking-[-0.025em] text-ink">Dashboard</h1>
        <p className="mt-1.5 max-w-2xl text-[13px] text-ink-secondary">
          {config.productName} turns a business objective into a verified, evidence-backed report. Every
          number below is read from the platform database — nothing here is illustrative.
        </p>
      </div>
      <LinkButton href="/runs/new" variant="primary" size="lg" icon={<SparkIcon className="h-4 w-4" />}>
        New investigation
      </LinkButton>
    </div>
  )
}
