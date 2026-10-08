"""initial schema

Revision ID: 1a2dfc1be8e1
Revises: 
Create Date: 2026-10-08 01:41:57.487745
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector must exist before document_chunks.embedding is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table('customers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('external_id', sa.String(length=64), nullable=False),
    sa.Column('company_name', sa.String(length=200), nullable=False),
    sa.Column('industry', sa.String(length=80), nullable=False),
    sa.Column('country', sa.String(length=80), nullable=False),
    sa.Column('company_size', sa.String(length=40), nullable=False),
    sa.Column('employee_count', sa.Integer(), nullable=False),
    sa.Column('account_tier', sa.String(length=20), nullable=False),
    sa.Column('account_manager', sa.String(length=120), nullable=False),
    sa.Column('scenario_persona', sa.String(length=60), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("account_tier IN ('ENTERPRISE', 'MID_MARKET', 'SMB', 'STARTUP')", name=op.f('ck_customers_account_tier_valid')),
    sa.CheckConstraint('employee_count >= 0', name=op.f('ck_customers_employee_count_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customers')),
    sa.UniqueConstraint('external_id', name=op.f('uq_customers_external_id'))
    )
    op.create_index(op.f('ix_customers_account_tier'), 'customers', ['account_tier'], unique=False)
    op.create_index(op.f('ix_customers_company_name'), 'customers', ['company_name'], unique=False)
    op.create_index(op.f('ix_customers_created_at'), 'customers', ['created_at'], unique=False)
    op.create_index('ix_customers_tier_name', 'customers', ['account_tier', 'company_name'], unique=False)
    op.create_table('evaluation_runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('dataset_description', sa.Text(), nullable=False),
    sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('RUNNING', 'COMPLETED', 'FAILED')", name=op.f('ck_evaluation_runs_evaluation_status_valid')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evaluation_runs'))
    )
    op.create_index(op.f('ix_evaluation_runs_created_at'), 'evaluation_runs', ['created_at'], unique=False)
    op.create_index(op.f('ix_evaluation_runs_status'), 'evaluation_runs', ['status'], unique=False)
    op.create_table('runs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('objective', sa.Text(), nullable=False),
    sa.Column('workflow_type', sa.String(length=60), nullable=False),
    sa.Column('workflow_mode', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('current_stage', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_by', sa.String(length=120), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint("status IN ('PENDING', 'QUEUED', 'RUNNING', 'RETRYING', 'WAITING_FOR_APPROVAL', 'COMPLETED', 'FAILED', 'CANCELLED')", name=op.f('ck_runs_run_status_valid')),
    sa.CheckConstraint('progress >= 0 AND progress <= 100', name=op.f('ck_runs_run_progress_range')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_runs'))
    )
    op.create_index(op.f('ix_runs_created_at'), 'runs', ['created_at'], unique=False)
    op.create_index(op.f('ix_runs_status'), 'runs', ['status'], unique=False)
    op.create_index('ix_runs_status_created', 'runs', ['status', 'created_at'], unique=False)
    op.create_table('approvals',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=True),
    sa.Column('action_type', sa.String(length=40), nullable=False),
    sa.Column('proposed_action', sa.Text(), nullable=False),
    sa.Column('action_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('idempotency_key', sa.String(length=200), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reviewed_by', sa.String(length=120), nullable=True),
    sa.Column('reviewer_comment', sa.Text(), nullable=True),
    sa.CheckConstraint("action_type IN ('INTERNAL_REVIEW', 'SCHEDULE_INTERNAL_MEETING', 'MONITOR_USAGE', 'PREPARE_BRIEFING', 'ASSIGN_OWNER', 'SEND_CUSTOMER_EMAIL', 'OFFER_DISCOUNT', 'UPDATE_CRM_RECORD', 'CHANGE_SUBSCRIPTION', 'ESCALATE_TO_EXECUTIVE', 'SCHEDULE_CUSTOMER_CALL')", name=op.f('ck_approvals_approval_action_type_valid')),
    sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')", name=op.f('ck_approvals_approval_status_valid')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_approvals_customer_id_customers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_approvals_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approvals')),
    sa.UniqueConstraint('run_id', 'idempotency_key', name='uq_approvals_run_idempotency')
    )
    op.create_index(op.f('ix_approvals_status'), 'approvals', ['status'], unique=False)
    op.create_index('ix_approvals_status_requested', 'approvals', ['status', 'requested_at'], unique=False)
    op.create_table('claims',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=True),
    sa.Column('claim_key', sa.String(length=120), nullable=False),
    sa.Column('claim_text', sa.Text(), nullable=False),
    sa.Column('claim_type', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('verification_reason', sa.Text(), nullable=True),
    sa.Column('suggested_revision', sa.Text(), nullable=True),
    sa.Column('final_text', sa.Text(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("claim_type IN ('OBSERVED_FACT', 'CALCULATED_METRIC', 'INFERENCE')", name=op.f('ck_claims_claim_type_valid')),
    sa.CheckConstraint("status IN ('PENDING', 'SUPPORTED', 'PARTIALLY_SUPPORTED', 'UNSUPPORTED', 'CONTRADICTED')", name=op.f('ck_claims_claim_status_valid')),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name=op.f('ck_claims_claim_confidence_range')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_claims_customer_id_customers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_claims_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_claims')),
    sa.UniqueConstraint('run_id', 'claim_key', name='uq_claims_run_key')
    )
    op.create_index('ix_claims_run_customer', 'claims', ['run_id', 'customer_id'], unique=False)
    op.create_index(op.f('ix_claims_status'), 'claims', ['status'], unique=False)
    op.create_table('customer_documents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('source_date', sa.Date(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("source_type IN ('CUSTOMER_EMAIL', 'CSM_NOTE', 'QBR_NOTE', 'RENEWAL_NOTE', 'MEETING_SUMMARY', 'ONBOARDING_NOTE', 'SUPPORT_SUMMARY')", name=op.f('ck_customer_documents_document_source_type_valid')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_customer_documents_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_documents'))
    )
    op.create_index('ix_customer_documents_customer_date', 'customer_documents', ['customer_id', 'source_date'], unique=False)
    op.create_index(op.f('ix_customer_documents_source_type'), 'customer_documents', ['source_type'], unique=False)
    op.create_table('customer_outcomes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('outcome', sa.String(length=20), nullable=False),
    sa.Column('outcome_date', sa.Date(), nullable=True),
    sa.Column('churn_reason', sa.String(length=120), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.CheckConstraint("outcome IN ('CHURNED', 'RENEWED', 'DOWNGRADED', 'EXPANDED', 'UNKNOWN')", name=op.f('ck_customer_outcomes_customer_outcome_valid')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_customer_outcomes_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_outcomes')),
    sa.UniqueConstraint('customer_id', name=op.f('uq_customer_outcomes_customer_id'))
    )
    op.create_index(op.f('ix_customer_outcomes_outcome'), 'customer_outcomes', ['outcome'], unique=False)
    op.create_table('evidence',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=True),
    sa.Column('source_type', sa.String(length=40), nullable=False),
    sa.Column('source_id', sa.String(length=120), nullable=False),
    sa.Column('reference', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('source_date', sa.Date(), nullable=True),
    sa.Column('relevance_score', sa.Numeric(precision=6, scale=4), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("source_type IN ('DOCUMENT_CHUNK', 'SUPPORT_TICKET', 'NPS_SURVEY', 'USAGE_METRIC', 'PAYMENT_RECORD', 'SUBSCRIPTION')", name=op.f('ck_evidence_evidence_source_type_valid')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_evidence_customer_id_customers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_evidence_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence')),
    sa.UniqueConstraint('run_id', 'customer_id', 'source_id', name='uq_evidence_run_customer_source'),
    sa.UniqueConstraint('run_id', 'reference', name='uq_evidence_run_reference')
    )
    op.create_index('ix_evidence_run_customer', 'evidence', ['run_id', 'customer_id'], unique=False)
    op.create_table('investigations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('risk_score', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('heuristic_risk_score', sa.Numeric(precision=6, scale=2), nullable=False),
    sa.Column('risk_level', sa.String(length=20), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('risk_factors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('quantitative_signals', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('recommended_actions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('data_gaps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("risk_level IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')", name=op.f('ck_investigations_investigation_risk_level_valid')),
    sa.CheckConstraint('risk_score >= 0 AND risk_score <= 100', name=op.f('ck_investigations_investigation_risk_range')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_investigations_customer_id_customers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_investigations_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_investigations')),
    sa.UniqueConstraint('run_id', 'customer_id', name='uq_investigations_run_customer')
    )
    op.create_index(op.f('ix_investigations_risk_level'), 'investigations', ['risk_level'], unique=False)
    op.create_table('llm_calls',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('task_key', sa.String(length=120), nullable=True),
    sa.Column('agent', sa.String(length=40), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('operation', sa.String(length=60), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=False),
    sa.Column('completion_tokens', sa.Integer(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('estimated_cost_usd', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('valid_output', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_llm_calls_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llm_calls'))
    )
    op.create_index(op.f('ix_llm_calls_created_at'), 'llm_calls', ['created_at'], unique=False)
    op.create_index('ix_llm_calls_run_agent', 'llm_calls', ['run_id', 'agent'], unique=False)
    op.create_table('nps_surveys',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('response_date', sa.Date(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('feedback', sa.Text(), nullable=False),
    sa.CheckConstraint('score >= 0 AND score <= 10', name=op.f('ck_nps_surveys_nps_score_range')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_nps_surveys_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_nps_surveys'))
    )
    op.create_index('ix_nps_surveys_customer_date', 'nps_surveys', ['customer_id', 'response_date'], unique=False)
    op.create_table('payments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('invoice_date', sa.Date(), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('payment_date', sa.Date(), nullable=True),
    sa.Column('payment_status', sa.String(length=20), nullable=False),
    sa.Column('days_overdue', sa.Integer(), nullable=False),
    sa.CheckConstraint("payment_status IN ('PAID', 'PENDING', 'OVERDUE', 'FAILED', 'WRITTEN_OFF')", name=op.f('ck_payments_payment_status_valid')),
    sa.CheckConstraint('amount >= 0', name=op.f('ck_payments_payment_amount_non_negative')),
    sa.CheckConstraint('days_overdue >= 0', name=op.f('ck_payments_days_overdue_non_negative')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_payments_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments'))
    )
    op.create_index('ix_payments_customer_invoice', 'payments', ['customer_id', 'invoice_date'], unique=False)
    op.create_index(op.f('ix_payments_payment_status'), 'payments', ['payment_status'], unique=False)
    op.create_table('product_usage',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('usage_date', sa.Date(), nullable=False),
    sa.Column('active_users', sa.Integer(), nullable=False),
    sa.Column('total_logins', sa.Integer(), nullable=False),
    sa.Column('sessions', sa.Integer(), nullable=False),
    sa.Column('projects_created', sa.Integer(), nullable=False),
    sa.Column('api_calls', sa.Integer(), nullable=False),
    sa.Column('feature_adoption_score', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('seats_active', sa.Integer(), nullable=False),
    sa.CheckConstraint('active_users >= 0', name=op.f('ck_product_usage_active_users_non_negative')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_product_usage_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_product_usage')),
    sa.UniqueConstraint('customer_id', 'usage_date', name='uq_product_usage_customer_date')
    )
    op.create_index('ix_product_usage_customer_date', 'product_usage', ['customer_id', 'usage_date'], unique=False)
    op.create_table('reports',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('executive_summary', sa.Text(), nullable=False),
    sa.Column('report_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('markdown_content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_reports_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reports')),
    sa.UniqueConstraint('run_id', name=op.f('uq_reports_run_id'))
    )
    op.create_table('run_tasks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=False),
    sa.Column('task_key', sa.String(length=120), nullable=False),
    sa.Column('agent_type', sa.String(length=40), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('stage', sa.String(length=60), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('dependencies', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('input_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('output_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('retry_count', sa.Integer(), nullable=False),
    sa.Column('max_retries', sa.Integer(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('dispatch_token', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.CheckConstraint("status IN ('PENDING', 'QUEUED', 'RUNNING', 'RETRYING', 'WAITING_FOR_APPROVAL', 'COMPLETED', 'FAILED', 'CANCELLED', 'SKIPPED')", name=op.f('ck_run_tasks_task_status_valid')),
    sa.CheckConstraint('retry_count >= 0', name=op.f('ck_run_tasks_task_retry_non_negative')),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_run_tasks_run_id_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_run_tasks')),
    sa.UniqueConstraint('run_id', 'task_key', name='uq_run_tasks_run_key')
    )
    op.create_index('ix_run_tasks_run_status', 'run_tasks', ['run_id', 'status'], unique=False)
    op.create_index(op.f('ix_run_tasks_status'), 'run_tasks', ['status'], unique=False)
    op.create_table('subscriptions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('plan', sa.String(length=60), nullable=False),
    sa.Column('monthly_recurring_revenue', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('annual_contract_value', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('contract_start', sa.Date(), nullable=False),
    sa.Column('contract_end', sa.Date(), nullable=False),
    sa.Column('renewal_date', sa.Date(), nullable=False),
    sa.Column('subscription_status', sa.String(length=20), nullable=False),
    sa.Column('seats_purchased', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("subscription_status IN ('ACTIVE', 'PAST_DUE', 'CANCELLED', 'PAUSED')", name=op.f('ck_subscriptions_subscription_status_valid')),
    sa.CheckConstraint('contract_end >= contract_start', name=op.f('ck_subscriptions_contract_dates_ordered')),
    sa.CheckConstraint('monthly_recurring_revenue >= 0', name=op.f('ck_subscriptions_mrr_non_negative')),
    sa.CheckConstraint('seats_purchased >= 0', name=op.f('ck_subscriptions_seats_non_negative')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_subscriptions_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_subscriptions')),
    sa.UniqueConstraint('customer_id', name=op.f('uq_subscriptions_customer_id'))
    )
    op.create_index(op.f('ix_subscriptions_created_at'), 'subscriptions', ['created_at'], unique=False)
    op.create_index(op.f('ix_subscriptions_renewal_date'), 'subscriptions', ['renewal_date'], unique=False)
    op.create_index('ix_subscriptions_renewal_status', 'subscriptions', ['renewal_date', 'subscription_status'], unique=False)
    op.create_index(op.f('ix_subscriptions_subscription_status'), 'subscriptions', ['subscription_status'], unique=False)
    op.create_table('support_tickets',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('external_ticket_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('category', sa.String(length=60), nullable=False),
    sa.Column('priority', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('resolution_hours', sa.Numeric(precision=8, scale=2), nullable=True),
    sa.Column('csat_score', sa.Numeric(precision=3, scale=1), nullable=True),
    sa.Column('subject', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.CheckConstraint("priority IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')", name=op.f('ck_support_tickets_ticket_priority_valid')),
    sa.CheckConstraint("status IN ('OPEN', 'PENDING', 'RESOLVED', 'CLOSED', 'ESCALATED')", name=op.f('ck_support_tickets_ticket_status_valid')),
    sa.CheckConstraint('csat_score IS NULL OR (csat_score >= 1 AND csat_score <= 5)', name=op.f('ck_support_tickets_csat_range')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_support_tickets_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_support_tickets')),
    sa.UniqueConstraint('external_ticket_id', name=op.f('uq_support_tickets_external_ticket_id'))
    )
    op.create_index(op.f('ix_support_tickets_created_at'), 'support_tickets', ['created_at'], unique=False)
    op.create_index('ix_support_tickets_customer_created', 'support_tickets', ['customer_id', 'created_at'], unique=False)
    op.create_table('audit_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('run_id', sa.UUID(), nullable=True),
    sa.Column('task_id', sa.UUID(), nullable=True),
    sa.Column('customer_id', sa.UUID(), nullable=True),
    sa.Column('event_type', sa.String(length=60), nullable=False),
    sa.Column('actor_type', sa.String(length=20), nullable=False),
    sa.Column('actor_id', sa.String(length=120), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('trace_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("actor_type IN ('SYSTEM', 'AGENT', 'HUMAN', 'WORKER')", name=op.f('ck_audit_events_audit_actor_type_valid')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_audit_events_customer_id_customers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['run_id'], ['runs.id'], name=op.f('fk_audit_events_run_id_runs'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['run_tasks.id'], name=op.f('fk_audit_events_task_id_run_tasks'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index(op.f('ix_audit_events_created_at'), 'audit_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_events_event_type'), 'audit_events', ['event_type'], unique=False)
    op.create_index('ix_audit_events_run_created', 'audit_events', ['run_id', 'created_at'], unique=False)
    op.create_table('claim_evidence',
    sa.Column('claim_id', sa.UUID(), nullable=False),
    sa.Column('evidence_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['claim_id'], ['claims.id'], name=op.f('fk_claim_evidence_claim_id_claims'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], name=op.f('fk_claim_evidence_evidence_id_evidence'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('claim_id', 'evidence_id', name=op.f('pk_claim_evidence'))
    )
    op.create_index('ix_claim_evidence_evidence', 'claim_evidence', ['evidence_id'], unique=False)
    op.create_table('document_chunks',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('document_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=True),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_document_chunks_customer_id_customers'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['document_id'], ['customer_documents.id'], name=op.f('fk_document_chunks_document_id_customer_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_chunks')),
    sa.UniqueConstraint('document_id', 'chunk_index', name='uq_document_chunks_doc_index')
    )
    op.create_index('ix_document_chunks_customer', 'document_chunks', ['customer_id'], unique=False)
    _create_vector_index()
    # ### end Alembic commands ###


def _create_vector_index() -> None:
    """HNSW index for cosine similarity over document chunks.

    Built after the table so seeding a fresh database inserts into an empty
    index. ``lists``/``m`` defaults are fine at this corpus size; tune
    ``ef_search`` per session if recall needs to go up.
    """
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index('ix_document_chunks_customer', table_name='document_chunks')
    op.drop_table('document_chunks')
    op.drop_index('ix_claim_evidence_evidence', table_name='claim_evidence')
    op.drop_table('claim_evidence')
    op.drop_index('ix_audit_events_run_created', table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_event_type'), table_name='audit_events')
    op.drop_index(op.f('ix_audit_events_created_at'), table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_index('ix_support_tickets_customer_created', table_name='support_tickets')
    op.drop_index(op.f('ix_support_tickets_created_at'), table_name='support_tickets')
    op.drop_table('support_tickets')
    op.drop_index(op.f('ix_subscriptions_subscription_status'), table_name='subscriptions')
    op.drop_index('ix_subscriptions_renewal_status', table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_renewal_date'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_created_at'), table_name='subscriptions')
    op.drop_table('subscriptions')
    op.drop_index(op.f('ix_run_tasks_status'), table_name='run_tasks')
    op.drop_index('ix_run_tasks_run_status', table_name='run_tasks')
    op.drop_table('run_tasks')
    op.drop_table('reports')
    op.drop_index('ix_product_usage_customer_date', table_name='product_usage')
    op.drop_table('product_usage')
    op.drop_index(op.f('ix_payments_payment_status'), table_name='payments')
    op.drop_index('ix_payments_customer_invoice', table_name='payments')
    op.drop_table('payments')
    op.drop_index('ix_nps_surveys_customer_date', table_name='nps_surveys')
    op.drop_table('nps_surveys')
    op.drop_index('ix_llm_calls_run_agent', table_name='llm_calls')
    op.drop_index(op.f('ix_llm_calls_created_at'), table_name='llm_calls')
    op.drop_table('llm_calls')
    op.drop_index(op.f('ix_investigations_risk_level'), table_name='investigations')
    op.drop_table('investigations')
    op.drop_index('ix_evidence_run_customer', table_name='evidence')
    op.drop_table('evidence')
    op.drop_index(op.f('ix_customer_outcomes_outcome'), table_name='customer_outcomes')
    op.drop_table('customer_outcomes')
    op.drop_index(op.f('ix_customer_documents_source_type'), table_name='customer_documents')
    op.drop_index('ix_customer_documents_customer_date', table_name='customer_documents')
    op.drop_table('customer_documents')
    op.drop_index(op.f('ix_claims_status'), table_name='claims')
    op.drop_index('ix_claims_run_customer', table_name='claims')
    op.drop_table('claims')
    op.drop_index('ix_approvals_status_requested', table_name='approvals')
    op.drop_index(op.f('ix_approvals_status'), table_name='approvals')
    op.drop_table('approvals')
    op.drop_index('ix_runs_status_created', table_name='runs')
    op.drop_index(op.f('ix_runs_status'), table_name='runs')
    op.drop_index(op.f('ix_runs_created_at'), table_name='runs')
    op.drop_table('runs')
    op.drop_index(op.f('ix_evaluation_runs_status'), table_name='evaluation_runs')
    op.drop_index(op.f('ix_evaluation_runs_created_at'), table_name='evaluation_runs')
    op.drop_table('evaluation_runs')
    op.drop_index('ix_customers_tier_name', table_name='customers')
    op.drop_index(op.f('ix_customers_created_at'), table_name='customers')
    op.drop_index(op.f('ix_customers_company_name'), table_name='customers')
    op.drop_index(op.f('ix_customers_account_tier'), table_name='customers')
    op.drop_table('customers')
    # ### end Alembic commands ###
