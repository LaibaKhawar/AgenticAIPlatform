'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useMemo, useState } from 'react'
import { RiskSignalBars, TicketVolumeChart, UsageTrendChart } from '@/components/charts/charts'
import {
  AlertIcon,
  Badge,
  Cell,
  DocIcon,
  EmptyState,
  ErrorState,
  GlassPanel,
  KeyValue,
  LinkButton,
  Panel,
  Row,
  SectionHeader,
  Skeleton,
  StatTile,
  Table,
} from '@/components/ui/primitives'
import { RiskBadge } from '@/components/ui/status'
import { ApiError, api } from '@/lib/api'
import { useApi } from '@/lib/hooks'
import {
  daysLabel,
  formatCurrency,
  formatDate,
  formatNumber,
  formatRatio,
  formatRelative,
  formatSignedPercent,
  humanise,
} from '@/lib/format'
import type { DocumentDetail, TicketSummary } from '@/lib/types'

export default function CustomerDetailPage() {
  const params = useParams<{ customerId: string }>()
  const customerId = params.customerId
  const { data, error, initialLoading, refresh } = useApi(
    (signal) => api.customer(customerId, signal),
    [customerId],
    { enabled: Boolean(customerId) },
  )
  const [openDocument, setOpenDocument] = useState<DocumentDetail | null>(null)
  const [documentError, setDocumentError] = useState<ApiError | null>(null)

  const ticketBuckets = useMemo(() => (data ? bucketTickets(data.tickets) : []), [data])

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-[22px] font-semibold text-ink">Customer</h1>
        <ErrorState error={error} onRetry={refresh} />
        <LinkButton href="/customers" variant="secondary" size="sm">
          Back to customers
        </LinkButton>
      </div>
    )
  }

  if (initialLoading || !data) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-9 w-72" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[86px] rounded-card" />
          ))}
        </div>
        <Skeleton className="h-72 rounded-card" />
      </div>
    )
  }

  const { customer, subscription } = { customer: data.customer, subscription: data.customer.subscription }
  const usage = data.usage_summary
  const support = data.support_summary
  const payments = data.payment_summary
  const nps = data.nps_summary

  async function viewDocument(documentId: string) {
    setDocumentError(null)
    try {
      setOpenDocument(await api.customerDocument(customerId, documentId))
    } catch (caught) {
      setDocumentError(
        caught instanceof ApiError ? caught : new ApiError(0, 'unexpected_error', String(caught)),
      )
    }
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-1.5 flex items-center gap-2">
            <Link href="/customers" className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-muted hover:text-ink">
              Customers
            </Link>
          </div>
          <h1 className="flex flex-wrap items-center gap-3 text-[24px] font-semibold tracking-[-0.025em] text-ink">
            {customer.company_name}
            <RiskBadge level={data.risk.risk_level} score={data.risk.heuristic_risk_score} />
          </h1>
          <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-ink-muted">
            <span>{customer.external_id}</span>
            <span>{customer.account_tier.replace('_', ' ')}</span>
            <span>{customer.industry}</span>
            <span>{customer.country}</span>
            <span>{formatNumber(customer.employee_count)} employees</span>
            <span>AM {customer.account_manager}</span>
          </p>
        </div>
        {data.outcome && data.outcome.outcome !== 'UNKNOWN' ? (
          <GlassPanel className="px-3.5 py-2.5">
            <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-ink-muted">
              Historical outcome
            </div>
            <div className="mt-0.5 text-[13px] font-semibold text-ink">{data.outcome.outcome}</div>
            {data.outcome.churn_reason ? (
              <div className="text-[11.5px] text-ink-muted">{humanise(data.outcome.churn_reason)}</div>
            ) : null}
            <div className="mt-1 text-[10.5px] text-ink-muted">
              This label is held out of the risk model and used only for evaluation.
            </div>
          </GlassPanel>
        ) : null}
      </div>

      {/* Commercial summary */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="MRR" value={formatCurrency(subscription?.monthly_recurring_revenue)} hint={subscription?.plan ?? 'no subscription'} />
        <StatTile label="ACV" value={formatCurrency(subscription?.annual_contract_value)} hint="annual contract value" />
        <StatTile
          label="Renewal"
          value={subscription ? formatDate(subscription.renewal_date) : '—'}
          hint={subscription ? daysLabel(subscription.days_to_renewal) : 'no renewal date on record'}
          tone={
            subscription && subscription.days_to_renewal !== null && subscription.days_to_renewal <= 45
              ? 'warning'
              : 'neutral'
          }
        />
        <StatTile
          label="Risk score"
          value={data.risk.heuristic_risk_score.toFixed(1)}
          hint={`coverage ${formatRatio(data.risk.coverage)} · ×${data.risk.renewal_multiplier} renewal urgency`}
          tone={
            data.risk.risk_level === 'CRITICAL'
              ? 'critical'
              : data.risk.risk_level === 'HIGH'
                ? 'serious'
                : data.risk.risk_level === 'MEDIUM'
                  ? 'warning'
                  : 'good'
          }
        />
      </div>

      {/* Health signals */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Active users (30d avg)"
          value={formatNumber(usage.recent_active_users, 0)}
          hint={
            usage.active_user_change_pct === null
              ? 'no comparable baseline'
              : `${formatSignedPercent(usage.active_user_change_pct)} vs prior window`
          }
          tone={usage.active_user_change_pct !== null && usage.active_user_change_pct < -20 ? 'critical' : 'neutral'}
        />
        <StatTile
          label="Seat utilisation"
          value={usage.seat_utilization === null ? '—' : formatRatio(usage.seat_utilization)}
          hint={
            usage.seats_purchased
              ? `${formatNumber(usage.seats_active)} of ${formatNumber(usage.seats_purchased)} seats`
              : 'no seat count on record'
          }
          tone={usage.seat_utilization !== null && usage.seat_utilization < 0.5 ? 'warning' : 'neutral'}
        />
        <StatTile
          label="Tickets (30d)"
          value={formatNumber(support.recent_ticket_count)}
          hint={
            support.ticket_growth_pct === null
              ? 'no comparable history'
              : `${formatSignedPercent(support.ticket_growth_pct)} vs prior window · ${support.unresolved_critical_count} unresolved critical`
          }
          tone={support.ticket_growth_pct !== null && support.ticket_growth_pct > 100 ? 'serious' : 'neutral'}
        />
        <StatTile
          label="NPS"
          value={nps.latest_score === null ? '—' : String(nps.latest_score)}
          hint={
            nps.latest_score === null
              ? 'no survey response'
              : nps.score_delta === null
                ? `${nps.response_count} response${nps.response_count === 1 ? '' : 's'}`
                : `${nps.score_delta > 0 ? '+' : ''}${nps.score_delta} from previous`
          }
          tone={nps.latest_score !== null && nps.latest_score <= 4 ? 'critical' : 'neutral'}
        />
      </div>

      {/* Charts */}
      <div className="grid gap-4 lg:grid-cols-2">
        <UsageTrendChart
          points={data.usage.map((point) => ({
            usage_date: point.usage_date,
            active_users: point.active_users,
            seats_active: point.seats_active,
          }))}
        />
        <TicketVolumeChart buckets={ticketBuckets} />
      </div>

      {/* Risk breakdown + billing */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel className="p-4 lg:col-span-2">
          <SectionHeader
            eyebrow="Deterministic"
            title="Risk signal breakdown"
            description="Computed in application code from the rows below — never by a language model. Points shown are the contribution to the 0-100 score."
          />
          <div className="mt-4">
            <RiskSignalBars signals={data.risk.signals} />
          </div>
          {data.risk.missing_signals.length > 0 ? (
            <p className="mt-3 border-t border-[var(--line)] pt-2.5 text-[11.5px] text-ink-muted">
              <AlertIcon className="mr-1 inline h-3 w-3 align-[-2px]" />
              No data for {data.risk.missing_signals.map((key) => key.replace(/_/g, ' ')).join(', ')}. The
              score is renormalised over the signals that were available, so absent data neither inflates
              nor deflates it.
            </p>
          ) : null}
        </Panel>

        <div className="space-y-4">
          <Panel className="p-4">
            <SectionHeader eyebrow="Billing" title="Invoices" />
            <dl className="mt-2">
              <KeyValue label="Invoices on record" value={formatNumber(payments.invoice_count)} />
              <KeyValue label="Unpaid" value={formatNumber(payments.overdue_invoice_count)} />
              <KeyValue
                label="Worst overdue"
                value={payments.max_days_overdue > 0 ? `${payments.max_days_overdue} days` : 'none'}
              />
              <KeyValue label="Overdue amount" value={formatCurrency(payments.total_overdue_amount)} />
              <KeyValue label="Latest status" value={payments.latest_invoice_status ?? '—'} />
            </dl>
          </Panel>

          <Panel className="p-4">
            <SectionHeader eyebrow="Support" title="Quality" />
            <dl className="mt-2">
              <KeyValue
                label="Average CSAT"
                value={support.average_csat === null ? 'no responses' : `${support.average_csat.toFixed(2)} / 5`}
              />
              <KeyValue label="CSAT responses" value={formatNumber(support.csat_responses)} />
              <KeyValue label="Open tickets" value={formatNumber(support.open_ticket_count)} />
              <KeyValue label="Critical tickets" value={formatNumber(support.critical_ticket_count)} />
              <KeyValue
                label="Avg resolution"
                value={
                  support.average_resolution_hours === null
                    ? '—'
                    : `${support.average_resolution_hours.toFixed(1)} h`
                }
              />
            </dl>
          </Panel>
        </div>
      </div>

      {/* Documents + NPS feedback */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <div className="border-b border-[var(--line)] px-4 py-3">
            <SectionHeader
              eyebrow="Unstructured"
              title="Documents"
              description="The corpus behind semantic retrieval. Content is customer-authored and treated as untrusted data."
            />
          </div>
          {data.documents.length === 0 ? (
            <EmptyState
              icon={<DocIcon />}
              title="No documents"
              description="This account has no emails, CSM notes or QBR records, so an investigation would have only quantitative signals to work with."
            />
          ) : (
            <ul className="divide-y divide-[var(--line)]">
              {data.documents.map((document) => (
                <li key={document.id}>
                  <button
                    type="button"
                    onClick={() => viewDocument(document.id)}
                    className="flex w-full items-start gap-3 px-4 py-2.5 text-left hover:bg-surface-sunken"
                  >
                    <DocIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ink-muted" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12.5px] font-medium text-ink">
                        {document.title}
                      </span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-x-2.5 font-mono text-[10.5px] text-ink-muted">
                        <span>{humanise(document.source_type)}</span>
                        <span>{formatDate(document.source_date)}</span>
                        <span>{formatNumber(document.chars)} chars</span>
                        <span>{document.chunk_count} chunk{document.chunk_count === 1 ? '' : 's'}</span>
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel className="p-4">
            <SectionHeader eyebrow="Sentiment" title="NPS history" />
            {data.nps.length === 0 ? (
              <p className="mt-3 text-[12.5px] text-ink-muted">
                No survey responses on record, so relationship sentiment is unknown for this account.
              </p>
            ) : (
              <ul className="mt-3 space-y-2.5">
                {data.nps.map((response) => (
                  <li key={response.id} className="border-b border-[var(--line)] pb-2.5 last:border-0 last:pb-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={
                          response.score <= 4
                            ? 'rounded-md bg-[color-mix(in_srgb,var(--status-critical)_16%,transparent)] px-1.5 py-0.5 font-mono text-[11px] font-semibold text-[color-mix(in_srgb,var(--status-critical)_92%,var(--ink))]'
                            : response.score <= 7
                              ? 'rounded-md bg-[color-mix(in_srgb,var(--status-warning)_18%,transparent)] px-1.5 py-0.5 font-mono text-[11px] font-semibold text-[color-mix(in_srgb,var(--status-warning)_82%,var(--ink))]'
                              : 'rounded-md bg-[color-mix(in_srgb,var(--status-good)_16%,transparent)] px-1.5 py-0.5 font-mono text-[11px] font-semibold text-[var(--status-good)]'
                        }
                      >
                        {response.score}/10
                      </span>
                      <span className="font-mono text-[10.5px] text-ink-muted">
                        {formatDate(response.response_date)}
                      </span>
                    </div>
                    {response.feedback ? (
                      <p className="mt-1 text-[12px] leading-snug text-ink-secondary">“{response.feedback}”</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel className="p-4">
            <SectionHeader eyebrow="History" title="Prior investigations" />
            {data.investigations.length === 0 ? (
              <p className="mt-3 text-[12.5px] text-ink-muted">
                This account has not been investigated yet.
              </p>
            ) : (
              <ul className="mt-3 space-y-2.5">
                {data.investigations.map((investigation) => (
                  <li key={investigation.id} className="border-b border-[var(--line)] pb-2.5 last:border-0 last:pb-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <RiskBadge level={investigation.risk_level as never} score={investigation.risk_score} />
                      <Link
                        href={`/runs/${investigation.run_id}`}
                        className="font-mono text-[10.5px] text-accent hover:underline"
                      >
                        {formatRelative(investigation.created_at)}
                      </Link>
                      <span className="font-mono text-[10.5px] text-ink-muted">
                        confidence {formatRatio(investigation.confidence)}
                      </span>
                    </div>
                    <p className="mt-1 text-[12px] leading-snug text-ink-secondary">{investigation.summary}</p>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>

      {/* Recent tickets */}
      {data.tickets.length > 0 ? (
        <Panel>
          <div className="border-b border-[var(--line)] px-4 py-3">
            <SectionHeader eyebrow="Support" title="Recent tickets" />
          </div>
          <Table head={['Ticket', 'Subject', 'Category', 'Priority', 'Status', 'CSAT', 'Resolution', 'Created']}>
            {data.tickets.slice(0, 12).map((ticket) => (
              <Row key={ticket.id}>
                <Cell mono>{ticket.external_ticket_id}</Cell>
                <Cell className="max-w-[20rem] truncate text-ink">{ticket.subject}</Cell>
                <Cell>{ticket.category}</Cell>
                <Cell>
                  <Badge
                    tone={
                      ticket.priority === 'CRITICAL'
                        ? 'critical'
                        : ticket.priority === 'HIGH'
                          ? 'serious'
                          : 'muted'
                    }
                  >
                    {humanise(ticket.priority)}
                  </Badge>
                </Cell>
                <Cell>
                  <Badge
                    tone={
                      ticket.status === 'ESCALATED'
                        ? 'critical'
                        : ticket.status === 'OPEN' || ticket.status === 'PENDING'
                          ? 'warning'
                          : 'good'
                    }
                  >
                    {humanise(ticket.status)}
                  </Badge>
                </Cell>
                <Cell numeric>{ticket.csat_score === null ? '—' : ticket.csat_score.toFixed(1)}</Cell>
                <Cell numeric>
                  {ticket.resolution_hours === null ? '—' : `${ticket.resolution_hours.toFixed(0)}h`}
                </Cell>
                <Cell className="whitespace-nowrap text-ink-muted">{formatDate(ticket.created_at)}</Cell>
              </Row>
            ))}
          </Table>
        </Panel>
      ) : null}

      {documentError ? <ErrorState error={documentError} /> : null}

      {/* Document viewer */}
      {openDocument ? (
        <DocumentModal document={openDocument} onClose={() => setOpenDocument(null)} />
      ) : null}
    </div>
  )
}

function DocumentModal({ document, onClose }: { document: DocumentDetail; onClose: () => void }) {
  const detections = Array.isArray(document.metadata?.injection_detections)
    ? (document.metadata.injection_detections as string[])
    : []
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={document.title}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm sm:p-8"
      onClick={onClose}
    >
      <GlassPanel
        strong
        className="w-full max-w-3xl"
        // Stop the backdrop click from closing when interacting with content.
      >
        <div onClick={(event) => event.stopPropagation()}>
          <header className="flex items-start justify-between gap-4 border-b border-[var(--glass-border)] px-5 py-4">
            <div className="min-w-0">
              <h2 className="text-[15px] font-semibold text-ink">{document.title}</h2>
              <p className="mt-1 flex flex-wrap items-center gap-x-3 font-mono text-[10.5px] text-ink-muted">
                <span>{humanise(document.source_type)}</span>
                <span>{formatDate(document.source_date)}</span>
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close document"
              className="rounded-lg px-2 py-1 text-[13px] text-ink-muted hover:bg-surface-sunken hover:text-ink"
            >
              Close
            </button>
          </header>
          <div className="px-5 py-4">
            {detections.length > 0 ? (
              <div className="mb-3 rounded-md border border-[color-mix(in_srgb,var(--status-critical)_30%,transparent)] bg-[color-mix(in_srgb,var(--status-critical)_8%,transparent)] px-3 py-2">
                <p className="flex items-center gap-2 text-[12px] font-medium text-ink">
                  <AlertIcon className="h-3.5 w-3.5 text-[var(--status-critical)]" />
                  Instruction-like text was detected in this document and neutralised
                </p>
                <p className="mt-1 font-mono text-[11px] text-ink-secondary">
                  {detections.join(', ')} — the passage is replaced with a marker before this content can
                  reach any model prompt.
                </p>
              </div>
            ) : null}
            <p className="whitespace-pre-line text-[13px] leading-relaxed text-ink-secondary">
              {document.content}
            </p>
            <p className="mt-4 border-t border-[var(--glass-border)] pt-2.5 font-mono text-[10.5px] text-ink-muted">
              Customer-authored content · treated strictly as data
            </p>
          </div>
        </div>
      </GlassPanel>
    </div>
  )
}

/** Group tickets into calendar months for the volume chart. */
function bucketTickets(tickets: TicketSummary[]): Array<{ label: string; tickets: number; unresolved: number }> {
  const buckets = new Map<string, { label: string; tickets: number; unresolved: number; sort: number }>()
  for (const ticket of tickets) {
    const date = new Date(ticket.created_at)
    if (Number.isNaN(date.getTime())) continue
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
    const existing = buckets.get(key) ?? {
      label: date.toLocaleDateString('en-US', { month: 'short' }),
      tickets: 0,
      unresolved: 0,
      sort: date.getTime(),
    }
    const unresolved = ['OPEN', 'PENDING', 'ESCALATED'].includes(ticket.status)
    if (unresolved) existing.unresolved += 1
    else existing.tickets += 1
    buckets.set(key, existing)
  }
  return [...buckets.values()]
    .sort((a, b) => a.sort - b.sort)
    .map(({ label, tickets: resolved, unresolved }) => ({ label, tickets: resolved, unresolved }))
}
