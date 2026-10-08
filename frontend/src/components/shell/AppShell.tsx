'use client'

import clsx from 'clsx'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { api } from '@/lib/api'
import { config } from '@/lib/config'
import { useApi, useLocalValue } from '@/lib/hooks'
import {
  Badge,
  DocIcon,
  FlowIcon,
  GaugeIcon,
  GridIcon,
  LinkButton,
  MenuIcon,
  MoonIcon,
  PulseIcon,
  ShieldIcon,
  SparkIcon,
  SunIcon,
  UsersIcon,
} from '@/components/ui/primitives'

interface NavItem {
  href: string
  label: string
  Icon: (props: { className?: string }) => React.ReactNode
  /** Which pathnames should mark this item active. */
  match: (pathname: string) => boolean
  badge?: 'approvals'
}

const NAV: NavItem[] = [
  { href: '/', label: 'Dashboard', Icon: GridIcon, match: (p) => p === '/' },
  {
    href: '/runs',
    label: 'Investigations',
    Icon: FlowIcon,
    match: (p) => p === '/runs' || p.startsWith('/runs/'),
  },
  {
    href: '/customers',
    label: 'Customers',
    Icon: UsersIcon,
    match: (p) => p.startsWith('/customers'),
  },
  { href: '/reports', label: 'Reports', Icon: DocIcon, match: (p) => p.startsWith('/reports') },
  {
    href: '/approvals',
    label: 'Approvals',
    Icon: ShieldIcon,
    match: (p) => p.startsWith('/approvals'),
    badge: 'approvals',
  },
  { href: '/evaluation', label: 'Evaluation', Icon: GaugeIcon, match: (p) => p.startsWith('/evaluation') },
  { href: '/system', label: 'System', Icon: PulseIcon, match: (p) => p.startsWith('/system') },
]

function ThemeToggle() {
  const [theme, setTheme] = useLocalValue('veriflow-theme', 'system')

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
  }, [theme])

  const next = theme === 'dark' ? 'light' : theme === 'light' ? 'system' : 'dark'
  const label = theme === 'system' ? 'Theme: follows your system' : `Theme: ${theme}`

  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      title={label}
      aria-label={`${label}. Activate to switch to ${next}.`}
      className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink"
    >
      {theme === 'light' ? <SunIcon /> : <MoonIcon />}
    </button>
  )
}

function HealthPill() {
  const { data, error } = useApi((signal) => api.health(signal), [], { intervalMs: 30_000 })

  if (error) {
    return (
      <Badge tone="critical" icon={<span className="h-1.5 w-1.5 rounded-full bg-current" />}>
        API unreachable
      </Badge>
    )
  }
  if (!data) {
    return (
      <Badge tone="muted" icon={<span className="h-1.5 w-1.5 rounded-full bg-current" />}>
        Checking…
      </Badge>
    )
  }
  const healthy = data.status === 'ok'
  return (
    <Badge
      tone={healthy ? 'good' : 'warning'}
      icon={<span className="h-1.5 w-1.5 rounded-full bg-current" />}
      title={`Database ${data.database} · Redis ${data.redis} · pgvector ${data.pgvector ? 'ready' : 'missing'}`}
    >
      {healthy ? 'All systems operational' : 'Degraded'}
    </Badge>
  )
}

