import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.services.ingestion.chunker import SmartChunker
from app.services.ingestion.parser import parse
from app.services.retrieval.embedder import GeminiEmbedder
from app.services.retrieval.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)


class IngestionPipeline:
    def __init__(self, embedder: GeminiEmbedder, vector_store: QdrantVectorStore) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._chunker = SmartChunker()

    async def run(
        self,
        document_id: str,
        file_path: Path,
        file_type: str,
        db: AsyncSession,
    ) -> None:
        doc_uuid = uuid.UUID(document_id)
        chunks_uploaded = False

        try:
            doc = await db.get(Document, doc_uuid)
            if doc is None:
                logger.error("Documento %s no encontrado en DB, abortando pipeline", document_id)
                return

            # Guarda filename antes de cualquier commit/rollback que expire el objeto
            filename = doc.filename

            # status → processing
            doc.status = "processing"
            await db.commit()

            # parsear archivo
            pages = parse(file_path, file_type)

            # chunking
            chunks = self._chunker.split(pages, document_id)
            for chunk in chunks:
                chunk.filename = filename

            # embed
            vectors = await self._embedder.embed_batch([c.text for c in chunks])

            # upsert a Qdrant
            await self._vector_store.upsert(chunks, vectors)
            chunks_uploaded = True

            # calcular page_count (máximo page_number de los chunks)
            page_numbers = [c.page_number for c in chunks if c.page_number is not None]
            page_count = max(page_numbers) if page_numbers else None

            doc.status = "ready"
            doc.chunk_count = len(chunks)
            doc.page_count = page_count
            await db.commit()

        except Exception as exc:
            logger.error(
                "Pipeline falló para documento %s: %s",
                document_id,
                exc,
                exc_info=True,
            )

            # Rollback para limpiar cualquier transacción pendiente.
            # Tras el rollback el objeto doc queda expirado, usamos SQL directo.
            await db.rollback()
            try:
                await db.execute(
                    update(Document)
                    .where(Document.id == doc_uuid)
                    .values(
                        status="error",
                        error_msg=str(exc)[:2000],
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                await db.commit()
            except Exception:
                logger.error(
                    "No se pudo persistir el estado de error para %s",
                    document_id,
                    exc_info=True,
                )

            # Limpiar Qdrant si ya se habían subido chunks
            if chunks_uploaded:
                try:
                    await self._vector_store.delete_by_document(document_id)
                except Exception:
                    logger.error(
                        "Qdrant cleanup falló para documento %s",
                        document_id,
                        exc_info=True,
                    )

        finally:
            # siempre borrar el archivo temporal
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass
