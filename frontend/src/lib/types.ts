/**
 * API types, mirroring the FastAPI response schemas.
 *
 * Hand-written rather than generated so the shapes the UI actually relies on
 * are explicit and reviewable; `make typecheck` catches drift at the call site
 * and the integration tests assert the backend contract.
 */

export type RunStatus =
  | 'PENDING'
  | 'QUEUED'
  | 'RUNNING'
  | 'RETRYING'
  | 'WAITING_FOR_APPROVAL'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'

export type TaskStatus =
  | 'PENDING'
  | 'QUEUED'
  | 'RUNNING'
  | 'RETRYING'
  | 'WAITING_FOR_APPROVAL'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  | 'SKIPPED'

export type StageStatus =
  | 'PENDING'
  | 'RUNNING'
  | 'RETRYING'
  | 'WAITING_FOR_APPROVAL'
  | 'COMPLETED'
  | 'PARTIAL'
  | 'FAILED'
  | 'SKIPPED'
  | 'CANCELLED'

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type ClaimStatus =
  | 'PENDING'
  | 'SUPPORTED'
  | 'PARTIALLY_SUPPORTED'
  | 'UNSUPPORTED'
  | 'CONTRADICTED'

export type ClaimType = 'OBSERVED_FACT' | 'CALCULATED_METRIC' | 'INFERENCE'

export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED'

export type AccountTier = 'ENTERPRISE' | 'MID_MARKET' | 'SMB' | 'STARTUP'

export type WorkflowMode = 'STANDARD' | 'REVIEW_ALL' | 'READ_ONLY'

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface SubscriptionSummary {
  plan: string
  monthly_recurring_revenue: number
  annual_contract_value: number
  contract_start: string
  contract_end: string
  renewal_date: string
  subscription_status: string
  seats_purchased: number
  days_to_renewal: number | null
}

export interface CustomerListItem {
  id: string
  external_id: string
  company_name: string
  industry: string
  country: string
  account_tier: string
  account_manager: string
  employee_count: number
  subscription: SubscriptionSummary | null
  outcome: string | null
}

export interface UsagePoint {
  usage_date: string
  active_users: number
  sessions: number
  total_logins: number
  api_calls: number
  projects_created: number
  feature_adoption_score: number
  seats_active: number
}

export interface TicketSummary {
  id: string
  external_ticket_id: string
  created_at: string
  resolved_at: string | null
  category: string
  priority: string
  status: string
  resolution_hours: number | null
  csat_score: number | null
  subject: string
}

export interface PaymentSummaryItem {
  id: string
  invoice_date: string
  due_date: string | null
  amount: number
  payment_date: string | null
  payment_status: string
  days_overdue: number
}

export interface NpsResponseItem {
  id: string
  response_date: string
  score: number
  feedback: string
}

export interface DocumentListItem {
  id: string
  source_type: string
  title: string
  source_date: string
  chars: number
  chunk_count: number
}

export interface DocumentDetail {
  id: string
  customer_id: string
  source_type: string
  title: string
  source_date: string
  content: string
  metadata: Record<string, unknown>
}

export interface RiskSignal {
  key: string
  label: string
  value: number | null
  unit: string
  severity: number
  weight: number
  contribution: number
  detail: string
}

export interface CustomerRisk {
  customer_id: string
  external_id: string
  company_name: string
  heuristic_risk_score: number
  risk_level: RiskLevel
  coverage: number
  days_to_renewal: number | null
  renewal_multiplier: number
  missing_signals: string[]
  signals: RiskSignal[]
  model: Record<string, unknown>
}

export interface InvestigationHistoryItem {
  id: string
  run_id: string
  risk_score: number
  risk_level: string
  confidence: number
  summary: string
  created_at: string
}

