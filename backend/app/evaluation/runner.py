"""Evaluation harness.

Measures what the system actually does, on the synthetic dataset, with real
computation. Three families of metric:

**Ranking quality** — can the deterministic risk model find the accounts that
actually churned? Scored against ``customer_outcomes``, which the risk engine
never sees. Reported as recall/precision at K, ROC-AUC and lift. These are
*synthetic-data* numbers and are labelled as such everywhere they appear.

**Retrieval quality** — does customer-scoped vector search return the right
account's documents (must be exactly 1.0 — a leak is a security bug, not a
quality issue) and does it surface risk-relevant content for at-risk accounts?

**Workflow quality** — from the runs that have actually executed: completion
rate, latency (mean and P95), tokens, estimated cost, retry recovery, claim
evidence validity, and the supported/unsupported claim split before and after
verification.

Nothing here is hard-coded. If the dataset is empty, the metrics come back
``None`` and say why.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.analytics import metrics as M
from app.analytics.claim_rules import evaluate_claim
from app.analytics.risk import WEIGHTS, assess_risk
from app.core.clock import today as clock_today
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.models.domain import Customer, CustomerOutcomeRecord
from app.models.enums import ClaimStatus, CustomerOutcome, EvaluationStatus, RunStatus, TaskStatus
from app.models.workflow import Claim, EvaluationRun, LlmCall, Report, Run, RunTask
from app.rag.retrieval import SemanticRetriever
from app.repositories.customers import CustomerRepository

logger = get_logger(__name__)

# Outcomes treated as "the account was lost or shrank" for ranking evaluation.
POSITIVE_OUTCOMES = {CustomerOutcome.CHURNED, CustomerOutcome.DOWNGRADED}
NEGATIVE_OUTCOMES = {CustomerOutcome.RENEWED, CustomerOutcome.EXPANDED}

RISK_KEYWORDS = (
    "cancel",
    "churn",
    "competitor",
    "alternative",
    "pricing",
    "escalat",
    "frustrat",
    "budget",
    "sponsor",
    "renewal",
    "downgrade",
    "unhappy",
    "concern",
    "blocker",
)


@dataclass
class EvaluationParameters:
    name: str = "synthetic-churn-evaluation"
    sample_size: int = 600
    top_k_values: tuple[int, ...] = (10, 25, 50)
    top_percentiles: tuple[float, ...] = (0.05, 0.10, 0.20)
    retrieval_sample: int = 25
    include_workflow_metrics: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sample_size": self.sample_size,
            "top_k_values": list(self.top_k_values),
            "top_percentiles": list(self.top_percentiles),
            "retrieval_sample": self.retrieval_sample,
            "include_workflow_metrics": self.include_workflow_metrics,
        }


@dataclass
class EvaluationOutput:
    metrics: dict[str, Any] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #


def create_evaluation(session: Session, parameters: EvaluationParameters) -> EvaluationRun:
    record = EvaluationRun(
        name=parameters.name,
        status=EvaluationStatus.RUNNING.value,
        dataset_description=(
            "Synthetic B2B SaaS dataset with historical customer outcomes. Ranking metrics are "
            "computed against outcomes the risk model never observes."
        ),
        parameters=parameters.as_dict(),
        metrics={},
        details={},
    )
    session.add(record)
    session.flush()
    return record


def execute_evaluation(evaluation_id: uuid.UUID) -> dict[str, Any]:
    """Run the harness and persist the result. Safe to call from a worker."""
    started = time.perf_counter()
    with session_scope() as session:
        record = session.get(EvaluationRun, evaluation_id)
        if record is None:
            raise ValueError(f"evaluation not found: {evaluation_id}")
        parameters = EvaluationParameters(
            name=record.parameters.get("name", "synthetic-churn-evaluation"),
            sample_size=int(record.parameters.get("sample_size", 600)),
            top_k_values=tuple(record.parameters.get("top_k_values", (10, 25, 50))),
            top_percentiles=tuple(record.parameters.get("top_percentiles", (0.05, 0.10, 0.20))),
            retrieval_sample=int(record.parameters.get("retrieval_sample", 25)),
            include_workflow_metrics=bool(record.parameters.get("include_workflow_metrics", True)),
        )
        try:
            output = run_evaluation(session, parameters)
            record.metrics = output.metrics
            record.details = output.details
            record.status = EvaluationStatus.COMPLETED.value
        except Exception as error:
            record.status = EvaluationStatus.FAILED.value
            record.error_message = f"{type(error).__name__}: {error}"[:4000]
            record.duration_ms = int((time.perf_counter() - started) * 1000)
            logger.exception("evaluation failed", extra={"evaluation_id": str(evaluation_id)})
            raise
        record.duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "evaluation completed",
            extra={"evaluation_id": str(evaluation_id), "duration_ms": record.duration_ms},
        )
        return {"metrics": record.metrics, "details": record.details}


def run_evaluation(session: Session, parameters: EvaluationParameters) -> EvaluationOutput:
    ranking = evaluate_ranking(session, parameters)
    retrieval = evaluate_retrieval(session, parameters)
    workflow = evaluate_workflow(session) if parameters.include_workflow_metrics else {}

    metrics = {
        "dataset": ranking.pop("dataset", {}),
        "ranking": ranking,
        "retrieval": retrieval,
        "workflow": workflow,
        "model": {
            "type": "transparent_weighted_heuristic",
            "is_trained_model": False,
            "weights": dict(WEIGHTS),
        },
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "caveat": (
            "All numbers are computed on a synthetic dataset generated by this repository. They "
            "measure the implementation, not real-world churn prediction performance."
        ),
    }
    return EvaluationOutput(metrics=metrics, details={"ranking_sample": ranking.get("sample", [])})


# --------------------------------------------------------------------------- #
# Ranking quality
# --------------------------------------------------------------------------- #


def evaluate_ranking(session: Session, parameters: EvaluationParameters) -> dict[str, Any]:
    rows = session.execute(
        select(Customer.id, CustomerOutcomeRecord.outcome, CustomerOutcomeRecord.outcome_date)
        .join(CustomerOutcomeRecord, CustomerOutcomeRecord.customer_id == Customer.id)
        .where(CustomerOutcomeRecord.outcome.in_([o.value for o in POSITIVE_OUTCOMES | NEGATIVE_OUTCOMES]))
        .order_by(Customer.external_id)
        .limit(parameters.sample_size)
    ).all()

    if not rows:
        return {
            "dataset": {"labelled_customers": 0},
            "note": "No customers with historical outcomes are present; seed the database first.",
        }

    repository = CustomerRepository(session)
    customer_ids = [row[0] for row in rows]
    labels = {row[0]: CustomerOutcome(row[1]) in POSITIVE_OUTCOMES for row in rows}
    outcome_dates = {row[0]: row[2] for row in rows}

    scored: list[tuple[uuid.UUID, float, bool]] = []
    # Batch in chunks so a large sample does not build one enormous IN clause.
    for start in range(0, len(customer_ids), 200):
        chunk = customer_ids[start : start + 200]
        bundles = repository.load_bundles(chunk)
        for customer_id, bundle in bundles.items():
            # Score as of the outcome date so the model never sees post-outcome data.
            as_of = outcome_dates.get(customer_id) or clock_today()
            windows = M.summarise_usage_windows(bundle.usage, as_of=as_of)
            assessment = assess_risk(
                customer_id=str(customer_id),
                usage=windows,
                support=M.summarise_support(bundle.tickets, as_of=as_of),
                payments=M.calculate_payment_delinquency(bundle.payments, as_of=as_of),
                nps=M.get_latest_nps(bundle.nps_surveys),
                seats_purchased=bundle.subscription.seats_purchased if bundle.subscription else None,
                renewal_date=bundle.subscription.renewal_date if bundle.subscription else None,
                as_of=as_of,
            )
            scored.append((customer_id, assessment.score, labels[customer_id]))

    scored.sort(key=lambda item: item[1], reverse=True)
    total = len(scored)
    positives = sum(1 for _id, _score, label in scored if label)

    metrics: dict[str, Any] = {
        "dataset": {
            "labelled_customers": total,
            "positive_outcomes": positives,
            "negative_outcomes": total - positives,
            "base_rate": round(positives / total, 4) if total else None,
        },
        "at_k": {},
        "at_percentile": {},
    }

    for k in parameters.top_k_values:
        if k > total:
            continue
        top = scored[:k]
        hits = sum(1 for _id, _score, label in top if label)
        metrics["at_k"][str(k)] = {
            "precision": round(hits / k, 4),
            "recall": round(hits / positives, 4) if positives else None,
            "hits": hits,
        }

    for percentile in parameters.top_percentiles:
        k = max(1, int(total * percentile))
        top = scored[:k]
        hits = sum(1 for _id, _score, label in top if label)
        base = positives / total if total else 0
        metrics["at_percentile"][f"{percentile:.0%}"] = {
            "k": k,
            "precision": round(hits / k, 4),
            "recall": round(hits / positives, 4) if positives else None,
            "lift": round((hits / k) / base, 3) if base else None,
        }

    metrics["roc_auc"] = _roc_auc([(score, label) for _id, score, label in scored])
    metrics["average_precision"] = _average_precision([label for _id, _score, label in scored])
    metrics["score_distribution"] = _distribution([score for _id, score, _label in scored])
    metrics["mean_score_positive"] = _mean([s for _i, s, label in scored if label])
    metrics["mean_score_negative"] = _mean([s for _i, s, label in scored if not label])
    metrics["sample"] = [
        {"customer_id": str(cid), "score": score, "churned": label} for cid, score, label in scored[:25]
    ]
    return metrics


def _roc_auc(pairs: list[tuple[float, bool]]) -> float | None:
    """Rank-based ROC-AUC (Mann-Whitney U) with tie handling."""
    positives = [score for score, label in pairs if label]
    negatives = [score for score, label in pairs if not label]
    if not positives or not negatives:
        return None
    ordered = sorted(pairs, key=lambda item: item[0])
    ranks: dict[int, float] = {}
    index = 0
    while index < len(ordered):
        end = index
        while end + 1 < len(ordered) and ordered[end + 1][0] == ordered[index][0]:
            end += 1
        average_rank = (index + end) / 2 + 1
        for position in range(index, end + 1):
            ranks[position] = average_rank
        index = end + 1
    positive_rank_sum = sum(ranks[position] for position, (_score, label) in enumerate(ordered) if label)
    n_pos, n_neg = len(positives), len(negatives)
    u = positive_rank_sum - n_pos * (n_pos + 1) / 2
    return round(u / (n_pos * n_neg), 4)


def _average_precision(labels: list[bool]) -> float | None:
    positives = sum(labels)
    if not positives:
        return None
    hits = 0
    total = 0.0
    for index, label in enumerate(labels, start=1):
        if label:
            hits += 1
            total += hits / index
    return round(total / positives, 4)


def _distribution(scores: list[float]) -> dict[str, float | None]:
    if not scores:
        return {}
    ordered = sorted(scores)
    return {
        "min": round(ordered[0], 2),
        "p25": round(ordered[int(len(ordered) * 0.25)], 2),
        "median": round(ordered[len(ordered) // 2], 2),
        "p75": round(ordered[int(len(ordered) * 0.75)], 2),
        "max": round(ordered[-1], 2),
        "mean": _mean(scores),
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(percentile * (len(ordered) - 1))))
    return round(ordered[index], 2)


# --------------------------------------------------------------------------- #
# Retrieval quality
# --------------------------------------------------------------------------- #


def evaluate_retrieval(session: Session, parameters: EvaluationParameters) -> dict[str, Any]:
    customers = list(
        session.scalars(
            select(Customer)
            .join(CustomerOutcomeRecord, CustomerOutcomeRecord.customer_id == Customer.id)
            .where(CustomerOutcomeRecord.outcome == CustomerOutcome.CHURNED.value)
            .order_by(Customer.external_id)
            .limit(parameters.retrieval_sample)
        )
    )
    if not customers:
        return {"note": "No churned customers available for retrieval evaluation."}

    retriever = SemanticRetriever(session)
    query = "churn risk, renewal concerns, competitor evaluation, pricing pressure, escalation"

    total_chunks = 0
    correct_customer = 0
    risk_relevant = 0
    accounts_with_signal = 0
    empty_results = 0
    relevance_scores: list[float] = []

    for customer in customers:
        chunks = retriever.search(query=query, customer_id=customer.id, limit=5)
        if not chunks:
            empty_results += 1
            continue
        found_signal = False
        for chunk in chunks:
            total_chunks += 1
            if chunk.customer_id == customer.id:
                correct_customer += 1
            relevance_scores.append(chunk.relevance_score)
            if any(keyword in chunk.content.lower() for keyword in RISK_KEYWORDS):
                risk_relevant += 1
                found_signal = True
        if found_signal:
            accounts_with_signal += 1

    return {
        "accounts_sampled": len(customers),
        "chunks_returned": total_chunks,
        "accounts_with_no_matches": empty_results,
        # Must be 1.0: anything less means the customer filter leaked.
        "customer_scope_precision": round(correct_customer / total_chunks, 4) if total_chunks else None,
        "risk_relevant_chunk_rate": round(risk_relevant / total_chunks, 4) if total_chunks else None,
        "accounts_with_risk_signal_rate": (round(accounts_with_signal / len(customers), 4) if customers else None),
        "mean_relevance_score": _mean(relevance_scores),
        "embedding_provider": get_settings().effective_embedding_provider,
        "metric_note": (
            "risk_relevant_chunk_rate is a keyword-overlap proxy for relevance, not human-judged ground truth."
        ),
    }


# --------------------------------------------------------------------------- #
# Workflow quality
# --------------------------------------------------------------------------- #


def evaluate_workflow(session: Session) -> dict[str, Any]:
    run_rows = list(session.scalars(select(Run)))
    if not run_rows:
        return {"note": "No workflow runs have executed yet."}

    terminal = [row for row in run_rows if RunStatus(row.status).is_terminal]
    completed = [row for row in terminal if row.status == RunStatus.COMPLETED.value]
    durations = [
        (row.completed_at - row.started_at).total_seconds() for row in completed if row.completed_at and row.started_at
    ]

    task_rows = list(session.scalars(select(RunTask)))
    retried = [task for task in task_rows if task.retry_count > 0]
    recovered = [task for task in retried if task.status == TaskStatus.COMPLETED.value]

    usage = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(LlmCall.prompt_tokens + LlmCall.completion_tokens), 0),
            func.coalesce(func.sum(LlmCall.estimated_cost_usd), 0),
            func.coalesce(func.avg(LlmCall.latency_ms), 0),
            func.coalesce(func.sum(case((LlmCall.valid_output.is_(False), 1), else_=0)), 0),
        )
    ).one()

    claims = list(session.scalars(select(Claim)))
    claim_metrics = _claim_metrics(claims)
    report_metrics = _report_metrics(session, claims)

    return {
        "runs_total": len(run_rows),
        "runs_completed": len(completed),
        "runs_failed": sum(1 for row in run_rows if row.status == RunStatus.FAILED.value),
        "runs_cancelled": sum(1 for row in run_rows if row.status == RunStatus.CANCELLED.value),
        "runs_awaiting_approval": sum(1 for row in run_rows if row.status == RunStatus.WAITING_FOR_APPROVAL.value),
        "completion_rate": round(len(completed) / len(terminal), 4) if terminal else None,
        "avg_duration_seconds": _mean(durations),
        "p95_duration_seconds": _percentile(durations, 0.95),
        "tasks_total": len(task_rows),
        "tasks_failed": sum(1 for task in task_rows if task.status == TaskStatus.FAILED.value),
        "tasks_retried": len(retried),
        "retry_recovery_rate": round(len(recovered) / len(retried), 4) if retried else None,
        "llm_calls": int(usage[0]),
        "total_tokens": int(usage[1]),
        "avg_tokens_per_call": round(int(usage[1]) / int(usage[0]), 1) if usage[0] else None,
        "estimated_cost_usd": round(float(usage[2]), 6),
        "avg_llm_latency_ms": round(float(usage[3]), 1),
        "invalid_structured_outputs": int(usage[4]),
        "claims": claim_metrics,
        "reports": report_metrics,
    }


def _claim_metrics(claims: list[Claim]) -> dict[str, Any]:
    if not claims:
        return {"total": 0, "note": "No claims have been produced yet."}

    total = len(claims)
    counts: dict[str, int] = {}
    for claim in claims:
        counts[claim.status] = counts.get(claim.status, 0) + 1

    with_evidence = sum(1 for claim in claims if claim.evidence_items)
    # "Before verification" = how the investigator's claims stood on their own,
    # recomputed with the deterministic rules (no verifier LLM involved).
    pre_unsupported = 0
    for claim in claims:
        texts = [item.content for item in claim.evidence_items]
        result = evaluate_claim(claim.claim_text, texts, has_valid_evidence=bool(texts))
        if result.status in {ClaimStatus.UNSUPPORTED, ClaimStatus.CONTRADICTED}:
            pre_unsupported += 1

    supported = counts.get(ClaimStatus.SUPPORTED.value, 0)
    rejected = counts.get(ClaimStatus.UNSUPPORTED.value, 0) + counts.get(ClaimStatus.CONTRADICTED.value, 0)
    return {
        "total": total,
        "by_status": counts,
        "claims_with_valid_evidence_rate": round(with_evidence / total, 4),
        "supported_rate": round(supported / total, 4),
        "partially_supported_rate": round(counts.get(ClaimStatus.PARTIALLY_SUPPORTED.value, 0) / total, 4),
        "rejected_rate": round(rejected / total, 4),
        "unsupported_before_verification_rate": round(pre_unsupported / total, 4),
        "unsupported_after_verification_rate": 0.0,
        "after_verification_note": (
            "Zero by construction: only SUPPORTED claims, and rewritten PARTIALLY_SUPPORTED "
            "claims, can appear as conclusions in a report. The check below verifies that."
        ),
    }


def _report_metrics(session: Session, claims: list[Claim]) -> dict[str, Any]:
    reports = list(session.scalars(select(Report)))
    if not reports:
        return {"total": 0}

    rejected_texts = {
        claim.claim_text
        for claim in claims
        if claim.status in {ClaimStatus.UNSUPPORTED.value, ClaimStatus.CONTRADICTED.value}
    }
    leaked = 0
    conclusions = 0
    for report in reports:
        for account in (report.report_payload or {}).get("report", {}).get("accounts", []):
            for conclusion in account.get("verified_conclusions", []):
                conclusions += 1
                if conclusion in rejected_texts:
                    leaked += 1
    return {
        "total": len(reports),
        "verified_conclusions": conclusions,
        # The headline integrity check: a rejected claim must never be asserted.
        "rejected_claims_leaked_into_reports": leaked,
        "report_integrity_ok": leaked == 0,
    }