function ProviderPill() {
  const { data } = useApi((signal) => api.system(signal), [], {})
  if (!data) return null
  const isFake = data.llm_provider === 'fake'
  return (
    <Badge
      tone={isFake ? 'muted' : 'accent'}
      title={
        isFake
          ? 'LLM_PROVIDER=fake — the deterministic offline model. Set OPENAI_API_KEY and LLM_PROVIDER=openai for live inference.'
          : `Live provider: ${data.llm_provider} · ${data.llm_model}`
      }
    >
      {isFake ? 'Deterministic model' : data.llm_model}
    </Badge>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)
  const { data: approvals } = useApi(
    (signal) => api.approvals({ status: 'PENDING', limit: 1 }, signal),
    [],
    { intervalMs: 20_000 },
  )
  const pendingCount = approvals?.total ?? 0

  useEffect(() => setMobileOpen(false), [pathname])

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-40 flex w-[244px] shrink-0 flex-col border-r border-[var(--line)]',
          'bg-[color-mix(in_srgb,var(--plane-2)_88%,transparent)] backdrop-blur-xl',
          'transition-transform duration-200 lg:static lg:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 items-center gap-2.5 px-5">
          <div className="grid h-8 w-8 place-items-center rounded-[10px] bg-accent text-[var(--accent-ink)]">
            <SparkIcon className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <div className="truncate text-[15px] font-semibold tracking-[-0.02em] text-ink">
              {config.productName}
            </div>
            <div className="truncate font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted">
              Evidence-verified AI
            </div>
          </div>
        </div>

        <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto px-2.5 py-2">
          {NAV.map((item) => {
            const active = item.match(pathname)
            const { Icon } = item
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={clsx(
                  'group flex items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-[13px] font-medium transition-colors',
                  active
                    ? 'glass text-ink'
                    : 'text-ink-secondary hover:bg-surface-sunken hover:text-ink',
                )}
              >
                <Icon className={clsx('h-4 w-4 shrink-0', active ? 'text-accent' : 'text-ink-muted')} />
                <span className="relative z-1 flex-1 truncate">{item.label}</span>
                {item.badge === 'approvals' && pendingCount > 0 ? (
                  <span className="relative z-1 rounded-full bg-[color-mix(in_srgb,var(--status-warning)_22%,transparent)] px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-[color-mix(in_srgb,var(--status-warning)_80%,var(--ink))]">
                    {pendingCount}
                  </span>
                ) : null}
              </Link>
            )
          })}
        </nav>

        <div className="space-y-3 border-t border-[var(--line)] px-4 py-4">
          <LinkButton href="/runs/new" variant="primary" size="sm" className="w-full" icon={<SparkIcon className="h-3.5 w-3.5" />}>
            New investigation
          </LinkButton>
          <div className="flex items-center justify-between gap-2">
            <HealthPill />
            <ThemeToggle />
          </div>
        </div>
      </aside>

      {mobileOpen ? (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-30 bg-black/50 backdrop-blur-sm lg:hidden"
        />
      ) : null}

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-[var(--line)] bg-[color-mix(in_srgb,var(--plane)_82%,transparent)] px-4 backdrop-blur-xl sm:px-6">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
            className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted hover:bg-surface-sunken hover:text-ink lg:hidden"
          >
            <MenuIcon />
          </button>
          <Breadcrumb pathname={pathname} />
          <div className="ml-auto flex items-center gap-2">
            <ProviderPill />
          </div>
        </header>

        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-[1400px]">{children}</div>
        </main>

        <footer className="border-t border-[var(--line)] px-4 py-4 text-[11.5px] text-ink-muted sm:px-6 lg:px-8">
          <div className="mx-auto flex w-full max-w-[1400px] flex-wrap items-center justify-between gap-2">
            <span>
              {config.productName} — every conclusion is traced to an evidence record and verified
              independently.
            </span>
            <span className="font-mono">Synthetic dataset · demo environment</span>
          </div>
        </footer>
      </div>
    </div>
  )
}

function Breadcrumb({ pathname }: { pathname: string }) {
  const segments = pathname.split('/').filter(Boolean)
  const label = (() => {
    if (segments.length === 0) return 'Dashboard'
    const match = NAV.find((item) => item.match(pathname))
    return match?.label ?? segments[0]
  })()
  const detail = segments.length > 1 ? segments[segments.length - 1] : null

  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2 text-[13px]">
      <span className="truncate text-ink-muted">{config.productName}</span>
      <span aria-hidden className="text-ink-muted">
        /
      </span>
      <span className="truncate font-medium text-ink">{label}</span>
      {detail ? (
        <>
          <span aria-hidden className="text-ink-muted">
            /
          </span>
          <span className="max-w-[18ch] truncate font-mono text-[11.5px] text-ink-muted sm:max-w-[32ch]">
            {detail}
          </span>
        </>
      ) : null}
    </nav>
  )
}