export interface CustomerDetail {
  customer: CustomerListItem
  usage: UsagePoint[]
  usage_summary: {
    data_points: number
    recent_active_users: number | null
    baseline_active_users: number | null
    active_user_change_pct: number | null
    usage_change_pct: number | null
    feature_adoption_change_pct: number | null
    seat_utilization: number | null
    seats_active: number | null
    seats_purchased: number | null
    latest_usage_date: string | null
  }
  tickets: TicketSummary[]
  support_summary: {
    recent_ticket_count: number
    baseline_ticket_count: number
    ticket_growth_pct: number | null
    open_ticket_count: number
    critical_ticket_count: number
    unresolved_critical_count: number
    average_csat: number | null
    csat_responses: number
    average_resolution_hours: number | null
  }
  payments: PaymentSummaryItem[]
  payment_summary: {
    invoice_count: number
    overdue_invoice_count: number
    max_days_overdue: number
    total_overdue_amount: number
    delinquency_ratio: number | null
    latest_invoice_status: string | null
    has_failed_payment: boolean
  }
  nps: NpsResponseItem[]
  nps_summary: {
    latest_score: number | null
    previous_score: number | null
    score_delta: number | null
    average_score: number | null
    response_count: number
    latest_feedback: string | null
  }
  documents: DocumentListItem[]
  risk: CustomerRisk
  outcome: {
    outcome: string
    outcome_date: string | null
    churn_reason: string | null
    notes: string | null
  } | null
  investigations: InvestigationHistoryItem[]
}

export interface CreateRunRequest {
  objective: string
  account_tier?: AccountTier | null
  renewal_window_days?: number | null
  max_accounts?: number | null
  workflow_mode?: WorkflowMode
  risk_threshold?: number | null
  created_by?: string
}

export interface CreateRunResponse {
  run_id: string
  status: RunStatus
  objective: string
  created_at: string
  workflow_type: string
  parameters: Record<string, unknown>
  executor: string
}

export interface RunListItem {
  id: string
  objective: string
  workflow_type: string
  workflow_mode: string
  status: RunStatus
  progress: number
  current_stage: string
  created_at: string
  started_at: string | null
  completed_at: string | null
  failed_at: string | null
  error_message: string | null
  created_by: string
  duration_seconds: number | null
  investigation_count: number
  pending_approvals: number
}

export interface RunTaskItem {
  id: string
  task_key: string
  agent_type: string
  description: string
  stage: string
  status: TaskStatus
  dependencies: string[]
  retry_count: number
  max_retries: number
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
  output_summary: Record<string, unknown>
}

export interface AuditEventItem {
  id: string
  event_type: string
  actor_type: string
  actor_id: string
  message: string
  payload: Record<string, unknown>
  customer_id: string | null
  trace_id: string | null
  created_at: string
}

export interface RunStage {
  key: string
  label: string
  status: StageStatus
  progress_marker: number
  task_count: number
  tasks: string[]
  retry_count: number
  duration_ms: number | null
  error: string | null
}

export interface EvidenceItem {
  id: string
  reference: string
  customer_id: string | null
  source_type: string
  source_id: string
  title: string
  content: string
  source_date: string | null
  relevance_score: number | null
  metadata: Record<string, unknown>
  created_at: string
}

export interface ClaimItem {
  id: string
  claim_key: string
  customer_id: string | null
  claim_text: string
  final_text: string | null
  claim_type: ClaimType
  status: ClaimStatus
  confidence: number
  verification_reason: string | null
  suggested_revision: string | null
  evidence_references: string[]
  verified_at: string | null
  created_at: string
}

export interface RecommendedAction {
  action_type: string
  description: string
  rationale: string
  priority: number
  requires_approval: boolean
  approval_status: string | null
}

