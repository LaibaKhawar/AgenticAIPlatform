'use client'

import {
  AlertIcon,
  Badge,
  Cell,
  CheckIcon,
  CrossIcon,
  ErrorState,
  KeyValue,
  Panel,
  Row,
  SectionHeader,
  ShieldIcon,
  Skeleton,
  StatTile,
  Table,
} from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { useApi } from '@/lib/hooks'

export default function SystemPage() {
  const system = useApi((signal) => api.system(signal), [])
  const health = useApi((signal) => api.health(signal), [], { intervalMs: 15_000 })

  if (system.error) {
    return (
      <div className="space-y-4">
        <h1 className="text-[26px] font-semibold text-ink">System</h1>
        <ErrorState error={system.error} onRetry={system.refresh} />
      </div>
    )
  }

  if (system.initialLoading || !system.data) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-32 rounded-card" />
        <Skeleton className="h-64 rounded-card" />
      </div>
    )
  }

  const info = system.data
  const checks = health.data

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
          Observability
        </div>
        <h1 className="text-[26px] font-semibold tracking-[-0.025em] text-ink">System</h1>
        <p className="mt-1.5 max-w-3xl text-[13px] text-ink-secondary">
          What this deployment can actually do. Agents, tools, limits and policy are read from the running
          registry — this page cannot show a capability the platform does not have.
        </p>
      </div>

      {/* Dependency health */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="PostgreSQL"
          value={<span className="text-[18px]">{checks?.database ?? '…'}</span>}
          tone={checks?.database === 'ok' ? 'good' : checks ? 'critical' : 'neutral'}
          icon={checks?.database === 'ok' ? <CheckIcon className="h-3.5 w-3.5" /> : <CrossIcon className="h-3.5 w-3.5" />}
        />
        <StatTile
          label="pgvector"
          value={<span className="text-[18px]">{checks ? (checks.pgvector ? 'ready' : 'missing') : '…'}</span>}
          tone={checks?.pgvector ? 'good' : checks ? 'critical' : 'neutral'}
          icon={checks?.pgvector ? <CheckIcon className="h-3.5 w-3.5" /> : <CrossIcon className="h-3.5 w-3.5" />}
        />
        <StatTile
          label="Redis"
          value={<span className="text-[18px]">{checks?.redis === 'ok' ? 'ok' : (checks?.redis ?? '…')}</span>}
          tone={checks?.redis === 'ok' ? 'good' : checks ? 'warning' : 'neutral'}
          hint="Celery broker and result backend"
        />
        <StatTile
          label="Executor"
          value={<span className="text-[18px]">{info.workflow_executor}</span>}
          hint={
            info.workflow_executor === 'celery'
              ? 'distributed workers'
              : 'in-process (tests / no broker)'
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Configuration */}
        <Panel className="p-4">
          <SectionHeader eyebrow="Configuration" title="Runtime" />
          <dl className="mt-2">
            <KeyValue label="Environment" value={info.environment} mono />
            <KeyValue label="LLM provider" value={info.llm_provider} mono />
            <KeyValue label="LLM model" value={info.llm_model} mono />
            <KeyValue label="Embedding provider" value={info.embedding_provider} mono />
            <KeyValue label="Embedding model" value={info.embedding_model} mono />
            <KeyValue
              label="OpenTelemetry"
              value={info.tracing_enabled ? 'enabled' : 'disabled'}
              mono
            />
            <KeyValue
              label="Langfuse"
              value={info.langfuse_configured ? 'configured' : 'not configured'}
              mono
            />
          </dl>
          {info.llm_provider === 'fake' ? (
            <p className="mt-3 flex items-start gap-2 rounded-md bg-surface-sunken px-3 py-2 text-[11.5px] leading-snug text-ink-secondary">
              <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[color-mix(in_srgb,var(--status-warning)_85%,var(--ink))]" />
              <span>
                Running on the deterministic offline model, so no API key is required and results are
                reproducible. Set <code className="font-mono">OPENAI_API_KEY</code> and{' '}
                <code className="font-mono">LLM_PROVIDER=openai</code> for live inference.
              </span>
            </p>
          ) : null}
        </Panel>

        {/* Safety limits */}
        <Panel className="p-4">
          <SectionHeader
            eyebrow="Agent safety"
            title="Hard limits"
            description="Bounds that prevent runaway loops and unbounded cost."
          />
          <dl className="mt-2">
            {Object.entries(info.limits).map(([key, value]) => (
              <KeyValue key={key} label={key.replace(/_/g, ' ')} value={String(value)} mono />
            ))}
          </dl>
        </Panel>
      </div>

      {/* Failure injection */}
      <Panel className="p-4">
        <SectionHeader
          eyebrow="Resilience"
          title="Failure injection"
          description={info.failure_injection.note}
        />
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Badge
            tone={info.failure_injection.active ? 'warning' : 'muted'}
            icon={info.failure_injection.active ? <AlertIcon className="h-3 w-3" /> : <CheckIcon className="h-3 w-3" />}
          >
            {info.failure_injection.active ? 'Active' : 'Inactive'}
          </Badge>
          <span className="font-mono text-[11px] text-ink-muted">
            llm {info.failure_injection.llm_failure_rate} · vector{' '}
            {info.failure_injection.vector_failure_rate} · api {info.failure_injection.api_failure_rate}
          </span>
        </div>
      </Panel>

      {/* Agents */}
      <Panel>
        <div className="border-b border-[var(--line)] px-4 py-3">
          <SectionHeader
            eyebrow="Architecture"
            title="Agents"
            description="Each agent is a declared capability: an explicit tool allow-list, a typed output schema, a timeout and a retry budget. Nothing is acquired at runtime."
          />
        </div>
        <Table head={['Agent', 'Role', 'Model', 'Output schema', 'Tools', 'Timeout', 'Retries']}>
          {info.agents.map((agent) => (
            <Row key={agent.name}>
              <Cell className="font-medium text-ink">{agent.name}</Cell>
              <Cell className="max-w-[26rem] text-[12px] leading-snug">{agent.role}</Cell>
              <Cell>
                {agent.uses_llm ? (
                  <Badge tone="accent">{agent.provider === 'fake' ? 'deterministic' : agent.model}</Badge>
                ) : (
                  <Badge tone="muted" icon={<ShieldIcon className="h-3 w-3" />}>
                    no model
                  </Badge>
                )}
              </Cell>
              <Cell mono className="text-[11px]">
                {agent.output_schema ?? '—'}
              </Cell>
              <Cell mono className="max-w-[18rem] text-[11px] leading-snug">
                {agent.allowed_tools.length === 0 ? 'none' : agent.allowed_tools.join(', ')}
              </Cell>
              <Cell numeric>{agent.timeout_seconds}s</Cell>
              <Cell numeric>{agent.max_retries}</Cell>
            </Row>
          ))}
        </Table>
      </Panel>

      {/* Tools */}
      <Panel>
        <div className="border-b border-[var(--line)] px-4 py-3">
          <SectionHeader
            eyebrow="Boundary"
            title="Tool registry"
            description="Agents reach the database only through these validated methods. There is no SQL, shell, filesystem or arbitrary-HTTP tool."
          />
        </div>
        <Table head={['Tool', 'Description', 'Access', 'Approval', 'Timeout', 'Attempts']}>
          {info.tools.map((tool) => (
            <Row key={tool.name}>
              <Cell mono className="text-ink">
                {tool.name}
              </Cell>
              <Cell className="max-w-[30rem] text-[12px] leading-snug">{tool.description}</Cell>
              <Cell>
                <Badge tone={tool.read_only ? 'good' : 'warning'}>
                  {tool.read_only ? 'read-only' : 'sensitive write'}
                </Badge>
              </Cell>
              <Cell>
                {tool.requires_approval ? (
                  <Badge tone="warning" icon={<ShieldIcon className="h-3 w-3" />}>
                    gated
                  </Badge>
                ) : (
                  <span className="text-ink-muted">—</span>
                )}
              </Cell>
              <Cell numeric>{tool.timeout_seconds}s</Cell>
              <Cell numeric>{tool.max_attempts}</Cell>
            </Row>
          ))}
        </Table>
      </Panel>

      {/* Risk model */}
      <Panel className="p-4">
        <SectionHeader
          eyebrow="Determinism"
          title="Risk model"
          description={info.risk_model.description}
        />
        <div className="mt-3 grid gap-4 lg:grid-cols-2">
          <div>
            <h3 className="text-[12.5px] font-semibold text-ink">Component weights</h3>
            <dl className="mt-1.5">
              {Object.entries(info.risk_model.weights).map(([key, weight]) => (
                <KeyValue
                  key={key}
                  label={key.replace(/_/g, ' ')}
                  value={`${(weight * 100).toFixed(0)}%`}
                  mono
                />
              ))}
            </dl>
          </div>
          <div>
            <h3 className="text-[12.5px] font-semibold text-ink">Aggregation and thresholds</h3>
            <dl className="mt-1.5">
              <KeyValue
                label="weighted average share"
                value={String(info.risk_model.aggregation.weighted_average_share)}
                mono
              />
              <KeyValue
                label="dominant signal share"
                value={String(info.risk_model.aggregation.dominant_signal_share)}
                mono
              />
              <KeyValue
                label="agent adjustment band"
                value={`±${info.risk_model.agent_adjustment_band_points} pts`}
                mono
              />
              {Object.entries(info.risk_model.levels).map(([level, rule]) => (
                <KeyValue key={level} label={level} value={rule} mono />
              ))}
            </dl>
            <p className="mt-2 text-[11.5px] leading-snug text-ink-muted">
              {info.risk_model.aggregation.note}
            </p>
          </div>
        </div>
      </Panel>

      {/* Approval policy */}
      <Panel>
        <div className="border-b border-[var(--line)] px-4 py-3">
          <SectionHeader
            eyebrow="Human in the loop"
            title="Approval policy"
            description="Deterministic application logic. A model picks an action type; it never decides whether review can be skipped."
          />
        </div>
        <Table head={['Action type', 'Requires approval', 'Reason']}>
          {info.approval_policy.map((entry) => (
            <Row key={entry.action_type}>
              <Cell mono className="text-ink">
                {entry.action_type}
              </Cell>
              <Cell>
                {entry.requires_approval ? (
                  <Badge tone="warning" icon={<ShieldIcon className="h-3 w-3" />}>
                    Yes
                  </Badge>
                ) : (
                  <Badge tone="good" icon={<CheckIcon className="h-3 w-3" />}>
                    No
                  </Badge>
                )}
              </Cell>
              <Cell className="max-w-[34rem] text-[12px] leading-snug">{entry.reason}</Cell>
            </Row>
          ))}
        </Table>
      </Panel>
    </div>
  )
}
