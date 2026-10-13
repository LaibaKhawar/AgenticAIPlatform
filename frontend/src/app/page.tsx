'use client'

import Link from 'next/link'
import { TextShimmer } from '@/components/core/text-shimmer'
import { FlowCanvas } from '@/components/flow/FlowCanvas'
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
import type { Dashboard, RiskLevel } from '@/lib/types'

export default function DashboardPage() {
  const { data, error, initialLoading, refresh } = useApi((signal) => api.dashboard(signal), [], {
    intervalMs: 10_000,
  })

  if (error) {
    return (
      <div className="space-y-4">
        <DashboardHero />
        <ErrorState error={error} onRetry={refresh} />
      </div>
    )
  }

  if (initialLoading || !data) {
    return (
      <div className="space-y-6">
        <DashboardHero />
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
    <div className="stagger space-y-7">
      <DashboardHero data={data} />

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
        <div className="stagger grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatTile
            label="Investigations completed"
            value={formatNumber(data.investigations_completed)}
            countTo={data.investigations_completed}
            format={(n) => formatNumber(Math.round(n))}
            hint={`across ${formatNumber(data.runs_total)} run${data.runs_total === 1 ? '' : 's'}`}
            icon={<FlowIcon className="h-3.5 w-3.5" />}
            href="/runs"
            emphasis
          />
          <StatTile
            label="Currently running"
            value={formatNumber(data.runs_running)}
            countTo={data.runs_running}
            format={(n) => formatNumber(Math.round(n))}
            hint={
              data.runs_running > 0 ? (
                <TextShimmer as="span" duration={1.8}>
                  workers are executing tasks
                </TextShimmer>
              ) : (
                'no work in flight'
              )
            }
            tone={data.runs_running > 0 ? 'accent' : 'neutral'}
            href="/runs"
            emphasis
          />
          <StatTile
            label="Failed investigations"
            value={formatNumber(data.runs_failed)}
            countTo={data.runs_failed}
            format={(n) => formatNumber(Math.round(n))}
            hint={data.runs_failed > 0 ? 'open a run to see the failing stage' : 'none'}
            tone={data.runs_failed > 0 ? 'critical' : 'neutral'}
            href="/runs?status=FAILED"
            emphasis
          />
          <StatTile
            label="Pending approvals"
            value={formatNumber(data.pending_approvals)}
            countTo={data.pending_approvals}
            format={(n) => formatNumber(Math.round(n))}
            hint={data.pending_approvals > 0 ? 'sensitive actions awaiting review' : 'nothing to review'}
            tone={data.pending_approvals > 0 ? 'warning' : 'neutral'}
            icon={<ShieldIcon className="h-3.5 w-3.5" />}
            href="/approvals"
            emphasis
          />
        </div>
      </section>

      {/* Quality + portfolio */}
      <section className="stagger grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="High-risk customers"
          value={formatNumber(data.high_risk_customers)}
          countTo={data.high_risk_customers}
          format={(n) => formatNumber(Math.round(n))}
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
          countTo={data.verified_claim_pct}
          format={(n) => formatPercent(n, 1)}
          hint={claimTotal === 0 ? 'no claims produced yet' : 'fully supported by evidence'}
          tone={data.verified_claim_pct === null ? 'neutral' : 'good'}
        />
        <StatTile
          label="Unsupported claims"
          value={data.unsupported_claim_pct === null ? '—' : formatPercent(data.unsupported_claim_pct, 1)}
          countTo={data.unsupported_claim_pct}
          format={(n) => formatPercent(n, 1)}
          hint={claimTotal === 0 ? 'no claims produced yet' : 'rejected before reaching a report'}
          tone={data.unsupported_claim_pct === null ? 'neutral' : 'critical'}
        />
      </section>

      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-4 lg:grid-cols-3">
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
                        live={isRunActive(run.status)}
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

function DashboardHero({ data }: { data?: Dashboard }) {
  const pending = data?.pending_approvals ?? 0
  return (
    <section aria-labelledby="dashboard-title" data-flow-origin className="hero-band lg:min-h-[520px]">
      {/* The Veriflow Flow: inputs enter small and distant on the right, are
          routed through investigation and verification, and leave large and
          near at the bottom-left. It is also where page transitions begin. */}
      <FlowCanvas className="absolute inset-0 opacity-60 lg:opacity-100" />
      {/* Legibility scrim behind the headline only; the near end of the flow
          (bottom-left) stays at full strength. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(56rem_24rem_at_0%_0%,rgb(30_34_66/0.82),rgb(30_34_66/0.5)_45%,transparent_72%)]"
      />

      <div className="relative z-1 grid gap-8 px-6 py-9 sm:px-9 sm:py-11 lg:grid-cols-[minmax(0,1fr)_auto] lg:py-12">
        <div className="max-w-2xl">
        <div className="mb-4 inline-flex items-center gap-2 rounded-full bg-white/[0.07] px-3 py-1 ring-1 ring-inset ring-white/15 backdrop-blur-sm">
          <span className="relative flex h-1.5 w-1.5">
            <span className="live-dot h-1.5 w-1.5 rounded-full bg-aqua text-aqua" />
          </span>
          <span className="font-mono text-[10.5px] font-medium tracking-[0.12em] text-[#c9cdea] uppercase">
            Operations · live
          </span>
        </div>

        <h1
          id="dashboard-title"
          className="text-[34px] leading-[1.05] font-semibold tracking-[-0.035em] text-[#f2f3fa] sm:text-[44px]"
        >
          Every conclusion,
          <br />
          <span className="text-brand-hero text-brand-animated">traced to its evidence.</span>
        </h1>

        <p className="mt-4 max-w-[58ch] text-[14.5px] leading-relaxed text-[#c9cdea]">
          {config.productName} turns a business objective into a plan, investigates each account,
          and checks every claim against its sources before anything reaches a report. Every number
          on this page is read live from the platform database.
        </p>

        <div className="mt-7 flex flex-wrap items-center gap-3">
          <LinkButton href="/runs/new" variant="brand" size="lg" icon={<SparkIcon className="h-4 w-4" />}>
            New investigation
          </LinkButton>
          <LinkButton href="/approvals" variant="onDark" size="lg" icon={<ShieldIcon className="h-4 w-4" />}>
            {pending > 0 ? `Review ${pending} approval${pending === 1 ? '' : 's'}` : 'Approvals'}
          </LinkButton>
        </div>

        </div>

        {/* Live figures sit top-right, clear of the flow's path. */}
        {data ? (
          <dl className="flex flex-wrap gap-x-7 gap-y-3 border-t border-white/10 pt-5 lg:flex-col lg:items-end lg:gap-y-4 lg:border-0 lg:pt-1 lg:text-right">
            <HeroFact label="Customers" value={formatNumber(data.total_customers)} />
            <HeroFact label="Renewing in 90 days" value={formatNumber(data.renewing_within_90_days)} />
            <HeroFact label="Evidence records" value={formatNumber(data.evidence_records)} />
          </dl>
        ) : null}
      </div>
    </section>
  )
}

function HeroFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-mono text-[10px] tracking-[0.12em] text-[#a9aed6] uppercase">{label}</dt>
      <dd className="num mt-1 text-[20px] font-semibold tracking-[-0.02em] text-[#f2f3fa]">{value}</dd>
    </div>
  )
}
