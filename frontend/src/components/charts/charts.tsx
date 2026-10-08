'use client'

/**
 * Charts.
 *
 * Colour comes from the validated token palette (`--series-*` for identity,
 * the sequential blue ramp for magnitude, the fixed status palette for state),
 * re-validated against this app's own surfaces. Rules kept throughout:
 *
 *   - one y-axis, never two;
 *   - categorical hues assigned by slot in fixed order, never cycled;
 *   - a legend whenever there are two or more series, plus direct labels;
 *   - recessive grid and axes, thin marks, rounded data-ends;
 *   - a hover tooltip on every plotted form;
 *   - a table view behind a toggle, which is also the relief for the
 *     light-mode series that sit below 3:1 against white.
 */

import { useId, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Button, Cell as TCell, Panel, Row, Table } from '@/components/ui/primitives'
import { severityColour } from '@/components/ui/status'
import { formatDateShort, formatNumber, formatPercent } from '@/lib/format'

const AXIS = { stroke: 'var(--baseline)', fontSize: 11 }
const GRID = 'var(--gridline)'

/* -------------------------------------------------------------------------- */
/* Chart frame: title, legend, table toggle                                   */
/* -------------------------------------------------------------------------- */

export function ChartFrame({
  title,
  subtitle,
  legend,
  table,
  children,
  height = 240,
}: {
  title: string
  subtitle?: string
  legend?: Array<{ label: string; colour: string }>
  table?: React.ReactNode
  children: React.ReactNode
  height?: number
}) {
  const [showTable, setShowTable] = useState(false)
  const tableId = useId()

  return (
    <Panel className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold text-ink">{title}</h3>
          {subtitle ? <p className="mt-0.5 text-[11.5px] text-ink-muted">{subtitle}</p> : null}
        </div>
        <div className="flex items-center gap-3">
          {legend && legend.length > 1 ? (
            <ul className="flex flex-wrap items-center gap-3">
              {legend.map((entry) => (
                <li key={entry.label} className="flex items-center gap-1.5 text-[11.5px] text-ink-secondary">
                  <span
                    aria-hidden
                    className="h-2 w-2 shrink-0 rounded-sm ring-1 ring-[var(--surface)]"
                    style={{ background: entry.colour }}
                  />
                  {entry.label}
                </li>
              ))}
            </ul>
          ) : null}
          {table ? (
            <Button
              size="sm"
              variant="ghost"
              aria-expanded={showTable}
              aria-controls={tableId}
              onClick={() => setShowTable((value) => !value)}
            >
              {showTable ? 'Hide data' : 'View data'}
            </Button>
          ) : null}
        </div>
      </div>

      <div className="mt-3" style={{ height }}>
        {children}
      </div>

      {table ? (
        <div id={tableId} hidden={!showTable} className="mt-3 border-t border-[var(--line)] pt-2">
          {table}
        </div>
      ) : null}
    </Panel>
  )
}

function TooltipShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-[var(--line-strong)] bg-[var(--surface-raised)] px-3 py-2 text-[12px] shadow-lg">
      {children}
    </div>
  )
}

interface TooltipEntry {
  name?: string | number
  value?: number | string
  color?: string
  dataKey?: string | number
}

/* -------------------------------------------------------------------------- */
/* Usage over time — two series, line, crosshair tooltip                      */
/* -------------------------------------------------------------------------- */

