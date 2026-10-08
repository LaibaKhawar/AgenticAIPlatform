"""Semantic retrieval over pgvector.

Every retrieved item keeps full attribution — chunk id, document id, source
type, customer id, source date, raw content and a relevance score — because a
claim is only as good as the row it can be traced back to.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import VectorSearchError
from app.core.failure_injection import get_injector
from app.core.logging import get_logger
from app.core.telemetry import span
from app.llm.embeddings import get_embedding_service
from app.models.domain import CustomerDocument, DocumentChunk
from app.rag.sanitize import sanitise_evidence_content

logger = get_logger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    customer_id: uuid.UUID
    source_type: str
    title: str
    source_date: date | None
    chunk_index: int
    content: str
    relevance_score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    injection_detections: list[str] = field(default_factory=list)

    @property
    def source_id(self) -> str:
        return f"chunk:{self.chunk_id}"


class SemanticRetriever:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _enable_filtered_scan(self) -> None:
        """Make customer-filtered vector search correct, not just fast.

        An HNSW index scan collects its ``ef_search`` nearest candidates by
        *global* distance and only then applies the WHERE clause. With a filter
        as selective as one customer out of thousands, every candidate can be
        filtered away and the query returns **zero rows** — silently, with no
        error. We hit exactly that: a run started immediately after seeding
        retrieved no document evidence at all, because the planner had no
        statistics yet and chose the HNSW path (`Rows Removed by Filter: 40`).

        `hnsw.iterative_scan` (pgvector 0.8+) makes the scan keep going until
        the LIMIT is satisfied, so recall no longer depends on which plan the
        planner happens to pick. `strict_order` preserves exact distance
        ordering. Both are SET LOCAL, so they cannot leak out of this
        transaction, and an older pgvector that does not know the parameter is
        tolerated rather than fatal.
        """
        try:
            self.session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
            self.session.execute(text("SET LOCAL hnsw.ef_search = 100"))
        except (OperationalError, DBAPIError) as error:  # pragma: no cover - older pgvector
            logger.debug("iterative scan unavailable", extra={"error": str(error)[:200]})

    def search(
        self,
        *,
        query: str,
        customer_id: uuid.UUID | None = None,
        source_types: list[str] | None = None,
        limit: int | None = None,
        min_relevance: float = 0.0,
        sanitise: bool = True,
    ) -> list[RetrievedChunk]:
        """Cosine-similarity search, optionally filtered to one customer.

        The customer filter is a hard SQL predicate, not a post-filter: an
        investigation must never see another account's documents.
        """
        settings = get_settings()
        top_k = min(limit or settings.max_retrieval_chunks, 50)
        get_injector().maybe_fail("vector", operation="vector_search")

        with span(
            "vector_search",
            **{"vector.top_k": top_k, "vector.customer_scoped": customer_id is not None},
        ):
            embedding = get_embedding_service().embed_query(query)
            if customer_id is not None:
                self._enable_filtered_scan()
            distance = DocumentChunk.embedding.cosine_distance(embedding)
            statement = (
                select(
                    DocumentChunk.id,
                    DocumentChunk.document_id,
                    DocumentChunk.customer_id,
                    DocumentChunk.chunk_index,
                    DocumentChunk.content,
                    DocumentChunk.chunk_metadata,
                    CustomerDocument.source_type,
                    CustomerDocument.title,
                    CustomerDocument.source_date,
                    distance.label("distance"),
                )
                .join(CustomerDocument, CustomerDocument.id == DocumentChunk.document_id)
                .where(DocumentChunk.embedding.isnot(None))
                .order_by(distance)
                .limit(top_k)
            )
            if customer_id is not None:
                statement = statement.where(DocumentChunk.customer_id == customer_id)
            if source_types:
                statement = statement.where(CustomerDocument.source_type.in_(source_types))

            try:
                rows = self.session.execute(statement).all()
            except (OperationalError, DBAPIError) as error:
                raise VectorSearchError(f"vector search failed: {error}") from error

        results: list[RetrievedChunk] = []
        for row in rows:
            # pgvector cosine_distance is 1 - cosine_similarity, in [0, 2].
            # Relevance is the cosine similarity clamped to [0, 1]; negative
            # similarity means "unrelated", which is the same as 0 here.
            relevance = round(max(0.0, min(1.0, 1.0 - float(row.distance))), 4)
            if relevance < min_relevance:
                continue
            content = row.content
            detections: list[str] = []
            if sanitise:
                sanitised = sanitise_evidence_content(content)
                content = sanitised.content
                detections = sanitised.detections
            results.append(
                RetrievedChunk(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    customer_id=row.customer_id,
                    source_type=row.source_type,
                    title=row.title,
                    source_date=row.source_date,
                    chunk_index=row.chunk_index,
                    content=content,
                    relevance_score=relevance,
                    metadata=dict(row.chunk_metadata or {}),
                    injection_detections=detections,
                )
            )

        logger.info(
            "vector search completed",
            extra={
                "query_chars": len(query),
                "customer_id": str(customer_id) if customer_id else None,
                "results": len(results),
                "top_relevance": results[0].relevance_score if results else None,
            },
        )
        return results

    def search_many(
        self, *, query: str, customer_ids: list[uuid.UUID], limit_per_customer: int = 4
    ) -> dict[uuid.UUID, list[RetrievedChunk]]:
        """Per-customer retrieval. Bounded by design: each customer gets its own
        scoped query so one noisy account cannot crowd out the others."""
        return {
            customer_id: self.search(query=query, customer_id=customer_id, limit=limit_per_customer)
            for customer_id in customer_ids
        }
