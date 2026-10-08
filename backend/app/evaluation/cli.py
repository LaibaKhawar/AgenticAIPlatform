"""Evaluation CLI: ``python -m app.evaluation.cli``.

Runs the harness, persists the result, and prints a human-readable summary
alongside the full JSON so the numbers can be pasted into a README or diffed
between commits.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.core.logging import configure_logging
from app.db.session import session_scope
from app.evaluation.runner import EvaluationParameters, create_evaluation, execute_evaluation


def _line(label: str, value: Any, unit: str = "") -> str:
    if value is None:
        return f"  {label:<38} n/a"
    if isinstance(value, float):
        return f"  {label:<38} {value:.4g}{unit}"
    return f"  {label:<38} {value}{unit}"


def summarise(metrics: dict[str, Any]) -> str:
    ranking = metrics.get("ranking", {})
    retrieval = metrics.get("retrieval", {})
    workflow = metrics.get("workflow", {})
    dataset = metrics.get("dataset", {})
    claims = workflow.get("claims", {}) or {}
    reports = workflow.get("reports", {}) or {}

    out: list[str] = ["", "RANKING QUALITY (synthetic dataset, historical outcomes held out)"]
    out.append(_line("labelled customers", dataset.get("labelled_customers")))
    out.append(_line("churn base rate", dataset.get("base_rate")))
    out.append(_line("ROC-AUC", ranking.get("roc_auc")))
    out.append(_line("average precision", ranking.get("average_precision")))
    out.append(_line("mean score (churned)", ranking.get("mean_score_positive")))
    out.append(_line("mean score (renewed)", ranking.get("mean_score_negative")))
    for k, value in (ranking.get("at_k") or {}).items():
        out.append(_line(f"precision@{k}", value.get("precision")))
        out.append(_line(f"recall@{k}", value.get("recall")))
    for percentile, value in (ranking.get("at_percentile") or {}).items():
        out.append(_line(f"lift @ top {percentile}", value.get("lift"), "x"))
    if ranking.get("note"):
        out.append(f"  note: {ranking['note']}")

    out += ["", "RETRIEVAL QUALITY"]
    if retrieval.get("note"):
        out.append(f"  note: {retrieval['note']}")
    else:
        out.append(_line("customer scope precision", retrieval.get("customer_scope_precision")))
        out.append(_line("risk-relevant chunk rate", retrieval.get("risk_relevant_chunk_rate")))
        out.append(_line("accounts with a risk signal", retrieval.get("accounts_with_risk_signal_rate")))
        out.append(_line("mean cosine relevance", retrieval.get("mean_relevance_score")))
        out.append(_line("embedding provider", retrieval.get("embedding_provider")))

    out += ["", "WORKFLOW QUALITY"]
    if workflow.get("note"):
        out.append(f"  note: {workflow['note']}")
    else:
        out.append(_line("runs completed / total", f"{workflow.get('runs_completed')} / {workflow.get('runs_total')}"))
        out.append(_line("completion rate", workflow.get("completion_rate")))
        out.append(_line("avg run duration (s)", workflow.get("avg_duration_seconds")))
        out.append(_line("P95 run duration (s)", workflow.get("p95_duration_seconds")))
        out.append(_line("tasks retried", workflow.get("tasks_retried")))
        out.append(_line("retry recovery rate", workflow.get("retry_recovery_rate")))
        out.append(_line("llm calls", workflow.get("llm_calls")))
        out.append(_line("avg tokens per call", workflow.get("avg_tokens_per_call")))
        out.append(_line("estimated cost (USD)", workflow.get("estimated_cost_usd")))
        out.append(_line("invalid structured outputs", workflow.get("invalid_structured_outputs")))
        out += ["", "CLAIM VERIFICATION"]
        out.append(_line("material claims", claims.get("total")))
        out.append(_line("claims with valid evidence", claims.get("claims_with_valid_evidence_rate")))
        out.append(_line("supported", claims.get("supported_rate")))
        out.append(_line("partially supported", claims.get("partially_supported_rate")))
        out.append(_line("rejected", claims.get("rejected_rate")))
        out.append(_line("unsupported BEFORE verification", claims.get("unsupported_before_verification_rate")))
        out.append(_line("unsupported AFTER verification", claims.get("unsupported_after_verification_rate")))
        out.append(_line("rejected claims leaked into reports", reports.get("rejected_claims_leaked_into_reports")))
        out.append(_line("report integrity ok", reports.get("report_integrity_ok")))

    out += ["", f"  {metrics.get('caveat', '')}", ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Run the Veriflow evaluation harness.")
    parser.add_argument("--name", default="cli-evaluation")
    parser.add_argument("--sample-size", type=int, default=800)
    parser.add_argument("--retrieval-sample", type=int, default=25)
    parser.add_argument("--json", action="store_true", help="print only the JSON metrics")
    arguments = parser.parse_args(argv)

    parameters = EvaluationParameters(
        name=arguments.name,
        sample_size=arguments.sample_size,
        retrieval_sample=arguments.retrieval_sample,
    )

    with session_scope() as session:
        record = create_evaluation(session, parameters)
        evaluation_id = record.id

    result = execute_evaluation(evaluation_id)
    metrics = result["metrics"]

    if arguments.json:
        print(json.dumps(metrics, indent=2, default=str))
        return 0

    print(f"Evaluation {evaluation_id}", file=sys.stderr)
    print(summarise(metrics))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
