'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { EvidenceCard } from '@/components/runs/EvidenceCard'
import {
  AlertIcon,
  Badge,
  Cell,
  CheckIcon,
  CrossIcon,
  DocIcon,
  DownloadIcon,
  EmptyState,
  ErrorState,
  GlassPanel,
  LinkButton,
  Panel,
  Row,
  SectionHeader,
  ShieldIcon,
  Skeleton,
  StatTile,
  Table,
} from '@/components/ui/primitives'
import { RiskBadge } from '@/components/ui/status'
import { api } from '@/lib/api'
import { useApi } from '@/lib/hooks'
import { formatCurrency, formatDate, formatDateTime, formatNumber, formatRatio } from '@/lib/format'
import type { EvidenceItem, ReportAccountSection } from '@/lib/types'

type View = 'rendered' | 'markdown' | 'json'

export default function ReportPage() {
  const params = useParams<{ runId: string }>()
  const runId = params.runId
  const [view, setView] = useState<View>('rendered')

  const { data, error, initialLoading, refresh } = useApi(
    (signal) => api.report(runId, signal),
    [runId],
    { enabled: Boolean(runId) },
  )

  if (error) {
    const notReady = error.code === 'report_not_ready'
    return (
      <div className="space-y-4">
        <h1 className="text-[22px] font-semibold text-ink">Report</h1>
        {notReady ? (
          <Panel>
            <EmptyState
              icon={<DocIcon />}
              title="This report is not ready yet"
              description={error.message}
              action={
                <LinkButton href={`/runs/${runId}`} variant="primary" size="sm">
                  Follow the run
                </LinkButton>
              }
            />
          </Panel>
        ) : (
          <ErrorState error={error} onRetry={refresh} />
        )}
      </div>
    )
  }

  if (initialLoading || !data) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-9 w-96" />
        <Skeleton className="h-32 rounded-card" />
        <Skeleton className="h-64 rounded-card" />
      </div>
    )
  }

  const payload = data.report_payload
  const report = payload.report
  const stats = payload.statistics ?? {}
  const evidenceByReference = new Map(
    payload.evidence_index.map((item) => [
      item.reference,
      {
        id: item.reference,
        reference: item.reference,
        customer_id: null,
        source_type: item.source_type,
        source_id: item.source_id,
        title: item.title,
        content: item.content,
        source_date: item.source_date,
        relevance_score: item.relevance_score,
        metadata: {},
        created_at: payload.generated_at,
      } satisfies EvidenceItem,
    ]),
  )

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-1.5 flex items-center gap-2">
            <Link href="/reports" className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted hover:text-ink">
              Reports
            </Link>
          </div>
          <h1 className="max-w-3xl text-[24px] font-semibold leading-snug tracking-[-0.025em] text-ink">
            {data.title}
          </h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-ink-muted">
            <span>{formatDateTime(data.created_at)}</span>
            <Link href={`/runs/${data.run_id}`} className="text-accent hover:underline">
              run {data.run_id.slice(0, 8)}
            </Link>
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <a
            href={api.reportMarkdownUrl(data.run_id)}
            className="inline-flex h-9.5 items-center justify-center gap-2 rounded-lg bg-surface-raised px-4 text-[13px] font-medium text-ink ring-1 ring-inset ring-[var(--line-strong)] transition-colors hover:bg-surface-sunken"
          >
            <DownloadIcon className="h-3.5 w-3.5" />
            Download Markdown
          </a>
        </div>
      </div>

      {/* Objective */}
      <GlassPanel className="px-4 py-3.5">
        <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted">Objective</div>
        <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-secondary">{payload.objective}</p>
      </GlassPanel>

      {/* Statistics */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Accounts investigated"
          value={formatNumber(Number(stats.investigated ?? report.accounts.length))}
          hint={`${formatNumber(Number(stats.candidates ?? 0))} screened`}
          emphasis
        />
        <StatTile
          label="Supported claims"
          value={formatNumber(Number(stats.supported_claims ?? 0))}
          hint={`of ${formatNumber(Number(stats.total_claims ?? 0))} material claims`}
          tone="good"
          emphasis
        />
        <StatTile
          label="Rejected claims"
          value={formatNumber(Number(stats.rejected_claims ?? 0))}
          hint="excluded from every conclusion below"
          tone={Number(stats.rejected_claims ?? 0) > 0 ? 'critical' : 'neutral'}
          emphasis
        />
        <StatTile
          label="ARR investigated"
          value={formatCurrency(Number(stats.investigated_acv ?? 0))}
          hint="annual contract value in scope"
          emphasis
        />
      </div>

      {/* View switcher */}
      <nav className="flex gap-1 border-b border-[var(--line)]" aria-label="Report format">
        {(
          [
            ['rendered', 'Report'],
            ['markdown', 'Markdown'],
            ['json', 'Structured JSON'],
          ] as Array<[View, string]>
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-current={view === id ? 'page' : undefined}
            onClick={() => setView(id)}
            className={
              view === id
                ? '-mb-px border-b-2 border-accent px-3 py-2 text-[13px] font-medium text-ink'
                : '-mb-px border-b-2 border-transparent px-3 py-2 text-[13px] text-ink-secondary hover:text-ink'
            }
          >
            {label}
          </button>
        ))}
      </nav>

      {view === 'markdown' ? (
        <Panel className="overflow-x-auto p-4">
          <pre className="whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-ink-secondary">
            {data.markdown_content}
          </pre>
        </Panel>
      ) : null}

      {view === 'json' ? (
        <Panel className="overflow-x-auto p-4">
          <pre className="whitespace-pre-wrap font-mono text-[11.5px] leading-relaxed text-ink-secondary">
            {JSON.stringify(payload, null, 2)}
          </pre>
        </Panel>
      ) : null}

      {view === 'rendered' ? (
        <div className="space-y-5">
          {/* Executive summary */}
          <Panel className="p-5">
            <SectionHeader eyebrow="For the revenue leader" title="Executive summary" />
            <p className="mt-3 max-w-4xl text-[14px] leading-relaxed text-ink-secondary">
              {report.executive_summary}
            </p>
          </Panel>

          {/* Ranked accounts */}
          {report.accounts.length === 0 ? (
            <Panel>
              <EmptyState
                icon={<CheckIcon />}
                title="No account crossed the risk threshold"
                description="This is a valid result. The screening model ran over the full candidate set and found nothing requiring intervention, so no retention action is recommended."
              />
            </Panel>
          ) : (
            <>
              <Panel>
                <div className="border-b border-[var(--line)] px-4 py-3">
                  <SectionHeader eyebrow="Priority" title="Ranked at-risk accounts" />
                </div>
                <Table head={['#', 'Account', 'Risk score', 'Level', 'Confidence', 'Renewal', 'MRR']}>
                  {report.accounts.map((account, index) => (
                    <Row key={account.customer_external_id}>
                      <Cell numeric className="w-10 text-ink-muted">
                        {index + 1}
                      </Cell>
                      <Cell>
                        <Link
                          href={`/customers/${account.customer_external_id}`}
                          className="font-medium text-ink hover:text-accent"
                        >
                          {account.company_name}
                        </Link>
                        <span className="ml-2 font-mono text-[10.5px] text-ink-muted">
                          {account.customer_external_id}
                        </span>
                      </Cell>
                      <Cell numeric className="font-medium text-ink">
                        {account.risk_score.toFixed(1)}
                      </Cell>
                      <Cell>
                        <RiskBadge level={account.risk_level} />
                      </Cell>
                      <Cell numeric>{formatRatio(account.confidence)}</Cell>
                      <Cell className="whitespace-nowrap">{formatDate(account.renewal_date)}</Cell>
                      <Cell numeric>{formatCurrency(account.monthly_recurring_revenue)}</Cell>
                    </Row>
                  ))}
                </Table>
              </Panel>

              {report.accounts.map((account) => (
                <AccountSection
                  key={account.customer_external_id}
                  account={account}
                  evidenceByReference={evidenceByReference}
                />
              ))}
            </>
          )}

          {/* Portfolio observations */}
          {report.portfolio_observations.length > 0 ? (
            <Panel className="p-4">
              <SectionHeader eyebrow="Pattern" title="Portfolio observations" />
              <ul className="mt-3 space-y-1.5">
                {report.portfolio_observations.map((item, index) => (
                  <li key={index} className="flex gap-2.5 text-[13px] leading-snug text-ink-secondary">
                    <span aria-hidden className="text-ink-muted">
                      ·
                    </span>
                    {item}
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}

          {/* Uncertainties */}
          {report.unresolved_uncertainties.length > 0 ? (
            <Panel className="p-4">
              <SectionHeader
                eyebrow="Honesty"
                title="Unresolved uncertainties"
                description="What this report could not establish."
              />
              <ul className="mt-3 space-y-1.5">
                {report.unresolved_uncertainties.map((item, index) => (
                  <li key={index} className="flex gap-2.5 text-[13px] leading-snug text-ink-secondary">
                    <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[color-mix(in_srgb,var(--status-warning)_85%,var(--ink))]" />
                    {item}
                  </li>
                ))}
              </ul>
            </Panel>
          ) : null}

          {/* Methodology */}
          <Panel className="p-4">
            <SectionHeader
              eyebrow="How this was produced"
              title="Methodology"
              description="Stated so a reader can judge how much weight the conclusions deserve."
            />
            <ul className="mt-3 space-y-1.5">
              {report.methodology_notes.map((note, index) => (
                <li key={index} className="flex gap-2.5 text-[12.5px] leading-snug text-ink-secondary">
                  <ShieldIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-muted" />
                  {note}
                </li>
              ))}
            </ul>
          </Panel>

          {/* Evidence appendix */}
          {payload.evidence_index.length > 0 ? (
            <Panel className="p-4">
              <SectionHeader
                eyebrow="Provenance"
                title="Evidence appendix"
                description={`${payload.evidence_index.length} records cited across this report.`}
              />
              <div className="mt-3 grid gap-2.5 lg:grid-cols-2">
                {[...evidenceByReference.values()].map((item) => (
                  <EvidenceCard key={item.reference} item={item} compact />
                ))}
              </div>
            </Panel>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function AccountSection({
  account,
  evidenceByReference,
}: {
  account: ReportAccountSection
  evidenceByReference: Map<string, EvidenceItem>
}) {
  return (
    <Panel className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex flex-wrap items-center gap-2.5 text-[16px] font-semibold tracking-[-0.015em] text-ink">
            <Link href={`/customers/${account.customer_external_id}`} className="hover:text-accent">
              {account.company_name}
            </Link>
            <RiskBadge level={account.risk_level} score={account.risk_score} />
          </h2>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 font-mono text-[11px] text-ink-muted">
            <span>{account.customer_external_id}</span>
            <span>Renews {formatDate(account.renewal_date)}</span>
            <span>MRR {formatCurrency(account.monthly_recurring_revenue)}</span>
            <span>Confidence {formatRatio(account.confidence)}</span>
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        <Block
          title="Verified quantitative indicators"
          items={account.quantitative_indicators}
          icon={<CheckIcon className="h-3.5 w-3.5 text-[var(--status-good)]" />}
          empty="No calculated metrics were verified for this account."
        />
        <Block
          title="Verified qualitative evidence"
          items={account.qualitative_evidence}
          icon={<CheckIcon className="h-3.5 w-3.5 text-[var(--status-good)]" />}
          empty="No document-based observations were verified for this account."
        />
      </div>

      {account.verified_conclusions.length > 0 ? (
        <div className="mt-5">
          <Block
            title="Verified conclusions"
            items={account.verified_conclusions}
            icon={<CheckIcon className="h-3.5 w-3.5 text-[var(--status-good)]" />}
            empty=""
          />
        </div>
      ) : null}

      {account.qualified_findings.length > 0 ? (
        <div className="mt-5">
          <Block
            title="Qualified findings"
            description="The evidence supports the direction but not the original wording, so these are stated with their qualifier."
            items={account.qualified_findings}
            icon={<AlertIcon className="h-3.5 w-3.5 text-[color-mix(in_srgb,var(--status-warning)_85%,var(--ink))]" />}
            empty=""
          />
        </div>
      ) : null}

      {account.excluded_conclusions.length > 0 ? (
        <div className="mt-5">
          <Block
            title="Excluded conclusions"
            description="The investigator produced these; verification rejected them, so they are not asserted."
            items={account.excluded_conclusions}
            icon={<CrossIcon className="h-3.5 w-3.5 text-[var(--status-critical)]" />}
            empty=""
            strike
          />
        </div>
      ) : null}

      {account.recommended_actions.length > 0 ? (
        <div className="mt-5">
          <h3 className="text-[12.5px] font-semibold text-ink">Recommended interventions</h3>
          <ul className="mt-2 space-y-1.5">
            {account.recommended_actions.map((action, index) => (
              <li key={index} className="flex flex-wrap items-baseline gap-2 text-[12.5px] text-ink-secondary">
                <span className="font-mono text-[11px] font-medium text-ink">{action.action_type}</span>
                {action.requires_approval ? (
                  <Badge tone="warning" icon={<ShieldIcon className="h-3 w-3" />}>
                    Approval required
                  </Badge>
                ) : null}
                <span className="min-w-0">{action.description}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {account.uncertainties.length > 0 ? (
        <div className="mt-5 rounded-card border border-[var(--line)] bg-surface-sunken p-3">
          <h3 className="text-[12.5px] font-semibold text-ink">Insufficient evidence</h3>
          <ul className="mt-1.5 space-y-1 text-[12px] text-ink-secondary">
            {account.uncertainties.map((item, index) => (
              <li key={index}>· {item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {account.evidence_references.length > 0 ? (
        <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-[var(--line)] pt-3">
          <span className="mr-1 font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted">
            Evidence
          </span>
          {account.evidence_references.map((reference) => (
            <a
              key={reference}
              href={`#evidence-${reference}`}
              title={evidenceByReference.get(reference)?.title ?? reference}
              className="rounded bg-accent-wash px-1.5 py-0.5 font-mono text-[10.5px] font-medium text-accent hover:underline"
            >
              {reference}
            </a>
          ))}
        </div>
      ) : null}
    </Panel>
  )
}

function Block({
  title,
  description,
  items,
  icon,
  empty,
  strike = false,
}: {
  title: string
  description?: string
  items: string[]
  icon: React.ReactNode
  empty: string
  strike?: boolean
}) {
  if (items.length === 0 && !empty) return null
  return (
    <section>
      <h3 className="text-[12.5px] font-semibold text-ink">{title}</h3>
      {description ? <p className="mt-0.5 text-[11.5px] text-ink-muted">{description}</p> : null}
      {items.length === 0 ? (
        <p className="mt-2 text-[12px] text-ink-muted">{empty}</p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {items.map((item, index) => (
            <li key={index} className="flex gap-2.5 text-[12.5px] leading-snug text-ink-secondary">
              <span className="mt-0.5 shrink-0">{icon}</span>
              <span className={strike ? 'min-w-0 opacity-80' : 'min-w-0'}>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