export interface Investigation {
  id: string
  run_id: string
  customer_id: string
  external_id: string
  company_name: string
  account_tier: string
  renewal_date: string | null
  monthly_recurring_revenue: number | null
  risk_score: number
  heuristic_risk_score: number
  risk_level: RiskLevel
  confidence: number
  summary: string
  risk_factors: Array<{
    factor: string
    explanation: string
    severity: string
    evidence_references: string[]
  }>
  quantitative_signals: {
    assessment?: {
      score: number
      level: string
      coverage: number
      days_to_renewal: number | null
      signals: RiskSignal[]
      missing_signals: string[]
    }
    metrics?: Record<string, Record<string, unknown>>
  }
  recommended_actions: RecommendedAction[]
  data_gaps: string[]
  claims: ClaimItem[]
  evidence: EvidenceItem[]
  created_at: string
}

export interface Approval {
  id: string
  run_id: string
  customer_id: string | null
  company_name: string
  action_type: string
  proposed_action: string
  action_payload: Record<string, unknown>
  status: ApprovalStatus
  reason: string
  requested_at: string
  reviewed_at: string | null
  reviewed_by: string | null
  reviewer_comment: string | null
  run_objective: string
}

export interface RunDetail {
  run: RunListItem
  parameters: Record<string, unknown>
  plan: {
    objective: string
    workflow_type: string
    reasoning: string
    tasks: Array<{
      id: string
      agent: string
      description: string
      stage: string
      dependencies: string[]
      parameters: Record<string, unknown>
    }>
  } | null
  stages: RunStage[]
  tasks: RunTaskItem[]
  events: AuditEventItem[]
  verification: {
    total: number
    counts: Record<string, number>
    supported_pct: number | null
    partially_supported_pct: number | null
    unsupported_pct: number | null
  } | null
  llm_usage: {
    calls: number
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    estimated_cost_usd: number
    avg_latency_ms: number
  } | null
  investigation_summaries: Array<{
    customer_id: string
    external_id: string
    company_name: string
    risk_score: number
    heuristic_risk_score: number
    risk_level: string
    confidence: number
    summary: string
  }>
  approvals: Approval[]
  has_report: boolean
}

export interface ReportAccountSection {
  customer_external_id: string
  company_name: string
  risk_score: number
  risk_level: RiskLevel
  confidence: number
  renewal_date: string | null
  monthly_recurring_revenue: number | null
  quantitative_indicators: string[]
  qualitative_evidence: string[]
  verified_conclusions: string[]
  qualified_findings: string[]
  excluded_conclusions: string[]
  recommended_actions: RecommendedAction[]
  evidence_references: string[]
  uncertainties: string[]
}

export interface Report {
  id: string
  run_id: string
  title: string
  executive_summary: string
  markdown_content: string
  created_at: string
  report_payload: {
    generated_at: string
    product: string
    objective: string
    parameters: Record<string, unknown>
    statistics: Record<string, number | string | null>
    report: {
      title: string
      executive_summary: string
      accounts: ReportAccountSection[]
      portfolio_observations: string[]
      unresolved_uncertainties: string[]
      methodology_notes: string[]
    }
    evidence_index: Array<{
      reference: string
      customer_external_id: string
      source_type: string
      source_id: string
      source_date: string | null
      title: string
      relevance_score: number | null
      content: string
    }>
  }
}

export interface ReportListItem {
  id: string
  run_id: string
  title: string
  executive_summary: string
  created_at: string
  account_count: number
  objective: string
}

export interface Dashboard {
  investigations_completed: number
  runs_running: number
  runs_failed: number
  runs_total: number
  pending_approvals: number
  high_risk_customers: number
  avg_run_duration_seconds: number | null
  verified_claim_pct: number | null
  unsupported_claim_pct: number | null
  partially_supported_claim_pct: number | null
  total_customers: number
  renewing_within_90_days: number
  evidence_records: number
  embedded_chunks: number
  llm_usage: {
    calls: number
    total_tokens: number
    estimated_cost_usd: number
    avg_latency_ms: number
    provider: string
    model: string
  }
  recent_runs: RunListItem[]
  high_risk_accounts: Array<{
    customer_id: string
    external_id: string
    company_name: string
    account_tier: string
    risk_score: number
    risk_level: string
    renewal_date: string | null
    monthly_recurring_revenue: number | null
    run_id: string
    created_at: string
  }>
  dataset: {
    total_customers: number
    documents: number
    document_chunks: number
    embedded_chunks: number
    renewing_within_90_days: number
    outcomes: Record<string, number>
    tiers: Record<string, number>
    total_acv: number
  }
}

