"""Retrieval agent — semantic evidence gathering and persistence.

Produces the evidence set an investigation is allowed to cite. Two kinds of
evidence are recorded:

* **document chunks** retrieved from pgvector, carrying full attribution; and
* **metric rows**, one per deterministic risk signal, so a calculated claim has
  something concrete and verifiable to cite instead of being unverifiable prose.

Retrieved content is untrusted: it is sanitised, injection attempts are recorded
as audit events, and the text is only ever rendered inside a delimited data
block.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import AgentConfig, AgentRunContext, BaseAgent
from app.analytics.risk import RiskAssessment
from app.core.clock import today
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.enums import ActorType, AgentType, AuditEventType, EvidenceSourceType
from app.rag.retrieval import SemanticRetriever
from app.repositories.investigations import EvidenceRepository
from app.repositories.runs import RunRepository
from app.schemas.agent import EvidenceItem

logger = get_logger(__name__)

# One query per concern, so an account with a single dominant issue still
# surfaces evidence about the others instead of returning four near-duplicates.
EVIDENCE_QUERIES: tuple[tuple[str, str], ...] = (
    ("renewal_intent", "renewal decision, contract, evaluating alternative platforms, competitor, pricing"),
    ("product_experience", "product usage, adoption, missing feature, workflow problems, reporting"),
    ("relationship", "executive sponsor, stakeholder change, escalation, frustration, satisfaction"),
    ("support_billing", "support tickets, response times, invoice, billing, budget"),
)


@dataclass
class EvidenceSet:
    customer_id: uuid.UUID
    items: list[EvidenceItem] = field(default_factory=list)
    injection_detections: list[dict[str, Any]] = field(default_factory=list)
    queries_run: int = 0

    @property
    def references(self) -> list[str]:
        return [item.reference for item in self.items]

    def documents(self) -> list[EvidenceItem]:
        return [item for item in self.items if item.source_type == EvidenceSourceType.DOCUMENT_CHUNK.value]

    def as_prompt_payload(self) -> list[dict[str, Any]]:
        return [
            {
                "reference": item.reference,
                "source_type": item.source_type,
                "source_date": item.source_date.isoformat() if item.source_date else None,
                "title": item.title,
                "content": item.content,
                "relevance_score": item.relevance_score,
                "metadata": item.metadata,
            }
            for item in self.items
        ]


class RetrievalAgent(BaseAgent):
    config = AgentConfig(
        agent_type=AgentType.RETRIEVAL,
        role=(
            "Retrieves and persists attributable evidence: semantic document search over pgvector "
            "plus deterministic metric records. Treats all retrieved content as untrusted data."
        ),
        allowed_tools=("search_customer_documents", "list_customer_documents", "get_document"),
        uses_llm=False,
        timeout_seconds=90.0,
    )

    def gather(
        self,
        context: AgentRunContext,
        *,
        customer_id: uuid.UUID,
        assessment: RiskAssessment,
        objective: str,
        chunk_budget: int | None = None,
    ) -> EvidenceSet:
        settings = get_settings()
        budget = chunk_budget or settings.max_retrieval_chunks
        evidence_set = EvidenceSet(customer_id=customer_id)

        with self.traced(context, "evidence_retrieval"):
            evidence_repo = EvidenceRepository(context.session)
            run_id = context.run_id
            assert run_id is not None, "evidence retrieval requires a run"

            # 1. Deterministic metric evidence — the citable form of a computed number.
            for signal in assessment.top_signals:
                if signal.severity < 0.1:
                    continue
                record = evidence_repo.upsert(
                    run_id=run_id,
                    customer_id=customer_id,
                    source_type=EvidenceSourceType.USAGE_METRIC,
                    source_id=f"signal:{signal.key}",
                    title=signal.label,
                    content=signal.detail,
                    source_date=today(),
                    relevance_score=round(signal.severity, 4),
                    metadata={
                        "signal_key": signal.key,
                        "value": signal.value,
                        "unit": signal.unit,
                        "severity": signal.severity,
                        "weight": signal.weight,
                        "computed_by": "deterministic_risk_engine",
                    },
                )
                evidence_set.items.append(_to_item(record))

            # 2. Semantic document evidence, bounded per query and overall.
            retriever = SemanticRetriever(context.session)
            per_query = max(1, budget // len(EVIDENCE_QUERIES))
            seen_chunks: set[uuid.UUID] = set()
            document_items = 0

            for concern, query_text in EVIDENCE_QUERIES:
                if document_items >= budget:
                    break
                chunks = retriever.search(
                    query=f"{objective}\n{query_text}",
                    customer_id=customer_id,
                    limit=per_query,
                )
                evidence_set.queries_run += 1
                for chunk in chunks:
                    if chunk.chunk_id in seen_chunks or document_items >= budget:
                        continue
                    seen_chunks.add(chunk.chunk_id)
                    if chunk.injection_detections:
                        self._record_injection(context, customer_id, chunk)
                        evidence_set.injection_detections.append(
                            {
                                "source_id": chunk.source_id,
                                "detections": chunk.injection_detections,
                                "title": chunk.title,
                            }
                        )
                    record = evidence_repo.upsert(
                        run_id=run_id,
                        customer_id=customer_id,
                        source_type=EvidenceSourceType.DOCUMENT_CHUNK,
                        source_id=chunk.source_id,
                        title=chunk.title,
                        content=chunk.content,
                        source_date=chunk.source_date,
                        relevance_score=chunk.relevance_score,
                        metadata={
                            "document_id": str(chunk.document_id),
                            "chunk_index": chunk.chunk_index,
                            "document_source_type": chunk.source_type,
                            "concern": concern,
                            "injection_detections": chunk.injection_detections,
                            "trusted": False,
                        },
                    )
                    evidence_set.items.append(_to_item(record))
                    document_items += 1

            logger.info(
                "evidence gathered",
                extra={
                    "customer_id": str(customer_id),
                    "metric_items": len(assessment.top_signals),
                    "document_items": document_items,
                    "queries": evidence_set.queries_run,
                    "injection_detections": len(evidence_set.injection_detections),
                },
            )
        return evidence_set

    def _record_injection(self, context: AgentRunContext, customer_id: uuid.UUID, chunk: Any) -> None:
        RunRepository(context.session).record_event(
            run_id=context.run_id,
            customer_id=customer_id,
            event_type=AuditEventType.PROMPT_INJECTION_DETECTED,
            actor_type=ActorType.AGENT,
            actor_id=self.name,
            message=(
                "Instruction-like text was detected in retrieved customer content and neutralised "
                "before it reached a model prompt."
            ),
            payload={
                "source_id": chunk.source_id,
                "document_id": str(chunk.document_id),
                "detections": chunk.injection_detections,
                "title": chunk.title,
            },
        )
        logger.warning(
            "prompt injection neutralised in retrieved content",
            extra={
                "customer_id": str(customer_id),
                "source_id": chunk.source_id,
                "detections": chunk.injection_detections,
            },
        )


def _to_item(record: Any) -> EvidenceItem:
    return EvidenceItem(
        reference=record.reference,
        evidence_id=str(record.id),
        source_type=record.source_type,
        source_id=record.source_id,
        customer_id=str(record.customer_id) if record.customer_id else None,
        title=record.title,
        content=record.content,
        source_date=record.source_date,
        relevance_score=float(record.relevance_score) if record.relevance_score is not None else None,
        metadata=dict(record.evidence_metadata or {}),
    )
