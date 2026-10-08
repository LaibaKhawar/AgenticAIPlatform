'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import {
  Cell,
  EmptyState,
  ErrorState,
  Pagination,
  Panel,
  Row,
  SearchIcon,
  Skeleton,
  Table,
  UsersIcon,
} from '@/components/ui/primitives'
import { api } from '@/lib/api'
import { useApi } from '@/lib/hooks'
import { daysLabel, formatCurrency, formatDate, formatNumber } from '@/lib/format'
import type { AccountTier } from '@/lib/types'

const PAGE_SIZE = 25

const TIERS: Array<{ value: AccountTier | ''; label: string }> = [
  { value: '', label: 'All tiers' },
  { value: 'ENTERPRISE', label: 'Enterprise' },
  { value: 'MID_MARKET', label: 'Mid-market' },
  { value: 'SMB', label: 'SMB' },
  { value: 'STARTUP', label: 'Startup' },
]

const WINDOWS: Array<{ value: number | ''; label: string }> = [
  { value: '', label: 'Any renewal date' },
  { value: 30, label: 'Renewing in 30 days' },
  { value: 90, label: 'Renewing in 90 days' },
  { value: 180, label: 'Renewing in 180 days' },
]

export default function CustomersPage() {
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [tier, setTier] = useState<AccountTier | ''>('')
  const [window, setWindow] = useState<number | ''>('')
  const [offset, setOffset] = useState(0)

  // Debounce so typing does not issue a query per keystroke.
  useEffect(() => {
    const handle = setTimeout(() => {
      setDebounced(search.trim())
      setOffset(0)
    }, 300)
    return () => clearTimeout(handle)
  }, [search])

  const { data, error, initialLoading, refresh } = useApi(
    (signal) =>
      api.customers(
        {
          search: debounced || undefined,
          account_tier: tier || undefined,
          renewal_within_days: window || undefined,
          limit: PAGE_SIZE,
          offset,
        },
        signal,
      ),
    [debounced, tier, window, offset],
  )

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-ink-muted">
          Portfolio
        </div>
        <h1 className="text-[26px] font-semibold tracking-[-0.025em] text-ink">Customers</h1>
        <p className="mt-1.5 max-w-2xl text-[13px] text-ink-secondary">
          The structured side of the warehouse: subscriptions, usage, support, billing and sentiment.
          Open an account to see its deterministic risk breakdown.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by company name or account id"
            aria-label="Search customers"
            className="h-9.5 w-full rounded-lg border border-[var(--line-strong)] bg-surface-sunken pl-9 pr-3 text-[13px] text-ink placeholder:text-ink-muted focus:border-accent focus:outline-none"
          />
        </div>
        <select
          value={tier}
          onChange={(event) => {
            setTier(event.target.value as AccountTier | '')
            setOffset(0)
          }}
          aria-label="Filter by account tier"
          className="h-9.5 rounded-lg border border-[var(--line-strong)] bg-surface-sunken px-3 text-[13px] text-ink focus:border-accent focus:outline-none"
        >
          {TIERS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          value={window}
          onChange={(event) => {
            setWindow(event.target.value === '' ? '' : Number(event.target.value))
            setOffset(0)
          }}
          aria-label="Filter by renewal window"
          className="h-9.5 rounded-lg border border-[var(--line-strong)] bg-surface-sunken px-3 text-[13px] text-ink focus:border-accent focus:outline-none"
        >
          {WINDOWS.map((option) => (
            <option key={String(option.value)} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {error ? <ErrorState error={error} onRetry={refresh} /> : null}

      <Panel>
        {initialLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 8 }).map((_, index) => (
              <Skeleton key={index} className="h-10" />
            ))}
          </div>
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            icon={<UsersIcon />}
            title={debounced || tier || window ? 'No matching customers' : 'No customers loaded'}
            description={
              debounced || tier || window
                ? 'Try a broader filter or clear the search.'
                : 'Run make seed to generate the synthetic dataset — 3,000 accounts with correlated churn scenarios and supporting documents.'
            }
          />
        ) : (
          <>
            <Table head={['Account', 'Tier', 'Industry', 'Plan', 'MRR', 'ACV', 'Seats', 'Renewal', 'Outcome']}>
              {data.items.map((customer) => (
                <Row key={customer.id}>
                  <Cell>
                    <Link
                      href={`/customers/${customer.external_id}`}
                      className="font-medium text-ink hover:text-accent"
                    >
                      {customer.company_name}
                    </Link>
                    <span className="ml-2 font-mono text-[10.5px] text-ink-muted">
                      {customer.external_id}
                    </span>
                  </Cell>
                  <Cell className="whitespace-nowrap">{customer.account_tier.replace('_', ' ')}</Cell>
                  <Cell className="whitespace-nowrap">{customer.industry}</Cell>
                  <Cell className="whitespace-nowrap">{customer.subscription?.plan ?? '—'}</Cell>
                  <Cell numeric>{formatCurrency(customer.subscription?.monthly_recurring_revenue)}</Cell>
                  <Cell numeric>{formatCurrency(customer.subscription?.annual_contract_value)}</Cell>
                  <Cell numeric>{formatNumber(customer.subscription?.seats_purchased)}</Cell>
                  <Cell className="whitespace-nowrap">
                    {customer.subscription ? (
                      <>
                        {formatDate(customer.subscription.renewal_date)}
                        <span className="ml-1.5 font-mono text-[10.5px] text-ink-muted">
                          {daysLabel(customer.subscription.days_to_renewal)}
                        </span>
                      </>
                    ) : (
                      '—'
                    )}
                  </Cell>
                  <Cell className="whitespace-nowrap">
                    {customer.outcome && customer.outcome !== 'UNKNOWN' ? (
                      <span className="font-mono text-[11px] text-ink-muted">{customer.outcome}</span>
                    ) : (
                      <span className="font-mono text-[11px] text-accent">live</span>
                    )}
                  </Cell>
                </Row>
              ))}
            </Table>
            <Pagination
              total={data.total}
              limit={data.limit}
              offset={data.offset}
              onChange={setOffset}
              label="customers"
            />
          </>
        )}
      </Panel>
    </div>
  )
}
