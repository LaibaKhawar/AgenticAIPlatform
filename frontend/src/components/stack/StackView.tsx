'use client'

import clsx from 'clsx'
import { useMemo, useState, type CSSProperties } from 'react'
import { AnimatedBackground } from '@/components/core/animated-background'
import { InfiniteSlider } from '@/components/core/infinite-slider'
import { ErrorState, PauseIcon, PlayIcon } from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { useApi } from '@/lib/hooks'
import { usePrefersReducedMotion } from '@/lib/motion'
import type { StackInfo, SystemInfo } from '@/lib/types'
import { brandPalette } from './brandColors'
import { IntegrationsCard, type IntegrationItem } from './IntegrationsCard'
import { LAYERS, STACK, type StackEntry, type StackLayer } from './catalogue'

/** Per-brand colours solved for contrast in each theme (see brandColors.ts). */
function brandVars(entry: StackEntry): CSSProperties {
  const palette = brandPalette(entry.brand, !entry.Logo)
  return {
    '--brand': entry.brand,
    '--mark-d': palette.markDark,
    '--mark-l': palette.markLight,
    '--tile-d': palette.tileDark,
    '--tile-l': palette.tileLight,
  } as CSSProperties
}

const BRAND_VARS = new Map(STACK.map((entry) => [entry.id, brandVars(entry)]))

function Mark({ entry, size = 20 }: { entry: StackEntry; size?: number }) {
  const { Logo } = entry
  if (Logo) return <Logo size={size} className="brand-ink" />
  return (
    <span className="brand-ink font-mono text-[11px] font-bold tracking-tight">
      {entry.monogram ?? entry.name.slice(0, 2)}
    </span>
  )
}

function resolveVersion(
  entry: StackEntry,
  build: Record<string, string | null>,
  stack: StackInfo | null,
  stackFailed: boolean,
): IntegrationItem['stats'] {
  const source = entry.version
  switch (source.kind) {
    case 'build':
      return [
        { label: 'Version', value: build[source.pkg] ?? 'unknown' },
        { label: 'Read from', value: 'Lockfile at build' },
      ]
    case 'python':
    case 'library':
    case 'service': {
      if (!stack) return [{ label: 'Version', value: stackFailed ? 'unavailable' : '…' }, { label: 'Read from', value: 'Running service' }]
      const version =
        source.kind === 'python'
          ? stack.python
          : source.kind === 'library'
            ? stack.libraries[source.key]
            : stack.services.find((service) => service.name === source.name)?.version
      // A capability carried by another library is labelled with that library.
      const via = source.kind === 'library' ? source.via : undefined
      return [
        { label: 'Version', value: version ? (via ? `${via} ${version}` : version) : 'not installed' },
        { label: 'Read from', value: source.kind === 'service' ? 'The server itself' : 'Installed package' },
      ]
    }
    case 'none':
      return [
        { label: 'Version', value: '—' },
        { label: 'Read from', value: 'Not reported at runtime' },
      ]
  }
}

function resolveAvailability(
  entry: StackEntry,
  stack: StackInfo | null,
  stackFailed: boolean,
  system: SystemInfo | null,
): IntegrationItem['availability'] {
  const source = entry.version
  if (source.kind === 'service') {
    if (!stack) return stackFailed ? { tone: 'unknown', label: 'Unknown' } : { tone: 'unknown', label: 'Checking' }
    const service = stack.services.find((candidate) => candidate.name === source.name)
    return service?.reachable
      ? { tone: 'live', label: 'Connected', title: 'Reachable from the API right now' }
      : { tone: 'down', label: 'Unreachable', title: 'The API could not reach this service' }
  }
  if (source.kind === 'library' || source.kind === 'python') {
    if (!stack) return { tone: 'unknown', label: stackFailed ? 'Unknown' : 'Checking' }
    const version = source.kind === 'python' ? stack.python : stack.libraries[source.key]
    if (!version) return { tone: 'unknown', label: 'Not installed' }
    // Installed is not the same as in use: say which of these is actually active.
    if (entry.id === 'openai' && system)
      return system.llm_provider === 'openai'
        ? { tone: 'live', label: 'In use' }
        : { tone: 'dev', label: 'Standby', title: `Active provider: ${system.llm_provider}` }
    if (entry.id === 'opentelemetry' && system)
      return system.tracing_enabled
        ? { tone: 'live', label: 'Tracing on' }
        : { tone: 'dev', label: 'Tracing off', title: 'Set OTEL_ENABLED to export spans' }
    return { tone: 'live', label: 'Running' }
  }
  if (source.kind === 'build')
    return entry.layer === 'tooling' ? { tone: 'dev', label: 'Dev tool' } : { tone: 'bundled', label: 'Bundled' }
  return { tone: 'dev', label: entry.layer === 'tooling' ? 'Dev tool' : 'Host' }
}

