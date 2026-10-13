'use client'

import clsx from 'clsx'
import Link from 'next/link'
import { useEffect, useId, useState, useSyncExternalStore, type ComponentType, type ReactNode } from 'react'
import { TextShimmer } from '@/components/core/text-shimmer'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  ArrowRightIcon,
  Badge,
  LayersIcon,
  LinkIcon,
  MonitorIcon,
  PulseIcon,
  Skeleton,
  SunIcon,
  WaveIcon,
} from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { config } from '@/lib/config'
import { formatRelative } from '@/lib/format'
import { useApi } from '@/lib/hooks'
import { useSystemPrefersReducedMotion } from '@/lib/motion'
import {
  useMotionPreference,
  useScenePreference,
  useThemePreference,
  type MotionPreference,
  type ScenePreference,
  type ThemePreference,
} from '@/lib/preferences'

type SettingsTab = 'appearance' | 'motion' | 'connection'

const TABS: Array<{ value: SettingsTab; name: string; Icon: ComponentType<{ className?: string }> }> = [
  { value: 'appearance', name: 'Appearance', Icon: SunIcon },
  { value: 'motion', name: 'Motion', Icon: WaveIcon },
  { value: 'connection', name: 'Connection', Icon: LinkIcon },
]

const DARK_QUERY = '(prefers-color-scheme: dark)'

function useSystemPrefersDark(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const query = window.matchMedia(DARK_QUERY)
      query.addEventListener('change', onChange)
      return () => query.removeEventListener('change', onChange)
    },
    () => window.matchMedia(DARK_QUERY).matches,
    () => true,
  )
}

/* -------------------------------------------------------------------------- */
/* Option cards: a native radio group, styled as cards                        */
/* -------------------------------------------------------------------------- */

interface Option<T extends string> {
  value: T
  label: string
  description: string
  preview?: ReactNode
}

