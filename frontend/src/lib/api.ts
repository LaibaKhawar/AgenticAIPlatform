/**
 * Typed API client.
 *
 * One place that knows how to talk to the backend, so error handling is
 * uniform: every failure becomes an `ApiError` carrying the backend's
 * structured `{error: {code, message, details}}` body, which the UI renders
 * verbatim instead of showing "something went wrong".
 */

import { config } from './config'
import type {
  Approval,
  ApprovalStatus,
  ClaimItem,
  ClaimStatus,
  CreateRunRequest,
  CreateRunResponse,
  CustomerDetail,
  CustomerListItem,
  CustomerRisk,
  Dashboard,
  DocumentDetail,
  DocumentListItem,
  EvaluationRun,
  EvidenceItem,
  HealthStatus,
  Investigation,
  Page,
  Report,
  ReportListItem,
  RunDetail,
  RunListItem,
  RunStatus,
  RunTaskItem,
  SystemInfo,
  UsagePoint,
} from './types'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: Record<string, unknown>

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** Validation problems, flattened for display next to a form. */
  get problems(): Array<{ field: string; message: string }> {
    const raw = this.details?.problems
    if (!Array.isArray(raw)) return []
    return raw.flatMap((item) =>
      item && typeof item === 'object' && 'message' in item
        ? [{ field: String((item as { field?: string }).field ?? ''), message: String((item as { message: string }).message) }]
        : [],
    )
  }
}

type Query = Record<string, string | number | boolean | null | undefined>

function buildUrl(path: string, query?: Query): string {
  const url = new URL(`${config.apiBaseUrl}${path}`)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    }
  }
  return url.toString()
}

interface RequestOptions {
  method?: 'GET' | 'POST'
  query?: Query
  body?: unknown
  signal?: AbortSignal
  /** Polling requests must never be served from a cache. */
  cache?: RequestCache
  text?: boolean
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (config.apiKey) headers['X-API-Key'] = config.apiKey