export function StackView({ build }: { build: Record<string, string | null> }) {
  const stackState = useApi((signal) => api.stack(signal), [], { intervalMs: 60_000 })
  const systemState = useApi((signal) => api.system(signal), [], {})
  const [layer, setLayer] = useState<StackLayer | 'all'>('all')
  const [paused, setPaused] = useState(false)
  const reduced = usePrefersReducedMotion()

  const stack = stackState.data
  const stackFailed = Boolean(stackState.error)

  const items: IntegrationItem[] = useMemo(
    () =>
      STACK.filter((entry) => layer === 'all' || entry.layer === layer).map((entry) => ({
        id: entry.id,
        name: entry.name,
        entities: entry.runsIn,
        description: entry.description,
        tags: entry.tags,
        stats: resolveVersion(entry, build, stack, stackFailed),
        availability: resolveAvailability(entry, stack, stackFailed, systemState.data),
        icon: <Mark entry={entry} />,
        accentStyle: BRAND_VARS.get(entry.id) ?? {},
      })),
    [layer, build, stack, stackFailed, systemState.data],
  )

  // Count only versions that actually came back, not entries that could have one.
  const liveCount = stack
    ? STACK.filter((entry) => {
        const source = entry.version
        if (source.kind === 'python') return Boolean(stack.python)
        if (source.kind === 'library') return Boolean(stack.libraries[source.key])
        if (source.kind === 'service') return Boolean(stack.services.find((s) => s.name === source.name)?.version)
        return false
      }).length
    : null
  const counts = useMemo(() => {
    const result: Record<string, number> = { all: STACK.length }
    for (const entry of STACK) result[entry.layer] = (result[entry.layer] ?? 0) + 1
    return result
  }, [])

  return (
    <div className="stagger space-y-7">
      <header>
        <div className="mb-1.5 font-mono text-[10px] font-medium tracking-[0.14em] text-ink-muted uppercase">
          Built with
        </div>
        <h1 className="text-[26px] font-semibold tracking-[-0.025em] text-ink">The stack</h1>
        <p className="mt-1.5 max-w-2xl text-[13px] text-ink-secondary">
          What Veriflow is built from, and what each part does here. Frontend versions are the exact
          ones resolved in the lockfile; backend and server versions are read live from the running
          services{liveCount !== null ? ` (${liveCount} reported right now)` : ''}.
        </p>
      </header>

      {/* Logo marquee */}
      <section aria-label="Technologies" className="panel relative overflow-hidden py-5">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 z-2 w-20 bg-gradient-to-r from-[var(--surface)] to-transparent"
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 right-0 z-2 w-20 bg-gradient-to-l from-[var(--surface)] to-transparent"
        />
        <InfiniteSlider gap={36} speed={38} speedOnHover={12} paused={paused}>
          {STACK.map((entry) => (
            <div
              key={entry.id}
              style={BRAND_VARS.get(entry.id)}
              className="flex shrink-0 items-center gap-2.5 opacity-80 transition-opacity hover:opacity-100"
            >
              <Mark entry={entry} size={22} />
              <span className="text-[13.5px] font-medium whitespace-nowrap text-ink-secondary">{entry.name}</span>
            </div>
          ))}
        </InfiniteSlider>
        {reduced ? null : (
          <button
            type="button"
            onClick={() => setPaused((value) => !value)}
            aria-pressed={paused}
            aria-label={paused ? 'Resume the scrolling logos' : 'Pause the scrolling logos'}
            className="press absolute top-1/2 right-3 z-3 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-lg bg-surface-raised text-ink-muted ring-1 ring-inset ring-[var(--line)] hover:text-ink"
          >
            {paused ? <PlayIcon className="h-3.5 w-3.5" /> : <PauseIcon className="h-3.5 w-3.5" />}
          </button>
        )}
      </section>

      {stackState.error ? (
        <ErrorState
          error={{
            code: stackState.error.code,
            message: 'Could not read live versions from the API. Backend versions show as unavailable until it responds.',
          }}
          onRetry={stackState.refresh}
        />
      ) : null}

      <IntegrationsCard
        title="Technologies"
        description="Each card says where the technology runs in Veriflow and where its version number came from."
        items={items}
        actions={
          <nav aria-label="Filter by layer" className="flex flex-wrap gap-1 rounded-xl bg-surface-sunken p-1 ring-1 ring-inset ring-[var(--line)]">
            <AnimatedBackground
              defaultValue={layer}
              className="rounded-lg bg-surface-raised shadow-[0_2px_10px_-4px_rgb(4_6_20/0.5)] ring-1 ring-inset ring-[var(--line-strong)]"
              transition={{ type: 'spring', bounce: 0.2, duration: 0.35 }}
            >
              {LAYERS.map((option) => (
                <button
                  key={option.id}
                  data-id={option.id}
                  type="button"
                  aria-pressed={layer === option.id}
                  onClick={() => setLayer(option.id)}
                  className={clsx(
                    'press rounded-lg px-2.5 py-1 text-[12px] font-medium transition-colors',
                    layer === option.id ? 'text-ink' : 'text-ink-muted hover:text-ink',
                  )}
                >
                  {option.label}
                  <span className="num ml-1.5 text-[10.5px] text-ink-muted">{counts[option.id] ?? 0}</span>
                </button>
              ))}
            </AnimatedBackground>
          </nav>
        }
      />
    </div>
  )
}
