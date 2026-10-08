'use client'

import Link from 'next/link'
import { useState } from 'react'
import { RiskSignalBars } from '@/components/charts/charts'
import { EvidenceCard } from '@/components/runs/EvidenceCard'
import {
  AlertIcon,
  ArrowRightIcon,
  Badge,
  CheckIcon,
  CrossIcon,
  GlassPanel,
  ShieldIcon,
} from '@/components/ui/primitives'
import { ClaimStatusBadge, RiskBadge } from '@/components/ui/status'
import { formatCurrency, formatDate, formatRatio, humanise } from '@/lib/format'
import type { ClaimItem, Investigation } from '@/lib/types'

type Tab = 'findings' | 'claims' | 'evidence' | 'signals' | 'actions'

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'findings', label: 'Findings' },
  { id: 'claims', label: 'Claims' },
  { id: 'evidence', label: 'Evidence' },
  { id: 'signals', label: 'Signals' },
  { id: 'actions', label: 'Actions' },
]

/**
 * One investigated account: why the platform reached its conclusion, what it
 * refused to conclude, and what it recommends.
 *
 * The rejected claims are shown deliberately. A reviewer's trust comes from
 * seeing what the system threw away, not only what it kept.
 */
export function InvestigationCard({ investigation }: { investigation: Investigation }) {
  const [tab, setTab] = useState<Tab>('findings')

  const supported = investigation.claims.filter((claim) => claim.status === 'SUPPORTED')
  const partial = investigation.claims.filter((claim) => claim.status === 'PARTIALLY_SUPPORTED')
  const rejected = investigation.claims.filter(
    (claim) => claim.status === 'UNSUPPORTED' || claim.status === 'CONTRADICTED',
  )
  const metrics = supported.filter((claim) => claim.claim_type === 'CALCULATED_METRIC')
  const observations = supported.filter((claim) => claim.claim_type === 'OBSERVED_FACT')
  const inferences = supported.filter((claim) => claim.claim_type === 'INFERENCE')
  const signals = investigation.quantitative_signals?.assessment?.signals ?? []

  return (
    <GlassPanel className="overflow-hidden">
      <header className="border-b border-[var(--glass-border)] px-4 py-3.5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Link
                href={`/customers/${investigation.external_id}`}
                className="text-[15px] font-semibold tracking-[-0.01em] text-ink hover:text-accent"
              >
                {investigation.company_name || investigation.external_id}
              </Link>
              <RiskBadge level={investigation.risk_level} score={investigation.risk_score} />
              <Badge tone="muted">{investigation.account_tier.replace('_', ' ')}</Badge>
            </div>
            <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[11px] text-ink-muted">
              <span>{investigation.external_id}</span>
              <span>MRR {formatCurrency(investigation.monthly_recurring_revenue)}</span>
              <span>Renews {formatDate(investigation.renewal_date)}</span>
              <span>Confidence {formatRatio(investigation.confidence)}</span>
            </p>
          </div>
          <Link
            href={`/customers/${investigation.external_id}`}
            className="inline-flex items-center gap-1.5 text-[12.5px] text-accent hover:underline"
          >
            Account detail
            <ArrowRightIcon className="h-3.5 w-3.5" />
          </Link>
        </div>

        <p className="mt-3 text-[13px] leading-relaxed text-ink-secondary">{investigation.summary}</p>

        <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 font-mono text-[11px]">
          <ScoreBit label="Deterministic score" value={investigation.heuristic_risk_score.toFixed(1)} />
          <ScoreBit label="After investigation" value={investigation.risk_score.toFixed(1)} />
          <ScoreBit label="Supported claims" value={`${supported.length}/${investigation.claims.length}`} />
          <ScoreBit label="Rejected" value={String(rejected.length)} />
          <ScoreBit label="Evidence" value={String(investigation.evidence.length)} />
        </dl>
      </header>

      <nav className="flex gap-1 overflow-x-auto border-b border-[var(--glass-border)] px-3 py-2" aria-label="Investigation detail">
        {TABS.map((item) => {
          const count =
            item.id === 'claims'
              ? investigation.claims.length
              : item.id === 'evidence'
                ? investigation.evidence.length
                : item.id === 'signals'
                  ? signals.length
                  : item.id === 'actions'
                    ? investigation.recommended_actions.length
                    : null
          const active = tab === item.id
          return (
            <button
              key={item.id}
              type="button"
              aria-pressed={active}
              onClick={() => setTab(item.id)}
              className={
                active
                  ? 'shrink-0 rounded-lg bg-accent-wash px-2.5 py-1 text-[12px] font-medium text-accent'
                  : 'shrink-0 rounded-lg px-2.5 py-1 text-[12px] text-ink-secondary hover:bg-surface-sunken hover:text-ink'
              }
            >
              {item.label}
              {count !== null ? <span className="ml-1.5 tabular-nums opacity-70">{count}</span> : null}
            </button>
          )
        })}
      </nav>

      <div className="px-4 py-4">
        {tab === 'findings' ? (
          <div className="space-y-5">
            <ClaimGroup
              title="Verified quantitative indicators"
              description="Numbers the platform computed, restated and checked against the metric record they came from."
              claims={metrics}
              emptyText="No calculated metrics were verified for this account."
            />
            <ClaimGroup
              title="Verified qualitative evidence"
              description="Statements a document or record actually makes."
              claims={observations}
              emptyText="No document-based observations were verified for this account."
            />
            <ClaimGroup
              title="Verified conclusions"
              description="Interpretations, reported as interpretations."
              claims={inferences}
              emptyText="No inferences were verified for this account."
            />

            {investigation.risk_factors.length > 0 ? (
              <section>
                <h4 className="text-[12.5px] font-semibold text-ink">Risk factors</h4>
                <ul className="mt-2 space-y-2">
                  {investigation.risk_factors.map((factor, index) => (
                    <li key={index} className="rounded-card border border-[var(--line)] bg-surface-sunken p-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[12.5px] font-medium text-ink">{factor.factor}</span>
                        <Badge
                          tone={
                            factor.severity === 'CRITICAL'
                              ? 'critical'
                              : factor.severity === 'HIGH'
                                ? 'serious'
                                : factor.severity === 'MEDIUM'
                                  ? 'warning'
                                  : 'good'
                          }
                          icon={<AlertIcon className="h-3 w-3" />}
                        >
                          {humanise(factor.severity)}
                        </Badge>
                        {factor.evidence_references.map((reference) => (
                          <EvidenceRef key={reference} reference={reference} />
                        ))}
                      </div>
                      <p className="mt-1 text-[12px] leading-snug text-ink-secondary">{factor.explanation}</p>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {partial.length > 0 ? (
              <ClaimGroup
                title="Qualified findings"
                description="The evidence supports the direction but not the original wording, so these are reported with their qualifier."
                claims={partial}
                emptyText=""
                useFinalText
              />
            ) : null}

            {rejected.length > 0 ? (
              <section>
                <h4 className="flex items-center gap-2 text-[12.5px] font-semibold text-ink">
                  <CrossIcon className="h-3.5 w-3.5 text-[var(--status-critical)]" />
                  Excluded conclusions
                </h4>
                <p className="mt-0.5 text-[11.5px] text-ink-muted">
                  The investigator produced these; verification rejected them, so they are not asserted
                  anywhere in the report.
                </p>
                <ul className="mt-2 space-y-2">
                  {rejected.map((claim) => (
                    <li
                      key={claim.id}
                      className="rounded-card border border-[color-mix(in_srgb,var(--status-critical)_28%,transparent)] bg-[color-mix(in_srgb,var(--status-critical)_7%,transparent)] p-3"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <ClaimStatusBadge status={claim.status} />
                        {claim.evidence_references.map((reference) => (
                          <EvidenceRef key={reference} reference={reference} />
                        ))}
                      </div>
                      <p className="mt-1.5 text-[12.5px] leading-snug text-ink line-through decoration-[var(--status-critical)]/50">
                        {claim.claim_text}
                      </p>
                      {claim.verification_reason ? (
                        <p className="mt-1.5 text-[11.5px] leading-snug text-ink-secondary">
                          <span className="font-medium text-ink">Why it was rejected: </span>
                          {claim.verification_reason}
                        </p>
                      ) : null}
                      {claim.suggested_revision ? (
                        <p className="mt-1 text-[11.5px] leading-snug text-ink-secondary">
                          <span className="font-medium text-ink">The evidence supports instead: </span>
                          {claim.suggested_revision}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}

            {investigation.data_gaps.length > 0 ? (
              <section className="rounded-card border border-[var(--line)] bg-surface-sunken p-3">
                <h4 className="text-[12.5px] font-semibold text-ink">Insufficient evidence</h4>
                <ul className="mt-1.5 space-y-1 text-[12px] text-ink-secondary">
                  {investigation.data_gaps.map((gap, index) => (
                    <li key={index} className="flex gap-2">
                      <span aria-hidden className="text-ink-muted">
                        ·
                      </span>
                      {gap}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </div>
        ) : null}

        {tab === 'claims' ? (
          <ul className="space-y-2">
            {investigation.claims.map((claim) => (
              <li key={claim.id} className="rounded-card border border-[var(--line)] bg-surface-sunken p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <ClaimStatusBadge status={claim.status} reason={claim.verification_reason} />
                  <Badge tone="muted">{humanise(claim.claim_type)}</Badge>
                  <span className="font-mono text-[10.5px] text-ink-muted">
                    confidence {formatRatio(claim.confidence)}
                  </span>
                  {claim.evidence_references.map((reference) => (
                    <EvidenceRef key={reference} reference={reference} />
                  ))}
                </div>
                <p className="mt-1.5 text-[12.5px] leading-snug text-ink">{claim.claim_text}</p>
                {claim.final_text && claim.final_text !== claim.claim_text ? (
                  <p className="mt-1 text-[11.5px] leading-snug text-ink-secondary">
                    <span className="font-medium text-ink">Reported as: </span>
                    {claim.final_text}
                  </p>
                ) : null}
                {claim.verification_reason ? (
                  <p className="mt-1 text-[11.5px] leading-snug text-ink-muted">
                    {claim.verification_reason}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}

        {tab === 'evidence' ? (
          <div className="space-y-2.5">
            {investigation.evidence.length === 0 ? (
              <p className="text-[12.5px] text-ink-muted">No evidence was retrieved for this account.</p>
            ) : (
              investigation.evidence.map((item) => <EvidenceCard key={item.id} item={item} />)
            )}
          </div>
        ) : null}

        {tab === 'signals' ? (
          <div>
            <p className="mb-3 text-[11.5px] text-ink-muted">
              Contribution to the deterministic score, in points. Computed in code, never by a model.
            </p>
            <RiskSignalBars signals={signals} />
            {(investigation.quantitative_signals?.assessment?.missing_signals ?? []).length > 0 ? (
              <p className="mt-3 border-t border-[var(--line)] pt-2 text-[11.5px] text-ink-muted">
                No data for:{' '}
                {(investigation.quantitative_signals?.assessment?.missing_signals ?? [])
                  .map((key) => key.replace(/_/g, ' '))
                  .join(', ')}
                . The score is renormalised over the signals that were available.
              </p>
            ) : null}
          </div>
        ) : null}

        {tab === 'actions' ? (
          <ul className="space-y-2">
            {investigation.recommended_actions.length === 0 ? (
              <p className="text-[12.5px] text-ink-muted">No actions were recommended for this account.</p>
            ) : (
              investigation.recommended_actions.map((action, index) => (
                <li key={index} className="rounded-card border border-[var(--line)] bg-surface-sunken p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-[11px] font-medium text-ink">
                      {action.action_type}
                    </span>
                    {action.requires_approval ? (
                      <Badge tone="warning" icon={<ShieldIcon className="h-3 w-3" />}>
                        Requires approval
                      </Badge>
                    ) : (
                      <Badge tone="good" icon={<CheckIcon className="h-3 w-3" />}>
                        Internal — no approval needed
                      </Badge>
                    )}
                    {action.approval_status ? (
                      <Badge tone={action.approval_status === 'APPROVED' ? 'good' : action.approval_status === 'REJECTED' ? 'critical' : 'muted'}>
                        {humanise(action.approval_status)}
                      </Badge>
                    ) : null}
                    <span className="font-mono text-[10.5px] text-ink-muted">priority {action.priority}</span>
                  </div>
                  <p className="mt-1.5 text-[12.5px] text-ink">{action.description}</p>
                  {action.rationale ? (
                    <p className="mt-0.5 text-[11.5px] text-ink-muted">{action.rationale}</p>
                  ) : null}
                </li>
              ))
            )}
          </ul>
        ) : null}
      </div>
    </GlassPanel>
  )
}

function ScoreBit({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="font-medium tabular-nums text-ink">{value}</dd>
    </div>
  )
}

function EvidenceRef({ reference }: { reference: string }) {
  return (
    <a
      href={`#evidence-${reference}`}
      className="rounded bg-accent-wash px-1.5 py-0.5 font-mono text-[10.5px] font-medium text-accent hover:underline"
      title="Jump to this evidence record"
    >
      {reference}
    </a>
  )
}

function ClaimGroup({
  title,
  description,
  claims,
  emptyText,
  useFinalText = false,
}: {
  title: string
  description: string
  claims: ClaimItem[]
  emptyText: string
  useFinalText?: boolean
}) {
  if (claims.length === 0 && !emptyText) return null
  return (
    <section>
      <h4 className="text-[12.5px] font-semibold text-ink">{title}</h4>
      <p className="mt-0.5 text-[11.5px] text-ink-muted">{description}</p>
      {claims.length === 0 ? (
        <p className="mt-2 text-[12px] text-ink-muted">{emptyText}</p>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {claims.map((claim) => (
            <li key={claim.id} className="flex gap-2.5 text-[12.5px] leading-snug text-ink-secondary">
              <CheckIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--status-good)]" />
              <span className="min-w-0">
                {useFinalText ? (claim.final_text ?? claim.claim_text) : claim.claim_text}
                {claim.evidence_references.length > 0 ? (
                  <span className="ml-1.5 inline-flex gap-1">
                    {claim.evidence_references.map((reference) => (
                      <EvidenceRef key={reference} reference={reference} />
                    ))}
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
