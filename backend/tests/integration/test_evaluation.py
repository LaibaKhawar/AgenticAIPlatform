"""Evaluation harness: real metrics computed from the real dataset."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.evaluation.runner import (
    EvaluationParameters,
    _average_precision,
    _roc_auc,
    create_evaluation,
    evaluate_ranking,
    evaluate_retrieval,
    evaluate_workflow,
    execute_evaluation,
    run_evaluation,
)
from app.models.enums import EvaluationStatus

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# Metric primitives
# --------------------------------------------------------------------------- #


def test_roc_auc_of_a_perfect_ranker_is_one() -> None:
    assert _roc_auc([(0.9, True), (0.8, True), (0.2, False), (0.1, False)]) == pytest.approx(1.0)


def test_roc_auc_of_an_inverted_ranker_is_zero() -> None:
    assert _roc_auc([(0.9, False), (0.8, False), (0.2, True), (0.1, True)]) == pytest.approx(0.0)


def test_roc_auc_of_pure_ties_is_a_coin_flip() -> None:
    assert _roc_auc([(0.5, True), (0.5, False), (0.5, True), (0.5, False)]) == pytest.approx(0.5)


def test_roc_auc_is_undefined_without_both_classes() -> None:
    assert _roc_auc([(0.9, True), (0.8, True)]) is None
    assert _roc_auc([]) is None


def test_average_precision_rewards_early_hits() -> None:
    early = _average_precision([True, True, False, False])
    late = _average_precision([False, False, True, True])
    assert early > late
    assert early == pytest.approx(1.0)


def test_average_precision_is_undefined_with_no_positives() -> None:
    assert _average_precision([False, False]) is None


# --------------------------------------------------------------------------- #
# Ranking evaluation
# --------------------------------------------------------------------------- #


def test_ranking_evaluation_reports_a_real_signal(seeded_small: dict, db: Session) -> None:
    metrics = evaluate_ranking(db, EvaluationParameters(sample_size=200))

    dataset = metrics["dataset"]
    assert dataset["labelled_customers"] > 0
    assert dataset["positive_outcomes"] > 0
    assert dataset["negative_outcomes"] > 0
    assert 0 < dataset["base_rate"] < 1

    assert metrics["roc_auc"] is not None
    assert 0.0 <= metrics["roc_auc"] <= 1.0
    # The heuristic must beat chance on its own synthetic data, or the model is
    # not doing anything and the whole screening stage is decoration.
    assert metrics["roc_auc"] > 0.5

    assert metrics["mean_score_positive"] > metrics["mean_score_negative"]
    assert metrics["score_distribution"]["max"] <= 100
    assert metrics["sample"]


def test_precision_at_k_beats_the_base_rate(seeded_small: dict, db: Session) -> None:
    metrics = evaluate_ranking(db, EvaluationParameters(sample_size=200, top_k_values=(10, 25)))
    base_rate = metrics["dataset"]["base_rate"]
    for entry in metrics["at_k"].values():
        assert 0.0 <= entry["precision"] <= 1.0
        assert 0.0 <= entry["recall"] <= 1.0
    assert metrics["at_k"]["10"]["precision"] > base_rate


def test_lift_is_reported_per_percentile(seeded_small: dict, db: Session) -> None:
    metrics = evaluate_ranking(db, EvaluationParameters(sample_size=200))
    for bucket in metrics["at_percentile"].values():
        assert bucket["k"] >= 1
        assert bucket["lift"] is not None


def test_ranking_evaluation_on_an_empty_database_explains_itself(db: Session) -> None:
    """No fabricated numbers when there is no data."""
    metrics = evaluate_ranking(db, EvaluationParameters())
    assert metrics["dataset"]["labelled_customers"] == 0
    assert "seed the database" in metrics["note"]


def test_ranking_respects_the_sample_size(seeded_small: dict, db: Session) -> None:
    metrics = evaluate_ranking(db, EvaluationParameters(sample_size=5))
    assert metrics["dataset"]["labelled_customers"] <= 5


# --------------------------------------------------------------------------- #
# Retrieval evaluation
# --------------------------------------------------------------------------- #


def test_retrieval_evaluation_proves_customer_scoping(seeded_small: dict, db: Session) -> None:
    metrics = evaluate_retrieval(db, EvaluationParameters(retrieval_sample=8))
    if metrics.get("note"):
        pytest.skip(metrics["note"])

    assert metrics["accounts_sampled"] > 0
    assert metrics["chunks_returned"] > 0
    # Anything below 1.0 means the customer filter leaked another account's data.
    assert metrics["customer_scope_precision"] == pytest.approx(1.0)
    assert 0.0 <= metrics["risk_relevant_chunk_rate"] <= 1.0
    assert metrics["embedding_provider"] == "local"
    assert metrics["metric_note"]


def test_retrieval_evaluation_on_an_empty_database_explains_itself(db: Session) -> None:
    metrics = evaluate_retrieval(db, EvaluationParameters())
    assert "note" in metrics


# --------------------------------------------------------------------------- #
# Workflow evaluation
# --------------------------------------------------------------------------- #


def test_workflow_evaluation_with_no_runs_explains_itself(db: Session) -> None:
    assert "note" in evaluate_workflow(db)


def test_workflow_evaluation_measures_a_real_run(
    seeded_small: dict, api_client: Any, inline_engine: Any
) -> None:
    response = api_client.post(
        "/api/v1/runs",
        json={
            "objective": (
                "Analyze enterprise customers renewing within the next 90 days, identify churn "
                "risk, verify the evidence and report."
            ),
            "max_accounts": 1,
        },
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    for approval in api_client.get(f"/api/v1/approvals?run_id={run_id}").json()["items"]:
        api_client.post(f"/api/v1/approvals/{approval['id']}/approve", json={})

    with session_scope() as session:
        metrics = evaluate_workflow(session)

    assert metrics["runs_total"] == 1
    assert metrics["runs_completed"] == 1
    assert metrics["completion_rate"] == pytest.approx(1.0)
    assert metrics["avg_duration_seconds"] is not None
    assert metrics["p95_duration_seconds"] is not None
    assert metrics["tasks_total"] > 0
    assert metrics["llm_calls"] > 0
    assert metrics["total_tokens"] > 0
    assert metrics["avg_tokens_per_call"] > 0
    assert metrics["estimated_cost_usd"] >= 0
    assert metrics["invalid_structured_outputs"] == 0

    claims = metrics["claims"]
    assert claims["total"] > 0
    assert claims["claims_with_valid_evidence_rate"] > 0
    assert 0.0 <= claims["supported_rate"] <= 1.0
    assert claims["unsupported_before_verification_rate"] >= 0.0
    assert claims["unsupported_after_verification_rate"] == 0.0

    # The headline integrity check: no rejected claim is asserted in a report.
    reports = metrics["reports"]
    assert reports["total"] == 1
    assert reports["verified_conclusions"] > 0
    assert reports["rejected_claims_leaked_into_reports"] == 0
    assert reports["report_integrity_ok"] is True


# --------------------------------------------------------------------------- #
# Persistence and API
# --------------------------------------------------------------------------- #


def test_evaluation_run_is_persisted_with_its_metrics(seeded_small: dict, db: Session) -> None:
    record = create_evaluation(db, EvaluationParameters(name="unit-eval", sample_size=60, retrieval_sample=3))
    evaluation_id = record.id
    assert record.status == EvaluationStatus.RUNNING.value
    db.commit()

    execute_evaluation(evaluation_id)

    with session_scope() as session:
        from app.models.workflow import EvaluationRun

        stored = session.get(EvaluationRun, evaluation_id)
        assert stored.status == EvaluationStatus.COMPLETED.value
        assert stored.duration_ms is not None
        assert stored.metrics["ranking"]
        assert stored.metrics["model"]["is_trained_model"] is False
        assert "synthetic" in stored.metrics["caveat"].lower()
        assert stored.error_message is None


def test_full_evaluation_report_labels_itself_as_synthetic(seeded_small: dict, db: Session) -> None:
    output = run_evaluation(db, EvaluationParameters(sample_size=80, retrieval_sample=3))
    assert set(output.metrics) >= {"dataset", "ranking", "retrieval", "workflow", "model", "caveat"}
    assert "synthetic" in output.metrics["caveat"].lower()
    assert output.metrics["model"]["weights"]


def test_evaluation_endpoint_runs_and_returns_metrics(seeded_small: dict, api_client: Any) -> None:
    response = api_client.post(
        "/api/v1/evaluations/run",
        json={"name": "api-eval", "sample_size": 60, "retrieval_sample": 3},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["metrics"]["ranking"]["roc_auc"] is not None
    assert body["duration_ms"] is not None

    fetched = api_client.get(f"/api/v1/evaluations/{body['id']}").json()
    assert fetched["id"] == body["id"]

    listed = api_client.get("/api/v1/evaluations").json()
    assert listed["total"] == 1

    latest = api_client.get("/api/v1/evaluations/latest").json()
    assert latest["id"] == body["id"]


def test_latest_evaluation_is_null_before_any_run(api_client: Any) -> None:
    assert api_client.get("/api/v1/evaluations/latest").json() is None


def test_evaluation_request_validates_its_bounds(api_client: Any) -> None:
    assert api_client.post("/api/v1/evaluations/run", json={"sample_size": 1}).status_code == 422
    assert api_client.post("/api/v1/evaluations/run", json={"sample_size": 999_999}).status_code == 422
    assert api_client.post("/api/v1/evaluations/run", json={"retrieval_sample": 0}).status_code == 422