function OptionCards<T extends string>({
  legend,
  options,
  value,
  onChange,
}: {
  legend: string
  options: Array<Option<T>>
  value: T
  onChange: (value: T) => void
}) {
  const name = useId()
  return (
    <fieldset>
      <legend className="mb-2.5 text-[13px] font-semibold text-ink">{legend}</legend>
      <div className={clsx('grid gap-2.5', options.length === 3 ? 'sm:grid-cols-3' : 'sm:grid-cols-2')}>
        {options.map((option) => {
          const checked = value === option.value
          return (
            <label
              key={option.value}
              className={clsx(
                'press lift relative flex cursor-pointer flex-col rounded-card p-3 ring-1 ring-inset',
                'has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-[var(--accent)]',
                checked
                  ? 'bg-accent-wash ring-[var(--accent-ring)]'
                  : 'bg-surface-raised ring-[var(--line)] hover:ring-[var(--line-strong)]',
              )}
            >
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={checked}
                onChange={() => onChange(option.value)}
                className="sr-only"
              />
              {option.preview ? <div className="mb-3">{option.preview}</div> : null}
              <span className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-medium text-ink">{option.label}</span>
                <span
                  aria-hidden
                  className={clsx(
                    'grid h-4 w-4 place-items-center rounded-full ring-1 ring-inset transition-colors',
                    checked ? 'bg-accent ring-[var(--accent)]' : 'ring-[var(--line-strong)]',
                  )}
                >
                  {checked ? <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent-ink)]" /> : null}
                </span>
              </span>
              <span className="mt-1 text-[12px] leading-snug text-ink-muted">{option.description}</span>
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

/** A miniature of the app in a given palette — static swatches, not a screenshot. */
function ThemePreview({ variant }: { variant: 'dark' | 'light' | 'split' }) {
  const panel = (tone: 'dark' | 'light') => {
    const c =
      tone === 'dark'
        ? { plane: '#0b0d1c', surface: '#1c2142', line: '#343a68', ink: '#f2f3fa', muted: '#9196bb', accent: '#85ced1' }
        : { plane: '#f4f5fb', surface: '#ffffff', line: '#dfe2f0', ink: '#151833', muted: '#5f6488', accent: '#252a50' }
    return (
      <div className="flex h-full flex-1 gap-1.5 p-1.5" style={{ background: c.plane }}>
        <div className="w-3 rounded-[3px]" style={{ background: c.surface, boxShadow: `inset 0 0 0 1px ${c.line}` }} />
        <div className="flex flex-1 flex-col gap-1">
          <div className="h-3 rounded-[3px] bg-[linear-gradient(100deg,#2b3160,#252a50)]" />
          <div className="flex gap-1">
            <div className="h-2 flex-1 rounded-[2px]" style={{ background: c.surface, boxShadow: `inset 0 0 0 1px ${c.line}` }} />
            <div className="h-2 flex-1 rounded-[2px]" style={{ background: c.surface, boxShadow: `inset 0 0 0 1px ${c.line}` }} />
          </div>
          <div className="h-1 w-2/3 rounded-full" style={{ background: c.muted }} />
          <div className="mt-auto h-1.5 w-1/2 rounded-full" style={{ background: c.accent }} />
        </div>
      </div>
    )
  }
  return (
    <div aria-hidden className="flex h-16 overflow-hidden rounded-lg ring-1 ring-inset ring-[var(--line)]">
      {variant === 'split' ? (
        <>
          {panel('dark')}
          {panel('light')}
        </>
      ) : (
        panel(variant)
      )}
    </div>
  )
}

function StatusLine({ children }: { children: ReactNode }) {
  return (
    <p className="mt-3 flex items-center gap-2 rounded-lg bg-surface-sunken px-3 py-2 text-[12px] text-ink-secondary ring-1 ring-inset ring-[var(--line)]">
      <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
      {children}
    </p>
  )
}

/* -------------------------------------------------------------------------- */
/* Tabs                                                                       */
/* -------------------------------------------------------------------------- */

function AppearanceTab() {
  const [theme, setTheme] = useThemePreference()
  const systemDark = useSystemPrefersDark()
  const resolved = theme === 'system' ? (systemDark ? 'dark' : 'light') : theme

  return (
    <div className="space-y-4">
      <OptionCards<ThemePreference>
        legend="Theme"
        value={theme}
        onChange={setTheme}
        options={[
          {
            value: 'system',
            label: 'Match system',
            description: 'Follows your operating system, and switches when it does.',
            preview: <ThemePreview variant="split" />,
          },
          {
            value: 'dark',
            label: 'Dark',
            description: 'Beacon Blue planes. Aqua Splash and Georgia Peach at full Pantone strength.',
            preview: <ThemePreview variant="dark" />,
          },
          {
            value: 'light',
            label: 'Light',
            description: 'Beacon Blue ink on white, with deepened aqua and peach for legibility.',
            preview: <ThemePreview variant="light" />,
          },
        ]}
      />
      <StatusLine>
        Showing <strong className="font-medium text-ink">{resolved}</strong>
        {theme === 'system' ? ' — from your system setting.' : ' — chosen here.'} Saved in this browser only.
      </StatusLine>
    </div>
  )
}

function MotionTab() {
  const [motion, setMotion] = useMotionPreference()
  const [scene, setScene] = useScenePreference()
  const systemReduced = useSystemPrefersReducedMotion()
  const reduced = systemReduced || motion === 'reduce'

  return (
    <div className="space-y-6">
      <div>
        <OptionCards<MotionPreference>
          legend="Animations"
          value={motion}
          onChange={setMotion}
          options={[
            {
              value: 'system',
              label: 'Follow system',
              description: 'Page transitions, counters and hover effects play unless your system asks for less motion.',
            },
            {
              value: 'reduce',
              label: 'Reduce motion',
              description: 'Turns off every animation in the app, even if your system allows motion.',
            },
          ]}
        />
        <StatusLine>
          {systemReduced
            ? 'Your system asks for reduced motion, so animations are off whatever you choose here.'
            : reduced
              ? 'Animations are off because you chose Reduce motion.'
              : 'Animations are on. Your system is not asking for reduced motion.'}
        </StatusLine>
      </div>

      <div>
        <OptionCards<ScenePreference>
          legend="Flow"
          value={scene}
          onChange={setScene}
          options={[
            {
              value: 'on',
              label: 'Flow on',
              description: reduced
                ? 'The flow on the dashboard rests as a single still frame while motion is reduced, and pages change instantly.'
                : 'Information flows through the dashboard card, and carries you between sections when you navigate.',
            },
            {
              value: 'off',
              label: 'Flow off',
              description: 'The flow rests as a still frame and pages change instantly. Useful on battery or when you just want speed.',
            },
          ]}
        />
      </div>

      <div className="rounded-card bg-surface-raised p-3 ring-1 ring-inset ring-[var(--line)]">
        <p className="text-[12px] text-ink-muted">Preview — status text for work in flight:</p>
        <TextShimmer as="p" className="mt-1 font-mono text-[13px]" duration={1.6}>
          Investigating 5 accounts…
        </TextShimmer>
      </div>
    </div>
  )
}

function CheckRow({ label, ok, detail }: { label: string; ok: boolean | null; detail?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-[var(--line)] py-2 last:border-0">
      <span className="text-[12.5px] text-ink-secondary">{label}</span>
      {ok === null ? (
        <Skeleton className="h-4 w-16" />
      ) : (
        <Badge tone={ok ? 'good' : 'critical'} icon={<span className="h-1.5 w-1.5 rounded-full bg-current" />} title={detail}>
          {ok ? 'Connected' : 'Unreachable'}
        </Badge>
      )}
    </div>
  )
}

function FactRow({ label, value, mono = false }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-[var(--line)] py-2 last:border-0">
      <dt className="shrink-0 text-[12.5px] text-ink-muted">{label}</dt>
      <dd className={clsx('min-w-0 truncate text-right text-[12.5px] text-ink', mono && 'font-mono text-[12px]')}>{value}</dd>
    </div>
  )
}

function ConnectionTab() {
  const health = useApi((signal) => api.health(signal), [], { intervalMs: 15_000 })
  const system = useApi((signal) => api.system(signal), [], {})
  const [checkedAt, setCheckedAt] = useState<string | null>(null)
  useEffect(() => {
    if (health.data || health.error) setCheckedAt(new Date().toISOString())
  }, [health.data, health.error])

  const h = health.data
  const unreachable = Boolean(health.error)

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <section className="rounded-card bg-surface-raised p-4 ring-1 ring-inset ring-[var(--line)]">
        <h3 className="text-[13px] font-semibold text-ink">Dependencies</h3>
        <p className="mt-0.5 text-[12px] text-ink-muted">
          Checked by the API every 15 seconds{checkedAt ? ` · last ${formatRelative(checkedAt)}` : ''}.
        </p>
        <div className="mt-2">
          {unreachable ? (
            <CheckRow label="API" ok={false} detail={health.error?.message} />
          ) : (
            <>
              <CheckRow label="API" ok={h ? true : null} />
              <CheckRow label="PostgreSQL" ok={h ? h.database === 'ok' : null} detail={h?.database} />
              <CheckRow label="pgvector" ok={h ? h.pgvector : null} />
              <CheckRow label="Redis" ok={h ? h.redis === 'ok' : null} detail={h?.redis} />
            </>
          )}
        </div>
      </section>

      <section className="rounded-card bg-surface-raised p-4 ring-1 ring-inset ring-[var(--line)]">
        <h3 className="text-[13px] font-semibold text-ink">This deployment</h3>
        <dl className="mt-2">
          <FactRow label="API endpoint" value={config.apiBaseUrl} mono />
          <FactRow
            label="Authentication"
            value={config.apiKey ? 'API key sent with every request' : 'Open — no API key configured'}
          />
          <FactRow label="Environment" value={h?.environment ?? '…'} />
          <FactRow label="Version" value={h?.version ?? '…'} mono />
          <FactRow label="Workflow executor" value={system.data?.workflow_executor ?? '…'} />
          <FactRow
            label="Language model"
            value={
              system.data
                ? system.data.llm_provider === 'fake'
                  ? 'Deterministic offline model'
                  : `${system.data.llm_provider} · ${system.data.llm_model}`
                : '…'
            }
          />
          <FactRow label="Embeddings" value={system.data?.embedding_provider ?? '…'} />
        </dl>
      </section>

      <div className="flex flex-wrap gap-2 lg:col-span-2">
        <Link
          href="/system"
          className="press inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] font-medium text-accent hover:bg-accent-wash"
        >
          <PulseIcon className="h-3.5 w-3.5" /> Agents, tools and policies
          <ArrowRightIcon className="h-3.5 w-3.5" />
        </Link>
        <Link
          href="/stack"
          className="press inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] font-medium text-accent hover:bg-accent-wash"
        >
          <LayersIcon className="h-3.5 w-3.5" /> Versions of everything running
          <ArrowRightIcon className="h-3.5 w-3.5" />
        </Link>
      </div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */

const TAB_COPY: Record<SettingsTab, ReactNode> = {
  appearance: (
    <>
      Choose how {config.productName} <span className="font-semibold text-ink">looks</span> in this browser. The
      choice applies immediately and is stored only on this device.
    </>
  ),
  motion: (
    <>
      Control <span className="font-semibold text-ink">animation and the flow</span>. A request from your system
      to reduce motion always wins.
    </>
  ),
  connection: (
    <>
      The <span className="font-semibold text-ink">live state</span> of the API and the services behind it, read
      from the running deployment.
    </>
  ),
}

function isTab(value: string): value is SettingsTab {
  return TABS.some((tab) => tab.value === value)
}

export function SettingsView() {
  const [tab, setTab] = useState<SettingsTab>('appearance')

  // Deep links (`/settings#motion`) select a tab — on arrival, and when the
  // hash changes while already here (the Display menu's "All settings").
  useEffect(() => {
    const sync = () => {
      const fromHash = window.location.hash.slice(1)
      if (isTab(fromHash)) setTab(fromHash)
    }
    sync()
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])

  const select = (next: string) => {
    if (!isTab(next)) return
    setTab(next)
    window.history.replaceState(null, '', `#${next}`)
  }

  return (
    <div className="stagger space-y-6">
      <header>
        <div className="mb-1.5 font-mono text-[10px] font-medium tracking-[0.14em] text-ink-muted uppercase">
          Preferences
        </div>
        <h1 className="text-[26px] font-semibold tracking-[-0.025em] text-ink">Settings</h1>
        <p className="mt-1.5 max-w-2xl text-[13px] text-ink-secondary">
          Display preferences for this browser, and a live view of the deployment you are connected to.
        </p>
      </header>

      <Tabs defaultValue="appearance" value={tab} onValueChange={select} className="space-y-5">
        <TabsList
          label="Settings sections"
          className="inline-flex gap-1.5 rounded-2xl bg-surface-sunken p-1.5 ring-1 ring-inset ring-[var(--line)]"
        >
          {TABS.map(({ value, name, Icon }) => (
            <TabsTrigger
              key={value}
              value={value}
              indicatorClassName="rounded-xl bg-surface-raised shadow-[0_8px_22px_-10px_rgb(4_6_20/0.55)] ring-1 ring-inset ring-[var(--line-strong)]"
              className="press flex h-14 w-[5.75rem] flex-col items-center justify-center gap-1.5 rounded-xl px-2 text-[10px] font-bold tracking-wider text-ink-muted uppercase transition-colors hover:text-ink data-[state=active]:text-accent"
            >
              <Icon className="h-5 w-5" />
              <span>{name}</span>
            </TabsTrigger>
          ))}
        </TabsList>

        {TABS.map(({ value, name }) => (
          <TabsContent key={value} value={value} className="panel page-enter p-5 outline-none sm:p-6">
            <h2 className="text-lg font-bold tracking-tight text-ink">{name}</h2>
            <p className="mt-1 mb-5 max-w-2xl text-[13px] leading-relaxed text-ink-secondary">{TAB_COPY[value]}</p>
            {value === 'appearance' ? <AppearanceTab /> : null}
            {value === 'motion' ? <MotionTab /> : null}
            {value === 'connection' ? <ConnectionTab /> : null}
          </TabsContent>
        ))}
      </Tabs>

      <p className="flex items-center gap-2 text-[12px] text-ink-muted">
        <MonitorIcon className="h-3.5 w-3.5" /> Theme, motion and the flow are also in the Display menu at the top of
        every page.
      </p>
    </div>
  )
}
