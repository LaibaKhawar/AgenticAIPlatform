"""Evidence, claims, investigations, reports and approvals.

Writes are idempotent by construction: every table has a natural key scoped to
the run (``source_id``, ``claim_key``, ``customer_id``, ``idempotency_key``), so
a retried task updates rows instead of duplicating them.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import (
    ActionType,
    ApprovalStatus,
    ClaimStatus,
    ClaimType,
    EvidenceSourceType,
    RiskLevel,
)
from app.models.workflow import Approval, Claim, Evidence, Investigation, Report


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class EvidenceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def next_reference_index(self, run_id: uuid.UUID, customer_id: uuid.UUID | None) -> int:
        """Next free reference index within one customer's evidence set.

        Scoped to the customer on purpose. Numbering per *run* means every
        concurrent investigation task reads the same count and races to insert
        the same ``EV-n`` — a unique-constraint violation that only appears once
        real parallel workers are involved. One customer is investigated by
        exactly one task, so per-customer numbering needs no lock and no retry,
        and it reads better: ``EV-1`` is that account's first record rather than
        an arbitrary position in a shared sequence.
        """
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(Evidence)
                .where(Evidence.run_id == run_id, Evidence.customer_id == customer_id)
            )
            or 0
        )

    def upsert(
        self,
        *,
        run_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        source_type: EvidenceSourceType,
        source_id: str,
        content: str,
        title: str = "",
        source_date: date | None = None,
        relevance_score: float | None = None,
        metadata: dict[str, Any] | None = None,
        reference: str | None = None,
    ) -> Evidence:
        existing = self.session.scalars(
            select(Evidence).where(
                Evidence.run_id == run_id,
                Evidence.customer_id == customer_id,
                Evidence.source_id == source_id,
            )
        ).first()
        if existing is not None:
            existing.content = content
            existing.title = title or existing.title
            existing.relevance_score = relevance_score
            existing.evidence_metadata = metadata or existing.evidence_metadata
            self.session.flush()
            return existing

        if reference is None:
            reference = f"EV-{self.next_reference_index(run_id, customer_id) + 1}"
        record = Evidence(
            run_id=run_id,
            customer_id=customer_id,
            source_type=source_type.value,
            source_id=source_id,
            reference=reference,
            title=title[:300],
            content=content,
            source_date=source_date,
            relevance_score=relevance_score,
            evidence_metadata=metadata or {},
            created_at=utcnow(),
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_for_run(
        self, run_id: uuid.UUID, *, customer_id: uuid.UUID | None = None, limit: int = 500
    ) -> list[Evidence]:
        query = select(Evidence).where(Evidence.run_id == run_id)
        if customer_id is not None:
            query = query.where(Evidence.customer_id == customer_id)
        return list(self.session.scalars(query.order_by(Evidence.created_at, Evidence.reference).limit(limit)))

    def map_by_reference(self, run_id: uuid.UUID, *, customer_id: uuid.UUID | None = None) -> dict[str, Evidence]:
        return {item.reference: item for item in self.list_for_run(run_id, customer_id=customer_id)}

    def count_for_run(self, run_id: uuid.UUID) -> int:
        return int(
            self.session.scalar(select(func.count()).select_from(Evidence).where(Evidence.run_id == run_id)) or 0
        )


class ClaimRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        *,
        run_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        claim_key: str,
        claim_text: str,
        claim_type: ClaimType,
        confidence: float,
        evidence: Sequence[Evidence],
        status: ClaimStatus = ClaimStatus.PENDING,
    ) -> Claim:
        existing = self.session.scalars(
            select(Claim)
            .options(selectinload(Claim.evidence_items))
            .where(Claim.run_id == run_id, Claim.claim_key == claim_key)
        ).first()
        if existing is not None:
            existing.claim_text = claim_text
            existing.claim_type = claim_type.value
            existing.confidence = confidence
            existing.status = status.value
            existing.evidence_items = list(evidence)
            self.session.flush()
            return existing

        claim = Claim(
            run_id=run_id,
            customer_id=customer_id,
            claim_key=claim_key,
            claim_text=claim_text,
            claim_type=claim_type.value,
            status=status.value,
            confidence=confidence,
            created_at=utcnow(),
        )
        claim.evidence_items = list(evidence)
        self.session.add(claim)
        self.session.flush()
        return claim

    def record_verification(
        self,
        claim: Claim,
        *,
        status: ClaimStatus,
        confidence: float,
        reason: str,
        suggested_revision: str | None,
        final_text: str | None,
    ) -> Claim:
        claim.status = status.value
        claim.confidence = confidence
        claim.verification_reason = reason
        claim.suggested_revision = suggested_revision
        claim.final_text = final_text
        claim.verified_at = utcnow()
        self.session.flush()
        return claim

    def list_for_run(
        self,
        run_id: uuid.UUID,
        *,
        customer_id: uuid.UUID | None = None,
        status: ClaimStatus | None = None,
        limit: int = 500,
    ) -> list[Claim]:
        query = select(Claim).options(selectinload(Claim.evidence_items)).where(Claim.run_id == run_id)
        if customer_id is not None:
            query = query.where(Claim.customer_id == customer_id)
        if status is not None:
            query = query.where(Claim.status == status.value)
        return list(self.session.scalars(query.order_by(Claim.created_at, Claim.claim_key).limit(limit)).unique())

    def verification_stats(self, run_id: uuid.UUID) -> dict[str, Any]:
        rows = self.session.execute(
            select(Claim.status, func.count()).where(Claim.run_id == run_id).group_by(Claim.status)
        ).all()
        counts = {str(status): int(count) for status, count in rows}
        total = sum(counts.values())
        supported = counts.get(ClaimStatus.SUPPORTED.value, 0)
        partial = counts.get(ClaimStatus.PARTIALLY_SUPPORTED.value, 0)
        unsupported = counts.get(ClaimStatus.UNSUPPORTED.value, 0) + counts.get(ClaimStatus.CONTRADICTED.value, 0)
        return {
            "total": total,
            "counts": counts,
            "supported_pct": round(supported / total * 100, 2) if total else None,
            "partially_supported_pct": round(partial / total * 100, 2) if total else None,
            "unsupported_pct": round(unsupported / total * 100, 2) if total else None,
        }


class InvestigationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        *,
        run_id: uuid.UUID,
        customer_id: uuid.UUID,
        risk_score: float,
        heuristic_risk_score: float,
        risk_level: RiskLevel,
        confidence: float,
        summary: str,
        risk_factors: list[dict[str, Any]],
        quantitative_signals: dict[str, Any],
        recommended_actions: list[dict[str, Any]],
        data_gaps: list[str],
    ) -> Investigation:
        existing = self.session.scalars(
            select(Investigation).where(Investigation.run_id == run_id, Investigation.customer_id == customer_id)
        ).first()
        target = existing or Investigation(run_id=run_id, customer_id=customer_id, created_at=utcnow())
        target.risk_score = risk_score
        target.heuristic_risk_score = heuristic_risk_score
        target.risk_level = risk_level.value
        target.confidence = confidence
        target.summary = summary
        target.risk_factors = risk_factors
        target.quantitative_signals = quantitative_signals
        target.recommended_actions = recommended_actions
        target.data_gaps = data_gaps
        if existing is None:
            self.session.add(target)
        self.session.flush()
        return target

    def list_for_run(self, run_id: uuid.UUID) -> list[Investigation]:
        return list(
            self.session.scalars(
                select(Investigation).where(Investigation.run_id == run_id).order_by(Investigation.risk_score.desc())
            )
        )

    def get(self, run_id: uuid.UUID, customer_id: uuid.UUID) -> Investigation | None:
        return self.session.scalars(
            select(Investigation).where(Investigation.run_id == run_id, Investigation.customer_id == customer_id)
        ).first()

    def recent_high_risk(self, *, limit: int = 10) -> list[Investigation]:
        return list(
            self.session.scalars(
                select(Investigation)
                .where(Investigation.risk_level.in_([RiskLevel.HIGH.value, RiskLevel.CRITICAL.value]))
                .order_by(Investigation.created_at.desc())
                .limit(limit)
            )
        )

    def history_for_customer(self, customer_id: uuid.UUID, *, limit: int = 10) -> list[Investigation]:
        return list(
            self.session.scalars(
                select(Investigation)
                .where(Investigation.customer_id == customer_id)
                .order_by(Investigation.created_at.desc())
                .limit(limit)
            )
        )


class ReportRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        *,
        run_id: uuid.UUID,
        title: str,
        executive_summary: str,
        report_payload: dict[str, Any],
        markdown_content: str,
    ) -> Report:
        existing = self.session.scalars(select(Report).where(Report.run_id == run_id)).first()
        target = existing or Report(run_id=run_id, created_at=utcnow())
        target.title = title[:300]
        target.executive_summary = executive_summary
        target.report_payload = report_payload
        target.markdown_content = markdown_content
        if existing is None:
            self.session.add(target)
        self.session.flush()
        return target

    def get(self, run_id: uuid.UUID) -> Report | None:
        return self.session.scalars(select(Report).where(Report.run_id == run_id)).first()

    def list_reports(self, *, limit: int = 25, offset: int = 0) -> list[Report]:
        return list(self.session.scalars(select(Report).order_by(Report.created_at.desc()).limit(limit).offset(offset)))

    def count(self) -> int:
        return int(self.session.scalar(select(func.count()).select_from(Report)) or 0)


class ApprovalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def request(
        self,
        *,
        run_id: uuid.UUID,
        customer_id: uuid.UUID | None,
        action_type: ActionType,
        proposed_action: str,
        reason: str,
        action_payload: dict[str, Any],
        idempotency_key: str,
    ) -> tuple[Approval, bool]:
        """Create (or return) the approval for this action. Second element is
        ``True`` when a new record was created."""
        existing = self.session.scalars(
            select(Approval).where(Approval.run_id == run_id, Approval.idempotency_key == idempotency_key)
        ).first()
        if existing is not None:
            return existing, False

        approval = Approval(
            run_id=run_id,
            customer_id=customer_id,
            action_type=action_type.value,
            proposed_action=proposed_action,
            action_payload=action_payload,
            status=ApprovalStatus.PENDING.value,
            reason=reason,
            idempotency_key=idempotency_key,
            requested_at=utcnow(),
        )
        self.session.add(approval)
        self.session.flush()
        return approval, True

    def get(self, approval_id: uuid.UUID, *, for_update: bool = False) -> Approval | None:
        query = select(Approval).where(Approval.id == approval_id)
        if for_update:
            query = query.with_for_update()
        return self.session.scalars(query).first()

    def resolve(
        self,
        approval: Approval,
        *,
        status: ApprovalStatus,
        reviewed_by: str,
        comment: str | None,
    ) -> Approval:
        approval.status = status.value
        approval.reviewed_by = reviewed_by
        approval.reviewer_comment = comment
        approval.reviewed_at = utcnow()
        self.session.flush()
        return approval

    def list_approvals(
        self,
        *,
        status: ApprovalStatus | None = None,
        run_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Approval]:
        query = select(Approval).order_by(Approval.requested_at.desc()).limit(limit).offset(offset)
        if status:
            query = query.where(Approval.status == status.value)
        if run_id:
            query = query.where(Approval.run_id == run_id)
        return list(self.session.scalars(query))

    def count_approvals(self, *, status: ApprovalStatus | None = None, run_id: uuid.UUID | None = None) -> int:
        query = select(func.count()).select_from(Approval)
        if status:
            query = query.where(Approval.status == status.value)
        if run_id:
            query = query.where(Approval.run_id == run_id)
        return int(self.session.scalar(query) or 0)

    def pending_for_run(self, run_id: uuid.UUID) -> list[Approval]:
        return self.list_approvals(status=ApprovalStatus.PENDING, run_id=run_id, limit=200)

    def all_resolved(self, run_id: uuid.UUID) -> bool:
        return self.count_approvals(status=ApprovalStatus.PENDING, run_id=run_id) == 0
