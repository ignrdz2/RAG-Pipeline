import dataclasses
import logging
import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from app.services.ingestion.chunker import Chunk

logger = logging.getLogger(__name__)

_UPSERT_BATCH_SIZE = 100


class QdrantVectorStore:
    def __init__(self, url: str, api_key: str, collection_name: str) -> None:
        self._client = AsyncQdrantClient(url=url, api_key=api_key)
        self._collection = collection_name

    async def ensure_collection(self, vector_size: int = 768) -> None:
        """Crea la colección si no existe, con distancia COSINE."""
        existing = await self._client.get_collections()
        names = {c.name for c in existing.collections}
        if self._collection not in names:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )
            logger.info("Colección '%s' creada (dim=%d)", self._collection, vector_size)

    async def upsert(
        self, chunks: list[Chunk], vectors: list[list[float]]
    ) -> None:
        """Inserta o actualiza chunks con sus vectores en batches de 100."""
        points: list[PointStruct] = []
        for chunk, vector in zip(chunks, vectors):
            # ID determinístico para que re-upserts sean idempotentes
            point_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"{chunk.document_id}:{chunk.chunk_index}",
                )
            )
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=dataclasses.asdict(chunk),
                )
            )

        for i in range(0, len(points), _UPSERT_BATCH_SIZE):
            batch = points[i : i + _UPSERT_BATCH_SIZE]
            await self._client.upsert(
                collection_name=self._collection,
                points=batch,
            )

    async def search(
        self,
        vector: list[float],
        filter_doc_ids: list[str] | None = None,
        limit: int = 10,
    ) -> list[ScoredPoint]:
        """Búsqueda vectorial con filtro opcional por document_id."""
        query_filter: Filter | None = None
        if filter_doc_ids:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchAny(any=filter_doc_ids),
                    )
                ]
            )

        return await self._client.search(
            collection_name=self._collection,
            query_vector=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )

    async def delete_by_document(self, document_id: str) -> None:
        """Elimina todos los puntos cuyo payload.document_id coincida."""
        await self._client.delete(
            collection_name=self._collection,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id),
                        )
                    ]
                )
            ),
        )

    async def health_check(self) -> bool:
        """Verifica que Qdrant responde."""
        try:
            await self._client.get_collections()
            return True
        except Exception as exc:
            logger.warning("Qdrant health check fallido: %s", exc)
            return False
