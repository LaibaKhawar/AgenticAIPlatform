"""HTTP API behaviour: contracts, pagination, errors and auth boundary."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.config import get_settings

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# Health and system
# --------------------------------------------------------------------------- #


def test_health_reports_every_dependency(api_client: Any) -> None:
    response = api_client.get("/health")
    body = response.json()
    assert response.status_code in (200, 503)
    assert body["database"] == "ok"
    assert body["pgvector"] is True
    assert body["llm_provider"] == "fake"
    assert body["embedding_provider"] == "local"
    assert body["failure_injection"] is False
    assert set(body["checks"]) >= {"database", "pgvector", "redis", "executor"}


def test_liveness_does_not_touch_the_database(api_client: Any) -> None:
    response = api_client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_requires_the_database(api_client: Any) -> None:
    response = api_client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_openapi_document_is_valid_and_complete(api_client: Any) -> None:
    response = api_client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    required = {
        "/health",
        "/api/v1/customers",
        "/api/v1/customers/{customer_id}",
        "/api/v1/customers/{customer_id}/usage",
        "/api/v1/customers/{customer_id}/documents",
        "/api/v1/customers/{customer_id}/risk",
        "/api/v1/runs",
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/cancel",
        "/api/v1/runs/{run_id}/tasks",
        "/api/v1/runs/{run_id}/investigations",
        "/api/v1/runs/{run_id}/claims",
        "/api/v1/runs/{run_id}/evidence",
        "/api/v1/runs/{run_id}/report",
        "/api/v1/approvals",
        "/api/v1/approvals/{approval_id}/approve",
        "/api/v1/approvals/{approval_id}/reject",
        "/api/v1/evaluations/run",
        "/api/v1/evaluations/{evaluation_id}",
    }
    missing = required - set(spec["paths"])
    assert not missing, f"OpenAPI is missing: {sorted(missing)}"


def test_docs_are_served(api_client: Any) -> None:
    assert api_client.get("/docs").status_code == 200


def test_system_endpoint_describes_real_capabilities(api_client: Any) -> None:
    body = api_client.get("/api/v1/system").json()
    assert body["product"]
    agent_names = {agent["name"] for agent in body["agents"]}
    assert {"planner", "data", "risk", "retrieval", "investigator", "verifier", "reporter"} <= agent_names
    tool_names = {tool["name"] for tool in body["tools"]}
    assert "get_risk_signals" in tool_names
    assert body["risk_model"]["is_trained_model"] is False
    assert body["limits"]["max_parallel_investigations"] >= 1
    assert any(entry["requires_approval"] for entry in body["approval_policy"])


def test_root_endpoint_points_at_the_docs(api_client: Any) -> None:
    body = api_client.get("/").json()
    assert body["docs"] == "/docs"


# --------------------------------------------------------------------------- #
# Auth boundary
# --------------------------------------------------------------------------- #


def test_api_is_open_when_no_key_is_configured(api_client: Any) -> None:
    assert get_settings().api_key is None
    assert api_client.get("/api/v1/customers?limit=1").status_code == 200


def test_configured_api_key_is_enforced(api_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "api_key", "s3cret")

    assert api_client.get("/api/v1/customers?limit=1").status_code == 401
    assert api_client.get("/api/v1/customers?limit=1", headers={"X-API-Key": "wrong"}).status_code == 401
    assert api_client.get("/api/v1/customers?limit=1", headers={"X-API-Key": "s3cret"}).status_code == 200
    # Health stays public so orchestrators can probe it.
    assert api_client.get("/health/live").status_code == 200


# --------------------------------------------------------------------------- #
# Customers
# --------------------------------------------------------------------------- #


def test_customer_list_is_paginated(seeded_small: dict, api_client: Any) -> None:
    body = api_client.get("/api/v1/customers?limit=5&offset=0").json()
    assert body["total"] == 40
    assert len(body["items"]) == 5
    assert body["limit"] == 5

    second = api_client.get("/api/v1/customers?limit=5&offset=5").json()
    assert {c["id"] for c in body["items"]}.isdisjoint({c["id"] for c in second["items"]})


def test_pagination_boundaries_are_validated(seeded_small: dict, api_client: Any) -> None:
    assert api_client.get("/api/v1/customers?limit=0").status_code == 422
    assert api_client.get("/api/v1/customers?limit=-1").status_code == 422
    assert api_client.get("/api/v1/customers?offset=-1").status_code == 422
    assert api_client.get("/api/v1/customers?limit=99999").status_code == 422


def test_page_size_is_capped_to_the_configured_maximum(seeded_small: dict, api_client: Any) -> None:
    body = api_client.get("/api/v1/customers?limit=500").json()
    assert body["limit"] == get_settings().api_max_page_size


def test_offset_past_the_end_returns_an_empty_page(seeded_small: dict, api_client: Any) -> None:
    body = api_client.get("/api/v1/customers?limit=10&offset=9999").json()
    assert body["items"] == []
    assert body["total"] == 40


def test_empty_database_returns_an_empty_page_not_an_error(api_client: Any) -> None:
    body = api_client.get("/api/v1/customers").json()
    assert body == {"items": [], "total": 0, "limit": 25, "offset": 0}


def test_customer_filters_are_applied(seeded_small: dict, api_client: Any) -> None:
    body = api_client.get("/api/v1/customers?account_tier=ENTERPRISE&limit=100").json()
    assert body["items"]
    assert all(c["account_tier"] == "ENTERPRISE" for c in body["items"])


def test_invalid_enum_filter_is_rejected_with_a_useful_error(seeded_small: dict, api_client: Any) -> None:
    response = api_client.get("/api/v1/customers?account_tier=PLATINUM")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"]["problems"]


def test_customer_detail_aggregates_everything_a_reviewer_needs(
    seeded_small: dict, api_client: Any
) -> None:
    body = api_client.get("/api/v1/customers/CUST-000001").json()

    assert body["customer"]["company_name"] == "Acme Corp"
    assert body["customer"]["account_tier"] == "ENTERPRISE"
    assert body["customer"]["subscription"]["monthly_recurring_revenue"] == pytest.approx(8200.0)
    assert body["customer"]["subscription"]["days_to_renewal"] is not None

    assert body["usage"], "usage series must be present"
    assert body["usage_summary"]["active_user_change_pct"] < 0
    assert body["support_summary"]["recent_ticket_count"] > body["support_summary"]["baseline_ticket_count"]
    assert body["payment_summary"]["max_days_overdue"] > 0
    assert body["nps_summary"]["latest_score"] == 3
    assert body["nps_summary"]["score_delta"] == -5
    assert body["documents"]
    assert body["risk"]["risk_level"] in {"HIGH", "CRITICAL"}
    assert body["risk"]["signals"]


def test_customer_detail_accepts_a_uuid(seeded_small: dict, api_client: Any) -> None:
    listed = api_client.get("/api/v1/customers?limit=1").json()["items"][0]
    assert api_client.get(f"/api/v1/customers/{listed['id']}").status_code == 200


def test_unknown_customer_returns_404_with_a_structured_error(api_client: Any) -> None:
    response = api_client.get("/api/v1/customers/CUST-999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_malformed_customer_identifier_returns_404_not_500(api_client: Any) -> None:
    response = api_client.get("/api/v1/customers/not-a-valid-uuid-or-id")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_usage_endpoint_returns_an_ordered_series(seeded_small: dict, api_client: Any) -> None:
    rows = api_client.get("/api/v1/customers/CUST-000001/usage?days=180").json()
    assert rows
    dates = [row["usage_date"] for row in rows]
    assert dates == sorted(dates)
    assert all(row["active_users"] >= 0 for row in rows)


def test_usage_window_is_validated(seeded_small: dict, api_client: Any) -> None:
    assert api_client.get("/api/v1/customers/CUST-000001/usage?days=1").status_code == 422
    assert api_client.get("/api/v1/customers/CUST-000001/usage?days=99999").status_code == 422


def test_documents_endpoint_paginates(seeded_small: dict, api_client: Any) -> None:
    body = api_client.get("/api/v1/customers/CUST-000001/documents?limit=2").json()
    assert body["total"] >= 1
    assert len(body["items"]) <= 2
    assert body["items"][0]["source_type"]
    assert body["items"][0]["chars"] > 0


def test_document_detail_marks_content_as_untrusted(seeded_small: dict, api_client: Any) -> None:
    documents = api_client.get("/api/v1/customers/CUST-000001/documents").json()["items"]
    document_id = documents[0]["id"]
    body = api_client.get(f"/api/v1/customers/CUST-000001/documents/{document_id}").json()
    assert body["content"]
    assert body["metadata"]["content_is_untrusted"] is True
    assert "injection_detections" in body["metadata"]


def test_document_from_another_customer_is_not_accessible(seeded_small: dict, api_client: Any) -> None:
    """Cross-customer document access must 404, not leak."""
    other = api_client.get("/api/v1/customers?limit=5").json()["items"]
    foreign = next(c for c in other if c["external_id"] != "CUST-000001")
    foreign_docs = api_client.get(f"/api/v1/customers/{foreign['external_id']}/documents").json()["items"]
    if not foreign_docs:
        pytest.skip("the chosen customer has no documents")
    response = api_client.get(f"/api/v1/customers/CUST-000001/documents/{foreign_docs[0]['id']}")
    assert response.status_code == 404


def test_unknown_document_id_returns_404(seeded_small: dict, api_client: Any) -> None:
    assert api_client.get(f"/api/v1/customers/CUST-000001/documents/{uuid.uuid4()}").status_code == 404
    assert api_client.get("/api/v1/customers/CUST-000001/documents/garbage").status_code == 404


def test_risk_endpoint_exposes_the_signal_breakdown_and_model_card(
    seeded_small: dict, api_client: Any
) -> None:
    body = api_client.get("/api/v1/customers/CUST-000001/risk").json()
    assert body["heuristic_risk_score"] > 60
    assert body["risk_level"] in {"HIGH", "CRITICAL"}
    assert body["days_to_renewal"] is not None
    assert body["model"]["is_trained_model"] is False

    keys = {signal["key"] for signal in body["signals"]}
    assert {"active_user_decline", "support_pressure", "payment_delinquency", "nps"} <= keys
    for signal in body["signals"]:
        assert signal["detail"], "every signal must explain itself"
        assert 0.0 <= signal["severity"] <= 1.0


def test_industries_endpoint_returns_distinct_values(seeded_small: dict, api_client: Any) -> None:
    industries = api_client.get("/api/v1/customers/industries").json()
    assert industries == sorted(set(industries))


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #


def test_dashboard_on_an_empty_system_reports_zeros_and_nulls(api_client: Any) -> None:
    """No fake metrics: with nothing to show, the API says so."""
    body = api_client.get("/api/v1/dashboard").json()
    assert body["runs_total"] == 0
    assert body["investigations_completed"] == 0
    assert body["pending_approvals"] == 0
    assert body["verified_claim_pct"] is None
    assert body["avg_run_duration_seconds"] is None
    assert body["recent_runs"] == []
    assert body["high_risk_accounts"] == []


def test_dashboard_reflects_the_seeded_dataset(seeded_small: dict, api_client: Any) -> None:
    body = api_client.get("/api/v1/dashboard").json()
    assert body["total_customers"] == 40
    assert body["embedded_chunks"] > 0
    assert body["dataset"]["outcomes"]
    assert body["llm_usage"]["provider"] == "fake"


# --------------------------------------------------------------------------- #
# Run creation contract
# --------------------------------------------------------------------------- #


OBJECTIVE = (
    "Analyze enterprise customers renewing within the next 90 days. Identify the five accounts at "
    "highest risk of churn, investigate each one, verify the evidence, and create a report."
)


def test_create_run_returns_202_immediately(seeded_small: dict, api_client: Any) -> None:
    response = api_client.post("/api/v1/runs", json={"objective": OBJECTIVE})
    assert response.status_code == 202
    body = response.json()
    assert uuid.UUID(body["run_id"])
    assert body["status"] in {"QUEUED", "RUNNING", "WAITING_FOR_APPROVAL", "COMPLETED"}
    assert body["parameters"]["renewal_window_days"] == 90
    assert body["parameters"]["max_accounts"] == 5


def test_objective_length_is_validated(api_client: Any) -> None:
    assert api_client.post("/api/v1/runs", json={"objective": "too short"}).status_code == 422
    assert api_client.post("/api/v1/runs", json={"objective": "x" * 5000}).status_code == 422


def test_objective_is_required(api_client: Any) -> None:
    response = api_client.post("/api/v1/runs", json={})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["problems"]


def test_out_of_scope_objective_is_refused_with_an_explanation(api_client: Any) -> None:
    response = api_client.post(
        "/api/v1/runs",
        json={"objective": "Summarise our AWS bill and tell me how to reduce storage costs this quarter."},
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "unsupported_objective"
    assert "churn" in error["message"].lower()


def test_structured_controls_override_the_objective_text(seeded_small: dict, api_client: Any) -> None:
    response = api_client.post(
        "/api/v1/runs",
        json={
            "objective": OBJECTIVE,
            "renewal_window_days": 120,
            "max_accounts": 2,
            "account_tier": "ENTERPRISE",
            "workflow_mode": "REVIEW_ALL",
        },
    )
    assert response.status_code == 202
    parameters = response.json()["parameters"]
    assert parameters["renewal_window_days"] == 120
    assert parameters["max_accounts"] == 2
    assert parameters["account_tier"] == "ENTERPRISE"
    assert parameters["workflow_mode"] == "REVIEW_ALL"


def test_invalid_control_values_are_rejected(api_client: Any) -> None:
    for payload in (
        {"objective": OBJECTIVE, "renewal_window_days": 0},
        {"objective": OBJECTIVE, "renewal_window_days": 10_000},
        {"objective": OBJECTIVE, "max_accounts": 0},
        {"objective": OBJECTIVE, "max_accounts": 999},
        {"objective": OBJECTIVE, "workflow_mode": "YOLO"},
        {"objective": OBJECTIVE, "risk_threshold": 500},
    ):
        assert api_client.post("/api/v1/runs", json=payload).status_code == 422, payload


def test_oversized_request_body_is_rejected(api_client: Any) -> None:
    response = api_client.post(
        "/api/v1/runs",
        content=b'{"objective": "' + b"x" * 400_000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


# --------------------------------------------------------------------------- #
# Run reads and error cases
# --------------------------------------------------------------------------- #


def test_unknown_run_returns_404(api_client: Any) -> None:
    assert api_client.get(f"/api/v1/runs/{uuid.uuid4()}").status_code == 404


def test_malformed_run_id_returns_404_not_500(api_client: Any) -> None:
    response = api_client.get("/api/v1/runs/not-a-uuid")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_run_list_is_empty_before_any_run(api_client: Any) -> None:
    body = api_client.get("/api/v1/runs").json()
    assert body == {"items": [], "total": 0, "limit": 25, "offset": 0}


def test_report_requested_before_completion_returns_409(api_client: Any, seeded_small: dict) -> None:
    """Asking for a report too early is a conflict with a clear reason, not a 404
    and not an empty 200."""
    from app.db.session import session_scope
    from app.models.enums import WorkflowType
    from app.repositories.runs import RunRepository

    with session_scope() as session:
        run = RunRepository(session).create_run(
            objective=OBJECTIVE,
            workflow_type=WorkflowType.CHURN_INVESTIGATION,
            workflow_mode="STANDARD",
            created_by="tester",
            metadata={},
        )
        run_id = run.id

    response = api_client.get(f"/api/v1/runs/{run_id}/report")
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "report_not_ready"
    assert error["details"]["run_status"] == "QUEUED"


def test_cancelling_an_unknown_run_returns_404(api_client: Any) -> None:
    assert api_client.post(f"/api/v1/runs/{uuid.uuid4()}/cancel").status_code == 404


def test_approvals_list_is_empty_and_paginated(api_client: Any) -> None:
    body = api_client.get("/api/v1/approvals").json()
    assert body["items"] == []
    assert body["total"] == 0


def test_unknown_approval_returns_404(api_client: Any) -> None:
    assert api_client.get(f"/api/v1/approvals/{uuid.uuid4()}").status_code == 404
    assert api_client.post(f"/api/v1/approvals/{uuid.uuid4()}/approve", json={}).status_code == 404


def test_reports_list_is_empty_before_any_run(api_client: Any) -> None:
    assert api_client.get("/api/v1/reports").json()["total"] == 0


def test_unknown_report_returns_404(api_client: Any) -> None:
    assert api_client.get(f"/api/v1/reports/{uuid.uuid4()}").status_code == 404


def test_every_response_carries_a_request_id(api_client: Any) -> None:
    response = api_client.get("/health/live")
    assert response.headers["X-Request-ID"]


def test_supplied_request_id_is_echoed(api_client: Any) -> None:
    response = api_client.get("/health/live", headers={"X-Request-ID": "trace-me"})
    assert response.headers["X-Request-ID"] == "trace-me"


def test_application_shutdown_does_not_redirect_the_engine(engine: Any) -> None:
    """Regression: the lifespan's `dispose_engine()` used to unpin the database.

    The engine is a process global. When the app is embedded in a TestClient,
    shutdown disposed it, and the next `get_engine()` rebuilt it from
    `settings.database_url` — so every test after the first API test silently
    operated on, and truncated, the development database.
    """
    from fastapi.testclient import TestClient

    from app.db.session import active_database_url
    from app.main import create_app

    before = active_database_url()
    assert before.endswith("_test")

    with TestClient(create_app()) as client:
        assert client.get("/health/live").status_code == 200

    assert active_database_url() == before, "shutdown must not change the configured database"

    # And the rebuilt engine must still point at the test database.
    from app.db.session import get_engine

    assert str(get_engine().url).rsplit("/", 1)[-1].endswith("_test")
