'use client'

import clsx from 'clsx'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { MotionConfig } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { AnimatedBackground } from '@/components/core/animated-background'
import { FlowMark } from '@/components/flow/FlowMark'
import { FlowTransition } from '@/components/flow/FlowTransition'
import { DisplayMenu } from '@/components/shell/DisplayMenu'
import { api } from '@/lib/api'
import { config } from '@/lib/config'
import { useApi } from '@/lib/hooks'
import { PreferenceEffects, useMotionPreference } from '@/lib/preferences'
import {
  Badge,
  DocIcon,
  FlowIcon,
  GaugeIcon,
  GridIcon,
  LayersIcon,
  LinkButton,
  MenuIcon,
  PulseIcon,
  ShieldIcon,
  SlidersIcon,
  SparkIcon,
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

const MAIN_NAV: NavItem[] = [
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

/** About the product itself, kept apart from the investigation workflow. */
const MORE_NAV: NavItem[] = [
  { href: '/stack', label: 'Stack', Icon: LayersIcon, match: (p) => p.startsWith('/stack') },
  { href: '/settings', label: 'Settings', Icon: SlidersIcon, match: (p) => p.startsWith('/settings') },
]

const NAV: NavItem[] = [...MAIN_NAV, ...MORE_NAV]

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
  const [motionPreference] = useMotionPreference()
  const columnRef = useRef<HTMLDivElement>(null)
  const headerRef = useRef<HTMLElement>(null)

  return (
    // 'user' follows the OS; the in-app "Reduce motion" forces it off everywhere.
    <MotionConfig reducedMotion={motionPreference === 'reduce' ? 'always' : 'user'}>
    <PreferenceEffects />
    <FlowTransition areaRef={columnRef} headerRef={headerRef} />
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-40 flex w-[244px] shrink-0 flex-col border-r border-[var(--line)]',
          'bg-[color-mix(in_srgb,var(--plane-2)_88%,transparent)] backdrop-blur-xl',
          'transition-transform duration-200 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-16 items-center gap-2.5 px-5">
          <FlowMark className="h-8 w-8 shrink-0 drop-shadow-[0_6px_14px_rgb(37_42_80/0.55)]" />
          <div className="min-w-0">
            <div className="truncate text-[15px] font-semibold tracking-[-0.02em] text-ink">
              {config.productName}
            </div>
            <div className="truncate font-mono text-[9px] uppercase tracking-[0.1em] text-ink-muted">
              Evidence-verified AI
            </div>
          </div>
        </div>

        <nav aria-label="Main" className="flex-1 overflow-y-auto px-2.5 py-2">
          <NavGroup items={MAIN_NAV} pathname={pathname} pendingCount={pendingCount} offset={0} />
          <div className="mt-5 mb-1.5 px-2.5 font-mono text-[9.5px] font-medium tracking-[0.14em] text-ink-muted uppercase">
            This app
          </div>
          <NavGroup items={MORE_NAV} pathname={pathname} pendingCount={pendingCount} offset={MAIN_NAV.length} />
        </nav>

        <div className="space-y-3 border-t border-[var(--line)] px-4 py-4">
          <LinkButton href="/runs/new" variant="primary" size="sm" className="w-full" icon={<SparkIcon className="h-3.5 w-3.5" />}>
            New investigation
          </LinkButton>
          <div className="flex items-center">
            <HealthPill />
          </div>
        </div>
      </aside>

      {mobileOpen ? (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setMobileOpen(false)}
          className="fixed inset-0 z-30 bg-[rgb(11_13_28/0.6)] backdrop-blur-sm lg:hidden"
        />
      ) : null}

      {/* Main */}
      <div ref={columnRef} className="flex min-w-0 flex-1 flex-col">
        <header ref={headerRef} className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-[var(--line)] bg-[color-mix(in_srgb,var(--plane)_82%,transparent)] px-4 backdrop-blur-xl sm:px-6">
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
            <DisplayMenu />
          </div>
        </header>

        <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div key={pathname} className="page-enter mx-auto w-full max-w-[1400px]">
            {children}
          </div>
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
    </MotionConfig>
  )
}

/**
 * One group of nav links. A soft highlight slides between items as the
 * pointer (or keyboard focus) moves — AnimatedBackground in hover mode. The
 * current page keeps its own glass pill and Aqua rail.
 */
function NavGroup({
  items,
  pathname,
  pendingCount,
  offset,
}: {
  items: NavItem[]
  pathname: string
  pendingCount: number
  offset: number
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <AnimatedBackground
        enableHover
        className="rounded-[10px] bg-accent-wash"
        transition={{ type: 'spring', bounce: 0.15, duration: 0.3 }}
      >
        {items.map((item, index) => {
          const active = item.match(pathname)
          const { Icon } = item
          return (
            <Link
              key={item.href}
              data-id={item.href}
              href={item.href}
              aria-current={active ? 'page' : undefined}
              style={{ '--i': index + offset } as React.CSSProperties}
              className={clsx(
                'nav-enter press group flex items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-[13px] font-medium',
                active ? 'glass text-ink' : 'text-ink-secondary hover:text-ink',
              )}
            >
              {active ? <span aria-hidden className="nav-rail" /> : null}
              <Icon
                className={clsx(
                  'h-4 w-4 shrink-0 transition-transform duration-200 group-hover:scale-110',
                  active ? 'text-accent' : 'text-ink-muted group-hover:text-accent',
                )}
              />
              <span className="flex-1 truncate">{item.label}</span>
              {item.badge === 'approvals' && pendingCount > 0 ? (
                <span className="rounded-full bg-[color-mix(in_srgb,var(--status-warning)_22%,transparent)] px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-[color-mix(in_srgb,var(--status-warning)_80%,var(--ink))]">
                  {pendingCount}
                </span>
              ) : null}
            </Link>
          )
        })}
      </AnimatedBackground>
    </div>
  )
}

function Breadcrumb({ pathname }: { pathname: string }) {
  const segments = pathname.split('/').filter(Boolean)
  const match = segments.length === 0 ? NAV[0] : NAV.find((item) => item.match(pathname))
  // Every unrecognised path renders the same text. The 404 page is prerendered
  // statically at build time under `/_not-found`, so echoing the path back
  // would make the server HTML disagree with the URL the browser is actually
  // on — a hydration mismatch (React #418) on every 404.
  const label = match?.label ?? 'Page not found'
  const detail = match && segments.length > 1 ? segments[segments.length - 1] : null

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