export function UsageTrendChart({
  points,
}: {
  points: Array<{ usage_date: string; active_users: number; seats_active: number }>
}) {
  if (points.length === 0) {
    return (
      <ChartFrame title="Active users over time" height={120}>
        <p className="flex h-full items-center justify-center text-[12.5px] text-ink-muted">
          No usage history is recorded for this account.
        </p>
      </ChartFrame>
    )
  }

  const legend = [
    { label: 'Active users', colour: 'var(--series-1)' },
    { label: 'Active seats', colour: 'var(--series-2)' },
  ]

  return (
    <ChartFrame
      title="Active users over time"
      subtitle={`${points.length} weekly observations · active users against seats in use`}
      legend={legend}
      height={240}
      table={
        <Table head={['Week', 'Active users', 'Active seats']}>
          {points.map((point) => (
            <Row key={point.usage_date}>
              <TCell mono>{formatDateShort(point.usage_date)}</TCell>
              <TCell numeric>{formatNumber(point.active_users)}</TCell>
              <TCell numeric>{formatNumber(point.seats_active)}</TCell>
            </Row>
          ))}
        </Table>
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis
            dataKey="usage_date"
            tickFormatter={formatDateShort}
            {...AXIS}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis {...AXIS} tickLine={false} axisLine={false} width={44} allowDecimals={false} />
          <Tooltip
            cursor={{ stroke: 'var(--line-strong)', strokeWidth: 1 }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <TooltipShell>
                  <div className="mb-1 font-medium text-ink">{formatDateShort(String(label))}</div>
                  {(payload as TooltipEntry[]).map((entry) => (
                    <div key={String(entry.dataKey)} className="flex items-center gap-2 text-ink-secondary">
                      <span
                        aria-hidden
                        className="h-2 w-2 rounded-sm"
                        style={{ background: entry.color }}
                      />
                      <span>{entry.dataKey === 'active_users' ? 'Active users' : 'Active seats'}</span>
                      <span className="ml-auto font-medium tabular-nums text-ink">
                        {formatNumber(Number(entry.value))}
                      </span>
                    </div>
                  ))}
                </TooltipShell>
              ) : null
            }
          />
          <Line
            type="monotone"
            dataKey="active_users"
            stroke="var(--series-1)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }}
          />
          <Line
            type="monotone"
            dataKey="seats_active"
            stroke="var(--series-2)"
            strokeWidth={2}
            strokeDasharray="4 3"
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--surface)' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}

/* -------------------------------------------------------------------------- */
/* Support volume — single series bar                                         */
/* -------------------------------------------------------------------------- */

export function TicketVolumeChart({
  buckets,
}: {
  buckets: Array<{ label: string; tickets: number; unresolved: number }>
}) {
  if (buckets.every((bucket) => bucket.tickets === 0)) {
    return (
      <ChartFrame title="Support ticket volume" height={120}>
        <p className="flex h-full items-center justify-center text-[12.5px] text-ink-muted">
          No support tickets are recorded for this account.
        </p>
      </ChartFrame>
    )
  }

  const legend = [
    { label: 'Resolved', colour: 'var(--series-1)' },
    { label: 'Unresolved', colour: 'var(--status-critical)' },
  ]

  return (
    <ChartFrame
      title="Support ticket volume"
      subtitle="Monthly tickets created, with the unresolved share called out"
      legend={legend}
      height={200}
      table={
        <Table head={['Month', 'Tickets', 'Unresolved']}>
          {buckets.map((bucket) => (
            <Row key={bucket.label}>
              <TCell mono>{bucket.label}</TCell>
              <TCell numeric>{formatNumber(bucket.tickets)}</TCell>
              <TCell numeric>{formatNumber(bucket.unresolved)}</TCell>
            </Row>
          ))}
        </Table>
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={buckets} margin={{ top: 8, right: 12, bottom: 0, left: -12 }} barGap={2}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="label" {...AXIS} tickLine={false} />
          <YAxis {...AXIS} tickLine={false} axisLine={false} width={40} allowDecimals={false} />
          <Tooltip
            cursor={{ fill: 'var(--surface-sunken)' }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <TooltipShell>
                  <div className="mb-1 font-medium text-ink">{String(label)}</div>
                  {(payload as TooltipEntry[]).map((entry) => (
                    <div key={String(entry.dataKey)} className="flex items-center gap-2 text-ink-secondary">
                      <span aria-hidden className="h-2 w-2 rounded-sm" style={{ background: entry.color }} />
                      <span>{entry.dataKey === 'tickets' ? 'Resolved' : 'Unresolved'}</span>
                      <span className="ml-auto font-medium tabular-nums text-ink">
                        {formatNumber(Number(entry.value))}
                      </span>
                    </div>
                  ))}
                </TooltipShell>
              ) : null
            }
          />
          <Bar dataKey="tickets" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={26} />
          <Bar dataKey="unresolved" fill="var(--status-critical)" radius={[4, 4, 0, 0]} maxBarSize={26} />
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}

/* -------------------------------------------------------------------------- */
/* Risk signal contribution — horizontal bars, severity-coloured, labelled    */
/* -------------------------------------------------------------------------- */

export function RiskSignalBars({
  signals,
}: {
  signals: Array<{ key: string; label: string; contribution: number; severity: number; detail: string }>
}) {
  const ranked = [...signals].sort((a, b) => b.contribution - a.contribution)
  const max = Math.max(1, ...ranked.map((signal) => signal.contribution))

  if (ranked.length === 0) {
    return (
      <p className="py-6 text-center text-[12.5px] text-ink-muted">
        No risk signals could be computed — this account has no usable history.
      </p>
    )
  }

  return (
    <ul className="space-y-2.5">
      {ranked.map((signal) => (
        <li key={signal.key}>
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-[12.5px] font-medium text-ink">{signal.label}</span>
            <span className="shrink-0 font-mono text-[11.5px] tabular-nums text-ink-secondary">
              {signal.contribution.toFixed(1)} pts
            </span>
          </div>
          <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
            <div
              className="h-full rounded-full"
              style={{
                width: `${Math.max(2, (signal.contribution / max) * 100)}%`,
                background: severityColour(signal.severity),
              }}
            />
          </div>
          <p className="mt-1 text-[11.5px] leading-snug text-ink-muted">{signal.detail}</p>
        </li>
      ))}
    </ul>
  )
}

/* -------------------------------------------------------------------------- */
/* Verification split — state, so the fixed status palette + icon + label     */
/* -------------------------------------------------------------------------- */

export function VerificationSplit({
  counts,
  total,
}: {
  counts: { supported: number; partial: number; rejected: number; pending: number }
  total: number
}) {
  if (total === 0) {
    return <p className="text-[12.5px] text-ink-muted">No claims have been produced yet.</p>
  }

  const segments = [
    { key: 'supported', label: 'Supported', value: counts.supported, colour: 'var(--status-good)' },
    { key: 'partial', label: 'Partially supported', value: counts.partial, colour: 'var(--status-warning)' },
    { key: 'rejected', label: 'Rejected', value: counts.rejected, colour: 'var(--status-critical)' },
    { key: 'pending', label: 'Unverified', value: counts.pending, colour: 'var(--ink-muted)' },
  ].filter((segment) => segment.value > 0)

  return (
    <div>
      <div className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full bg-surface-sunken">
        {segments.map((segment) => (
          <div
            key={segment.key}
            title={`${segment.label}: ${segment.value} of ${total}`}
            style={{ width: `${(segment.value / total) * 100}%`, background: segment.colour }}
            className="h-full first:rounded-l-full last:rounded-r-full"
          />
        ))}
      </div>
      <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5">
        {segments.map((segment) => (
          <li key={segment.key} className="flex items-center gap-1.5 text-[11.5px] text-ink-secondary">
            <span aria-hidden className="h-2 w-2 rounded-sm" style={{ background: segment.colour }} />
            <span>{segment.label}</span>
            <span className="font-medium tabular-nums text-ink">
              {segment.value} ({formatPercent((segment.value / total) * 100, 0)})
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Evaluation: precision & recall at K — two series, grouped bars             */
/* -------------------------------------------------------------------------- */

export function PrecisionRecallChart({
  rows,
}: {
  rows: Array<{ k: string; precision: number; recall: number | null }>
}) {
  if (rows.length === 0) {
    return (
      <ChartFrame title="Precision and recall at K" height={120}>
        <p className="flex h-full items-center justify-center text-[12.5px] text-ink-muted">
          No labelled outcomes available — seed the database and re-run the evaluation.
        </p>
      </ChartFrame>
    )
  }

  const legend = [
    { label: 'Precision', colour: 'var(--series-1)' },
    { label: 'Recall', colour: 'var(--series-2)' },
  ]
  const data = rows.map((row) => ({
    k: `Top ${row.k}`,
    precision: Number((row.precision * 100).toFixed(1)),
    recall: row.recall === null ? 0 : Number((row.recall * 100).toFixed(1)),
  }))

  return (
    <ChartFrame
      title="Precision and recall at K"
      subtitle="How many of the top-K highest-scoring accounts actually churned (synthetic dataset)"
      legend={legend}
      height={230}
      table={
        <Table head={['Cutoff', 'Precision', 'Recall']}>
          {rows.map((row) => (
            <Row key={row.k}>
              <TCell mono>Top {row.k}</TCell>
              <TCell numeric>{formatPercent(row.precision * 100, 1)}</TCell>
              <TCell numeric>{row.recall === null ? '—' : formatPercent(row.recall * 100, 1)}</TCell>
            </Row>
          ))}
        </Table>
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 16, right: 12, bottom: 0, left: -12 }} barGap={3}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="k" {...AXIS} tickLine={false} />
          <YAxis
            {...AXIS}
            tickLine={false}
            axisLine={false}
            width={44}
            domain={[0, 100]}
            tickFormatter={(value) => `${value}%`}
          />
          <Tooltip
            cursor={{ fill: 'var(--surface-sunken)' }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <TooltipShell>
                  <div className="mb-1 font-medium text-ink">{String(label)}</div>
                  {(payload as TooltipEntry[]).map((entry) => (
                    <div key={String(entry.dataKey)} className="flex items-center gap-2 text-ink-secondary">
                      <span aria-hidden className="h-2 w-2 rounded-sm" style={{ background: entry.color }} />
                      <span>{entry.dataKey === 'precision' ? 'Precision' : 'Recall'}</span>
                      <span className="ml-auto font-medium tabular-nums text-ink">
                        {Number(entry.value).toFixed(1)}%
                      </span>
                    </div>
                  ))}
                </TooltipShell>
              ) : null
            }
          />
          <Bar dataKey="precision" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={30} />
          <Bar dataKey="recall" fill="var(--series-2)" radius={[4, 4, 0, 0]} maxBarSize={30} />
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}

/* -------------------------------------------------------------------------- */
/* Evaluation: score separation — one series, magnitude, sequential ramp      */
/* -------------------------------------------------------------------------- */

export function ScoreSeparationChart({
  positive,
  negative,
}: {
  positive: number | null
  negative: number | null
}) {
  if (positive === null || negative === null) {
    return null
  }
  const data = [
    { group: 'Churned / downgraded', score: Number(positive.toFixed(1)) },
    { group: 'Renewed / expanded', score: Number(negative.toFixed(1)) },
  ]

  return (
    <ChartFrame
      title="Mean risk score by actual outcome"
      subtitle="The gap between these two bars is the signal the screening model carries"
      height={180}
      table={
        <Table head={['Outcome group', 'Mean score']}>
          {data.map((row) => (
            <Row key={row.group}>
              <TCell>{row.group}</TCell>
              <TCell numeric>{row.score.toFixed(1)}</TCell>
            </Row>
          ))}
        </Table>
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 48, bottom: 0, left: 4 }}>
          <CartesianGrid stroke={GRID} horizontal={false} />
          <XAxis type="number" domain={[0, 100]} {...AXIS} tickLine={false} axisLine={false} />
          <YAxis type="category" dataKey="group" {...AXIS} tickLine={false} width={150} />
          <Tooltip
            cursor={{ fill: 'var(--surface-sunken)' }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <TooltipShell>
                  <span className="font-medium tabular-nums text-ink">
                    Mean score {Number((payload[0] as TooltipEntry).value).toFixed(1)} / 100
                  </span>
                </TooltipShell>
              ) : null
            }
          />
          <Bar dataKey="score" radius={[0, 4, 4, 0]} maxBarSize={28} label={ScoreLabel}>
            {/* Magnitude, so one hue: the darker step marks the higher-risk group. */}
            <Cell fill="var(--seq-550)" />
            <Cell fill="var(--seq-250)" />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}

function ScoreLabel({
  x,
  y,
  width,
  height,
  value,
}: {
  x?: number
  y?: number
  width?: number
  height?: number
  value?: number
}) {
  if (x === undefined || y === undefined || width === undefined || height === undefined) {
    return <g />
  }
  return (
    <text
      x={x + width + 8}
      y={y + height / 2}
      dominantBaseline="middle"
      fill="var(--ink-secondary)"
      fontSize={11}
      className="tabular-nums"
    >
      {Number(value).toFixed(1)}
    </text>
  )
}
