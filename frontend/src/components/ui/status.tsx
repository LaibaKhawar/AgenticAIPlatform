'use client'

/**
 * Status rendering.
 *
 * Status is never communicated by colour alone: every badge here carries an
 * icon and a text label, which is also what keeps the fixed status palette
 * legible for colour-vision deficiency and in forced-colours mode.
 */

import type { ReactNode } from 'react'
import {
  AlertIcon,
  Badge,
  CheckIcon,
  ClockIcon,
  CrossIcon,
  DashIcon,
  PauseIcon,
  SkipIcon,
  SpinIcon,
  type Tone,
} from './primitives'
import type { ApprovalStatus, ClaimStatus, RiskLevel, RunStatus, StageStatus, TaskStatus } from '@/lib/types'

interface StatusMeta {
  label: string
  tone: Tone
  Icon: (props: { className?: string }) => ReactNode
}

const RUN_STATUS: Record<RunStatus, StatusMeta> = {
  PENDING: { label: 'Pending', tone: 'muted', Icon: ClockIcon },
  QUEUED: { label: 'Queued', tone: 'accent', Icon: ClockIcon },
  RUNNING: { label: 'Running', tone: 'accent', Icon: SpinIcon },
  RETRYING: { label: 'Retrying', tone: 'warning', Icon: SpinIcon },
  WAITING_FOR_APPROVAL: { label: 'Awaiting approval', tone: 'warning', Icon: PauseIcon },
  COMPLETED: { label: 'Completed', tone: 'good', Icon: CheckIcon },
  FAILED: { label: 'Failed', tone: 'critical', Icon: AlertIcon },
  CANCELLED: { label: 'Cancelled', tone: 'muted', Icon: CrossIcon },
}

const TASK_STATUS: Record<TaskStatus, StatusMeta> = {
  ...RUN_STATUS,
  SKIPPED: { label: 'Skipped', tone: 'muted', Icon: SkipIcon },
}

const STAGE_STATUS: Record<StageStatus, StatusMeta> = {
  ...TASK_STATUS,
  PARTIAL: { label: 'Partial', tone: 'warning', Icon: AlertIcon },
}

const CLAIM_STATUS: Record<ClaimStatus, StatusMeta> = {
  PENDING: { label: 'Unverified', tone: 'muted', Icon: ClockIcon },
  SUPPORTED: { label: 'Supported', tone: 'good', Icon: CheckIcon },
  PARTIALLY_SUPPORTED: { label: 'Partially supported', tone: 'warning', Icon: AlertIcon },
  UNSUPPORTED: { label: 'Unsupported', tone: 'critical', Icon: CrossIcon },
  CONTRADICTED: { label: 'Contradicted', tone: 'critical', Icon: CrossIcon },
}

const APPROVAL_STATUS: Record<ApprovalStatus, StatusMeta> = {
  PENDING: { label: 'Pending review', tone: 'warning', Icon: ClockIcon },
  APPROVED: { label: 'Approved', tone: 'good', Icon: CheckIcon },
  REJECTED: { label: 'Rejected', tone: 'critical', Icon: CrossIcon },
  EXPIRED: { label: 'Expired', tone: 'muted', Icon: DashIcon },
}

const RISK_LEVEL: Record<RiskLevel, StatusMeta> = {
  LOW: { label: 'Low', tone: 'good', Icon: CheckIcon },
  MEDIUM: { label: 'Medium', tone: 'warning', Icon: AlertIcon },
  HIGH: { label: 'High', tone: 'serious', Icon: AlertIcon },
  CRITICAL: { label: 'Critical', tone: 'critical', Icon: AlertIcon },
}

function StatusBadge({ meta, title }: { meta: StatusMeta; title?: string }) {
  const { Icon } = meta
  return (
    <Badge tone={meta.tone} icon={<Icon className="h-3 w-3" />} title={title}>
      {meta.label}
    </Badge>
  )
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <StatusBadge meta={RUN_STATUS[status] ?? RUN_STATUS.PENDING} />
}

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return <StatusBadge meta={TASK_STATUS[status] ?? TASK_STATUS.PENDING} />
}

export function StageStatusBadge({ status }: { status: StageStatus }) {
  return <StatusBadge meta={STAGE_STATUS[status] ?? STAGE_STATUS.PENDING} />
}

export function ClaimStatusBadge({ status, reason }: { status: ClaimStatus; reason?: string | null }) {
  return <StatusBadge meta={CLAIM_STATUS[status] ?? CLAIM_STATUS.PENDING} title={reason ?? undefined} />
}

export function ApprovalStatusBadge({ status }: { status: ApprovalStatus }) {
  return <StatusBadge meta={APPROVAL_STATUS[status] ?? APPROVAL_STATUS.PENDING} />
}

export function RiskBadge({ level, score }: { level: RiskLevel; score?: number }) {
  const meta = RISK_LEVEL[level] ?? RISK_LEVEL.LOW
  const { Icon } = meta
  return (
    <Badge tone={meta.tone} icon={<Icon className="h-3 w-3" />}>
      {meta.label}
      {score !== undefined ? <span className="tabular-nums opacity-80">· {score.toFixed(0)}</span> : null}
    </Badge>
  )
}

export function riskTone(level: RiskLevel): Tone {
  return (RISK_LEVEL[level] ?? RISK_LEVEL.LOW).tone
}

export function riskColour(level: RiskLevel): string {
  switch (level) {
    case 'CRITICAL':
      return 'var(--status-critical)'
    case 'HIGH':
      return 'var(--status-serious)'
    case 'MEDIUM':
      return 'var(--status-warning)'
    default:
      return 'var(--status-good)'
  }
}

export function severityColour(severity: number): string {
  if (severity >= 0.75) return 'var(--status-critical)'
  if (severity >= 0.5) return 'var(--status-serious)'
  if (severity >= 0.25) return 'var(--status-warning)'
  return 'var(--status-good)'
}

export function claimTone(status: ClaimStatus): Tone {
  return (CLAIM_STATUS[status] ?? CLAIM_STATUS.PENDING).tone
}

export function LiveDot({ active }: { active: boolean }) {
  if (!active) return null
  return (
    <span className="relative inline-flex h-1.5 w-1.5 shrink-0 text-accent" aria-hidden>
      <span className="live-dot absolute inset-0 rounded-full bg-current" />
      <span className="absolute inset-0 rounded-full bg-current" />
    </span>
  )
}
