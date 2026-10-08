'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { LiquidGlassSurface } from '@/components/ui/LiquidGlassSurface'
import {
  Badge,
  Button,
  ErrorState,
  GlassPanel,
  Panel,
  SectionHeader,
  SparkIcon,
} from '@/components/ui/primitives'
import { ApiError, api } from '@/lib/api'
import { DEFAULT_OBJECTIVE, config } from '@/lib/config'
import type { AccountTier, WorkflowMode } from '@/lib/types'

const MAX_OBJECTIVE = 4000
const MIN_OBJECTIVE = 20

const TIERS: Array<{ value: AccountTier | ''; label: string }> = [
  { value: '', label: 'Any tier' },
  { value: 'ENTERPRISE', label: 'Enterprise' },
  { value: 'MID_MARKET', label: 'Mid-market' },
  { value: 'SMB', label: 'SMB' },
  { value: 'STARTUP', label: 'Startup' },
]

const WINDOWS = [30, 60, 90, 120, 180, 365]

const MODES: Array<{ value: WorkflowMode; label: string; description: string }> = [
  {
    value: 'STANDARD',
    label: 'Standard',
    description: 'Customer-facing and commercial actions need approval; internal actions do not.',
  },
  {
    value: 'REVIEW_ALL',
    label: 'Review everything',
    description: 'Every recommended action is held for human review, including internal ones.',
  },
  {
    value: 'READ_ONLY',
    label: 'Read-only',
    description: 'Investigate and report only. Nothing may be actioned without explicit review.',
  },
]

