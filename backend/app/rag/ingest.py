"""Document → chunk → embedding → pgvector ingestion."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.llm.embeddings import get_embedding_service
from app.models.domain import CustomerDocument, DocumentChunk
from app.rag.chunking import chunk_text

logger = get_logger(__name__)


@dataclass
class IngestStats:
    documents: int = 0
    chunks: int = 0
    embedded: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "documents": self.documents,
            "chunks": self.chunks,
            "embedded": self.embedded,
            "skipped": self.skipped,
        }


def ingest_documents(
    session: Session,
    documents: Sequence[CustomerDocument],
    *,
    replace_existing: bool = True,
    embed: bool = True,
) -> IngestStats:
    """Chunk and embed documents, writing chunks in one batch.

    Idempotent: re-ingesting a document replaces its chunks, so a retried seed
    or re-index does not leave duplicates behind.
    """
    stats = IngestStats()
    if not documents:
        return stats

    document_ids = [document.id for document in documents]
    if replace_existing:
        session.execute(delete(DocumentChunk).where(DocumentChunk.document_id.in_(document_ids)))

    pending: list[tuple[CustomerDocument, int, str]] = []
    for document in documents:
        chunks = chunk_text(document.content)
        if not chunks:
            stats.skipped += 1
            continue
        stats.documents += 1
        for chunk in chunks:
            pending.append((document, chunk.index, chunk.content))

    if not pending:
        return stats

    vectors: list[list[float] | None]
    if embed:
        service = get_embedding_service()
        embedded, _usage = service.embed_texts([content for _doc, _idx, content in pending])
        vectors = list(embedded)
        stats.embedded = len(embedded)
    else:
        vectors = [None] * len(pending)

    session.bulk_save_objects(
        [
            DocumentChunk(
                id=uuid.uuid4(),
                document_id=document.id,
                customer_id=document.customer_id,
                chunk_index=index,
                content=content,
                embedding=vector,
                chunk_metadata={
                    "source_type": document.source_type,
                    "title": document.title,
                    "source_date": document.source_date.isoformat() if document.source_date else None,
                    **(document.doc_metadata or {}),
                },
            )
            for (document, index, content), vector in zip(pending, vectors, strict=True)
        ]
    )
    stats.chunks = len(pending)
    session.flush()
    logger.info("ingested documents", extra=stats.as_dict())
    return stats


def reindex_customer(session: Session, customer_id: uuid.UUID) -> IngestStats:
    documents = list(session.scalars(select(CustomerDocument).where(CustomerDocument.customer_id == customer_id)))
    return ingest_documents(session, documents)


def iter_batches(items: Iterable[CustomerDocument], size: int) -> Iterable[list[CustomerDocument]]:
    batch: list[CustomerDocument] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