export interface AgentCard {
  name: string
  role: string
  uses_llm: boolean
  model: string | null
  provider: string | null
  allowed_tools: string[]
  timeout_seconds: number
  max_retries: number
  output_schema: string | null
}

export interface ToolCard {
  name: string
  description: string
  access: string
  read_only: boolean
  requires_approval: boolean
  timeout_seconds: number
  max_attempts: number
}

export interface SystemInfo {
  product: string
  tagline: string
  environment: string
  workflow_executor: string
  llm_provider: string
  llm_model: string
  embedding_provider: string
  embedding_model: string
  tracing_enabled: boolean
  langfuse_configured: boolean
  failure_injection: {
    active: boolean
    llm_failure_rate: number
    vector_failure_rate: number
    api_failure_rate: number
    note: string
  }
  limits: Record<string, number>
  agents: AgentCard[]
  tools: ToolCard[]
  risk_model: {
    model_type: string
    is_trained_model: boolean
    description: string
    weights: Record<string, number>
    aggregation: { weighted_average_share: number; dominant_signal_share: number; note: string }
    renewal_multipliers: Record<string, number>
    levels: Record<string, string>
    agent_adjustment_band_points: number
  }
  approval_policy: Array<{ action_type: string; requires_approval: boolean; reason: string }>
}

export interface HealthStatus {
  status: string
  product: string
  version: string
  environment: string
  database: string
  pgvector: boolean
  redis: string
  llm_provider: string
  llm_model: string
  embedding_provider: string
  failure_injection: boolean
  checks: Record<string, unknown>
}

export interface EvaluationMetrics {
  dataset: {
    labelled_customers: number
    positive_outcomes?: number
    negative_outcomes?: number
    base_rate?: number | null
  }
  ranking: {
    note?: string
    at_k?: Record<string, { precision: number; recall: number | null; hits: number }>
    at_percentile?: Record<string, { k: number; precision: number; recall: number | null; lift: number | null }>
    roc_auc?: number | null
    average_precision?: number | null
    score_distribution?: Record<string, number | null>
    mean_score_positive?: number | null
    mean_score_negative?: number | null
  }
  retrieval: {
    note?: string
    accounts_sampled?: number
    chunks_returned?: number
    accounts_with_no_matches?: number
    customer_scope_precision?: number | null
    risk_relevant_chunk_rate?: number | null
    accounts_with_risk_signal_rate?: number | null
    mean_relevance_score?: number | null
    embedding_provider?: string
    metric_note?: string
  }
  workflow: {
    note?: string
    runs_total?: number
    runs_completed?: number
    runs_failed?: number
    runs_cancelled?: number
    runs_awaiting_approval?: number
    completion_rate?: number | null
    avg_duration_seconds?: number | null
    p95_duration_seconds?: number | null
    tasks_total?: number
    tasks_failed?: number
    tasks_retried?: number
    retry_recovery_rate?: number | null
    llm_calls?: number
    total_tokens?: number
    avg_tokens_per_call?: number | null
    estimated_cost_usd?: number
    avg_llm_latency_ms?: number
    invalid_structured_outputs?: number
    claims?: Record<string, number | string | Record<string, number>>
    reports?: Record<string, number | boolean>
  }
  model: { type: string; is_trained_model: boolean; weights: Record<string, number> }
  generated_at: string
  caveat: string
}

export interface EvaluationRun {
  id: string
  name: string
  status: string
  dataset_description: string
  parameters: Record<string, unknown>
  metrics: EvaluationMetrics | Record<string, never>
  details: Record<string, unknown>
  error_message: string | null
  duration_ms: number | null
  created_at: string
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
  }
}