export default function NewInvestigationPage() {
  const router = useRouter()
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE)
  const [tier, setTier] = useState<AccountTier | ''>('ENTERPRISE')
  const [window, setWindow] = useState(90)
  const [maxAccounts, setMaxAccounts] = useState(5)
  const [mode, setMode] = useState<WorkflowMode>('STANDARD')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const trimmed = objective.trim()
  const tooShort = trimmed.length > 0 && trimmed.length < MIN_OBJECTIVE
  const tooLong = trimmed.length > MAX_OBJECTIVE
  const canSubmit = trimmed.length >= MIN_OBJECTIVE && !tooLong && !submitting

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!canSubmit) return
    setSubmitting(true)
    setError(null)
    try {
      const response = await api.createRun({
        objective: trimmed,
        account_tier: tier === '' ? null : tier,
        renewal_window_days: window,
        max_accounts: maxAccounts,
        workflow_mode: mode,
      })
      // The POST returns as soon as the run is QUEUED; execution continues on
      // the workers, and the run page streams the state from there.
      router.push(`/runs/${response.run_id}`)
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, 'unexpected_error', caught instanceof Error ? caught.message : String(caught)),
      )
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="mb-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
          New investigation
        </div>
        <h1 className="text-[26px] font-semibold tracking-[-0.025em] text-ink">
          What should {config.productName} investigate?
        </h1>
        <p className="mt-1.5 max-w-2xl text-[13px] text-ink-secondary">
          Describe the outcome you want in business terms. The planner turns it into a validated task
          graph; the platform selects and scores the accounts deterministically before any model reasons
          about them.
        </p>
      </div>

      <form onSubmit={submit} className="space-y-5">
        {/* The one surface that carries the WebGL liquid-glass accent. */}
        <LiquidGlassSurface className="overflow-hidden rounded-panel">
          <div className="p-5 sm:p-6">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <label
                htmlFor="objective"
                className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted"
              >
                Business objective
              </label>
              <span
                className={
                  tooLong
                    ? 'font-mono text-[11px] tabular-nums text-[var(--status-critical)]'
                    : 'font-mono text-[11px] tabular-nums text-ink-muted'
                }
              >
                {trimmed.length.toLocaleString()} / {MAX_OBJECTIVE.toLocaleString()}
              </span>
            </div>

            <textarea
              id="objective"
              name="objective"
              value={objective}
              onChange={(event) => setObjective(event.target.value)}
              rows={5}
              maxLength={MAX_OBJECTIVE + 200}
              aria-describedby="objective-help"
              aria-invalid={tooShort || tooLong}
              placeholder="e.g. Analyze enterprise customers renewing within the next 90 days and identify the accounts at highest risk of churn."
              className="w-full resize-y rounded-xl border border-[var(--line-strong)] bg-[color-mix(in_srgb,var(--surface-sunken)_80%,transparent)] px-4 py-3.5 text-[15px] leading-relaxed text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
            />

            <p id="objective-help" className="mt-2 text-[12px] text-ink-muted">
              {tooShort
                ? `Add a little more detail — at least ${MIN_OBJECTIVE} characters.`
                : 'Veriflow V1 implements the B2B SaaS churn-investigation workflow. Objectives outside that domain are refused rather than answered badly.'}
            </p>

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Badge tone="muted">PostgreSQL + pgvector</Badge>
              <Badge tone="muted">Deterministic risk screen</Badge>
              <Badge tone="muted">Independent verification</Badge>
              <Badge tone="muted">Human approval gate</Badge>
            </div>

            <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--glass-border)] pt-4">
              <button
                type="button"
                onClick={() => setObjective(DEFAULT_OBJECTIVE)}
                className="text-[12.5px] text-ink-muted underline-offset-2 hover:text-ink hover:underline"
              >
                Reset to the example objective
              </button>
              <Button
                type="submit"
                variant="primary"
                size="lg"
                loading={submitting}
                disabled={!canSubmit}
                icon={submitting ? undefined : <SparkIcon className="h-4 w-4" />}
              >
                {submitting ? 'Queueing run…' : 'Start investigation'}
              </Button>
            </div>
          </div>
        </LiquidGlassSurface>

        {error ? <ErrorState error={error} /> : null}

        <div className="grid gap-4 lg:grid-cols-3">
          <Panel className="p-4 lg:col-span-2">
            <SectionHeader
              eyebrow="Scope"
              title="Structured controls"
              description="These are applied as validated parameters. Anything you leave alone is parsed from the objective text by deterministic rules — never guessed by a model."
            />

            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Field label="Account tier" htmlFor="tier" hint="Filters candidate selection by segment.">
                <select
                  id="tier"
                  value={tier}
                  onChange={(event) => setTier(event.target.value as AccountTier | '')}
                  className="h-9.5 w-full rounded-lg border border-[var(--line-strong)] bg-surface-sunken px-3 text-[13px] text-ink focus:border-accent focus:outline-none"
                >
                  {TIERS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>

              <Field
                label="Renewal window"
                htmlFor="window"
                hint="Only accounts renewing inside this window are considered."
              >
                <select
                  id="window"
                  value={window}
                  onChange={(event) => setWindow(Number(event.target.value))}
                  className="h-9.5 w-full rounded-lg border border-[var(--line-strong)] bg-surface-sunken px-3 text-[13px] text-ink focus:border-accent focus:outline-none"
                >
                  {WINDOWS.map((days) => (
                    <option key={days} value={days}>
                      Next {days} days
                    </option>
                  ))}
                </select>
              </Field>

              <Field
                label={`Maximum accounts — ${maxAccounts}`}
                htmlFor="max-accounts"
                hint="Bounds cost: only this many accounts reach the LLM investigator."
              >
                <input
                  id="max-accounts"
                  type="range"
                  min={1}
                  max={10}
                  step={1}
                  value={maxAccounts}
                  onChange={(event) => setMaxAccounts(Number(event.target.value))}
                  className="h-9.5 w-full accent-[var(--accent)]"
                />
              </Field>

              <Field label="Workflow mode" htmlFor="mode" hint={MODES.find((m) => m.value === mode)?.description}>
                <select
                  id="mode"
                  value={mode}
                  onChange={(event) => setMode(event.target.value as WorkflowMode)}
                  className="h-9.5 w-full rounded-lg border border-[var(--line-strong)] bg-surface-sunken px-3 text-[13px] text-ink focus:border-accent focus:outline-none"
                >
                  {MODES.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </Panel>

          <GlassPanel className="p-4">
            <SectionHeader eyebrow="What happens next" title="Execution plan" />
            <ol className="mt-3 space-y-2.5">
              {[
                ['Planning', 'The planner emits a task DAG, validated against the agents and tasks that exist.'],
                ['Candidate selection', 'Indexed SQL on renewal date and tier. No model picks the accounts.'],
                ['Risk screening', 'A transparent weighted heuristic scores and ranks every candidate.'],
                ['Investigation', 'Selected accounts are investigated concurrently with bounded parallelism.'],
                ['Verification', 'Each claim is checked independently against its cited evidence.'],
                ['Report', 'Composed from verified material only; rejected claims are listed, never asserted.'],
                ['Approval', 'Sensitive actions become approval requests and the run waits for a human.'],
              ].map(([title, description], index) => (
                <li key={title} className="flex gap-3">
                  <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-accent-wash font-mono text-[10px] font-semibold text-accent">
                    {index + 1}
                  </span>
                  <div className="min-w-0">
                    <div className="text-[12.5px] font-medium text-ink">{title}</div>
                    <p className="text-[11.5px] leading-snug text-ink-muted">{description}</p>
                  </div>
                </li>
              ))}
            </ol>
          </GlassPanel>
        </div>
      </form>
    </div>
  )
}

function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string
  htmlFor: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 block text-[12.5px] font-medium text-ink">
        {label}
      </label>
      {children}
      {hint ? <p className="mt-1.5 text-[11.5px] leading-snug text-ink-muted">{hint}</p> : null}
    </div>
  )
}