  let response: Response
  try {
    response = await fetch(buildUrl(path, options.query), {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      cache: options.cache ?? 'no-store',
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError(
      0,
      'network_error',
      `Could not reach the ${config.productName} API at ${config.apiBaseUrl}. Is the backend running?`,
    )
  }

  if (!response.ok) {
    let code = `http_${response.status}`
    let message = `Request failed with status ${response.status}.`
    let details: Record<string, unknown> | undefined
    try {
      const body = await response.json()
      if (body && typeof body === 'object' && 'error' in body) {
        const payload = (body as { error: { code?: string; message?: string; details?: Record<string, unknown> } }).error
        code = payload.code ?? code
        message = payload.message ?? message
        details = payload.details
      } else if (body && typeof body === 'object' && 'detail' in body) {
        message = String((body as { detail: unknown }).detail)
      }
    } catch {
      // A non-JSON error body: keep the status-derived message.
    }
    throw new ApiError(response.status, code, message, details)
  }

  if (options.text) return (await response.text()) as T
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthStatus>('/health', { signal }),
  system: (signal?: AbortSignal) => request<SystemInfo>('/api/v1/system', { signal }),
  dashboard: (signal?: AbortSignal) => request<Dashboard>('/api/v1/dashboard', { signal }),

  // --- customers ---------------------------------------------------------
  customers: (query: Query, signal?: AbortSignal) =>
    request<Page<CustomerListItem>>('/api/v1/customers', { query, signal }),
  industries: (signal?: AbortSignal) => request<string[]>('/api/v1/customers/industries', { signal }),
  customer: (id: string, signal?: AbortSignal) =>
    request<CustomerDetail>(`/api/v1/customers/${encodeURIComponent(id)}`, { signal }),
  customerUsage: (id: string, days: number, signal?: AbortSignal) =>
    request<UsagePoint[]>(`/api/v1/customers/${encodeURIComponent(id)}/usage`, { query: { days }, signal }),
  customerDocuments: (id: string, query: Query, signal?: AbortSignal) =>
    request<Page<DocumentListItem>>(`/api/v1/customers/${encodeURIComponent(id)}/documents`, { query, signal }),
  customerDocument: (id: string, documentId: string, signal?: AbortSignal) =>
    request<DocumentDetail>(
      `/api/v1/customers/${encodeURIComponent(id)}/documents/${encodeURIComponent(documentId)}`,
      { signal },
    ),
  customerRisk: (id: string, signal?: AbortSignal) =>
    request<CustomerRisk>(`/api/v1/customers/${encodeURIComponent(id)}/risk`, { signal }),

  // --- runs --------------------------------------------------------------
  createRun: (body: CreateRunRequest) =>
    request<CreateRunResponse>('/api/v1/runs', { method: 'POST', body }),
  runs: (query: Query, signal?: AbortSignal) =>
    request<Page<RunListItem>>('/api/v1/runs', { query, signal }),
  run: (runId: string, signal?: AbortSignal) =>
    request<RunDetail>(`/api/v1/runs/${encodeURIComponent(runId)}`, { signal }),
  runTasks: (runId: string, signal?: AbortSignal) =>
    request<RunTaskItem[]>(`/api/v1/runs/${encodeURIComponent(runId)}/tasks`, { signal }),
  cancelRun: (runId: string) =>
    request<RunListItem>(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' }),
  investigations: (runId: string, signal?: AbortSignal) =>
    request<Investigation[]>(`/api/v1/runs/${encodeURIComponent(runId)}/investigations`, { signal }),
  claims: (runId: string, status: ClaimStatus | undefined, signal?: AbortSignal) =>
    request<ClaimItem[]>(`/api/v1/runs/${encodeURIComponent(runId)}/claims`, { query: { status }, signal }),
  evidence: (runId: string, customerId: string | undefined, signal?: AbortSignal) =>
    request<EvidenceItem[]>(`/api/v1/runs/${encodeURIComponent(runId)}/evidence`, {
      query: { customer_id: customerId },
      signal,
    }),
  report: (runId: string, signal?: AbortSignal) =>
    request<Report>(`/api/v1/runs/${encodeURIComponent(runId)}/report`, { signal }),
  reportMarkdownUrl: (runId: string) => `${config.apiBaseUrl}/api/v1/runs/${encodeURIComponent(runId)}/report.md`,

  // --- reports -----------------------------------------------------------
  reports: (query: Query, signal?: AbortSignal) =>
    request<Page<ReportListItem>>('/api/v1/reports', { query, signal }),

  // --- approvals ---------------------------------------------------------
  approvals: (query: Query, signal?: AbortSignal) =>
    request<Page<Approval>>('/api/v1/approvals', { query, signal }),
  approve: (approvalId: string, body: { reviewed_by: string; comment?: string | null }) =>
    request<Approval>(`/api/v1/approvals/${encodeURIComponent(approvalId)}/approve`, { method: 'POST', body }),
  reject: (approvalId: string, body: { reviewed_by: string; comment?: string | null }) =>
    request<Approval>(`/api/v1/approvals/${encodeURIComponent(approvalId)}/reject`, { method: 'POST', body }),

  // --- evaluation --------------------------------------------------------
  runEvaluation: (body: { name?: string; sample_size?: number; retrieval_sample?: number }) =>
    request<EvaluationRun>('/api/v1/evaluations/run', { method: 'POST', body }),
  evaluations: (query: Query, signal?: AbortSignal) =>
    request<Page<EvaluationRun>>('/api/v1/evaluations', { query, signal }),
  latestEvaluation: (signal?: AbortSignal) =>
    request<EvaluationRun | null>('/api/v1/evaluations/latest', { signal }),
}

/** Statuses that mean "work is still in flight", so the UI should keep polling. */
export const ACTIVE_RUN_STATUSES: readonly RunStatus[] = ['PENDING', 'QUEUED', 'RUNNING', 'RETRYING']

export function isRunActive(status: RunStatus): boolean {
  return ACTIVE_RUN_STATUSES.includes(status)
}

export const PENDING_APPROVAL: ApprovalStatus = 'PENDING'
