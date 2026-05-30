from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_vector_store
from app.services.retrieval.vector_store import QdrantVectorStore

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(
    db: AsyncSession = Depends(get_db),
    vector_store: QdrantVectorStore = Depends(get_vector_store),
) -> dict[str, str]:
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "error"

    qdrant_status = "connected" if await vector_store.health_check() else "error"

    return {"status": "ok", "db": db_status, "qdrant": qdrant_status}
