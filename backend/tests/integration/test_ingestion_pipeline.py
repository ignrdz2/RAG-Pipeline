"""
Tests de integración para el pipeline de ingesta.

Estrategia de mocking:
- DB: SQLite en archivo temporal con NullPool.
  NullPool es necesario porque el background task abre su propia sesión mientras
  la sesión del request aún está viva; con StaticPool (una sola conexión) eso
  provocaría un deadlock en el event loop.
- GeminiEmbedder y QdrantVectorStore: AsyncMock — no se realizan llamadas externas.
- parse(): MagicMock — el parseo de archivos se cubre en unit tests.

Por qué los background tasks ya terminaron cuando el test hace GET:
  Starlette ejecuta `await self.background()` DENTRO del ciclo ASGI, antes de
  retornar el control a ASGITransport. Por tanto, `await client.post(...)` solo
  retorna cuando el background task ya completó y el documento está en su estado
  final.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.deps import get_db, get_pipeline, get_vector_store
from app.db.base import Base
from app.main import app
from app.services.ingestion.pipeline import IngestionPipeline
from app.services.retrieval.embedder import GeminiEmbedder
from app.services.retrieval.vector_store import QdrantVectorStore

# Constantes

# Texto > 100 tokens para que el chunker genere al menos un chunk válido
FAKE_PAGES = [(1, "Texto de prueba para el test de integración. " * 50)]
FAKE_VECTOR = [0.1] * 768


# Fixtures de infraestructura


@pytest.fixture(scope="module")
async def test_engine():
    """Engine SQLite en archivo temporal; tablas creadas una vez por módulo."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture(autouse=True)
async def clean_tables(test_engine):
    """Borra todos los datos entre tests para garantizar aislamiento."""
    yield
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest.fixture
def mock_vector_store() -> AsyncMock:
    vs = AsyncMock(spec=QdrantVectorStore)
    vs.upsert.return_value = None
    vs.delete_by_document.return_value = None
    vs.health_check.return_value = True
    vs.search.return_value = []
    return vs


@pytest.fixture
def mock_embedder() -> AsyncMock:
    emb = AsyncMock(spec=GeminiEmbedder)
    # Devuelve tantos vectores falsos como textos reciba
    emb.embed_batch.side_effect = lambda texts: [FAKE_VECTOR for _ in texts]
    emb.embed_single.return_value = FAKE_VECTOR
    return emb


@pytest.fixture
def ingestion_pipeline(
    mock_embedder: AsyncMock, mock_vector_store: AsyncMock
) -> IngestionPipeline:
    return IngestionPipeline(embedder=mock_embedder, vector_store=mock_vector_store)


@pytest.fixture
async def client(
    test_engine,
    mock_vector_store: AsyncMock,
    mock_embedder: AsyncMock,
    ingestion_pipeline: IngestionPipeline,
) -> AsyncClient:
    """
    AsyncClient con:
    - DB de test inyectada en todos los puntos donde la app abre sesiones
    - GeminiEmbedder y QdrantVectorStore reemplazados por AsyncMocks
    - parse() reemplazado para evitar leer archivos reales

    Se usan TANTO dependency_overrides (para los Depends() de FastAPI) COMO
    patch() sobre los módulos (para las llamadas directas fuera de Depends).
    """
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    def override_get_vector_store() -> AsyncMock:
        return mock_vector_store

    def override_get_pipeline() -> IngestionPipeline:
        return ingestion_pipeline

    # FastAPI dependency overrides (Depends())
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = override_get_vector_store
    app.dependency_overrides[get_pipeline] = override_get_pipeline

    with (
        # _run_ingestion() abre sesión directamente vía AsyncSessionLocal
        patch("app.api.routers.documents.AsyncSessionLocal", test_session_factory),
        # _run_ingestion() llama get_pipeline() directamente (no via Depends)
        patch("app.api.routers.documents.get_pipeline", override_get_pipeline),
        # delete_document() llama get_vector_store() directamente (no via Depends)
        patch("app.api.routers.documents.get_vector_store", override_get_vector_store),
        # Evitar parseo real de archivos (se testea en unit tests)
        patch("app.services.ingestion.pipeline.parse", return_value=FAKE_PAGES),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c

    app.dependency_overrides.clear()


# Helper


def _file(filename: str, content: bytes, content_type: str = "text/plain") -> dict:
    return {"file": (filename, content, content_type)}


# Tests


async def test_upload_pdf_exitoso(client: AsyncClient) -> None:
    """POST /upload con PDF válido → 202; background task completa y queda 'ready'."""
    response = await client.post(
        "/api/v1/documents/upload",
        files=_file("contrato.pdf", b"fake pdf bytes", "application/pdf"),
    )

    assert response.status_code == 202
    body = response.json()
    assert body["filename"] == "contrato.pdf"
    assert body["status"] == "pending"
    doc_id = body["document_id"]

    # El background task completó antes de que client.post() retornara
    # (ASGITransport ejecuta await self.background() dentro del ciclo ASGI)
    poll = await client.get(f"/api/v1/documents/{doc_id}")
    assert poll.status_code == 200
    assert poll.json()["status"] == "ready"


async def test_upload_tipo_invalido(client: AsyncClient) -> None:
    """POST /upload con extensión no soportada → 400."""
    response = await client.post(
        "/api/v1/documents/upload",
        files=_file("exploit.exe", b"malicious", "application/octet-stream"),
    )

    assert response.status_code == 400
    assert "Tipo no soportado" in response.json()["detail"]


async def test_upload_muy_grande(client: AsyncClient) -> None:
    """POST /upload con archivo > MAX_FILE_SIZE_MB → 400."""
    from app.core.config import settings

    oversized = b"x" * (settings.MAX_FILE_SIZE_MB * 1024 * 1024 + 1)
    response = await client.post(
        "/api/v1/documents/upload",
        files=_file("gigante.txt", oversized),
    )

    assert response.status_code == 400
    assert "demasiado grande" in response.json()["detail"]


async def test_list_documentos(client: AsyncClient) -> None:
    """Subir 2 documentos → GET /documents retorna lista con exactamente 2 items."""
    for i in range(2):
        resp = await client.post(
            "/api/v1/documents/upload",
            files=_file(f"doc{i}.txt", b"Contenido de prueba del documento."),
        )
        assert resp.status_code == 202

    response = await client.get("/api/v1/documents/")
    assert response.status_code == 200
    docs = response.json()
    assert len(docs) == 2
    # Verifica orden descendente por created_at (el más reciente primero)
    assert docs[0]["filename"] == "doc1.txt"
    assert docs[1]["filename"] == "doc0.txt"


async def test_delete_documento(
    client: AsyncClient, mock_vector_store: AsyncMock
) -> None:
    """DELETE /documents/{id} → 204; Qdrant recibe la llamada; GET posterior → 404."""
    upload = await client.post(
        "/api/v1/documents/upload",
        files=_file("borrar.txt", b"Contenido temporal a eliminar."),
    )
    assert upload.status_code == 202
    doc_id = upload.json()["document_id"]

    delete = await client.delete(f"/api/v1/documents/{doc_id}")
    assert delete.status_code == 204

    # Qdrant recibió la orden de eliminar los chunks del documento
    mock_vector_store.delete_by_document.assert_called_with(doc_id)

    # El documento ya no existe en la DB
    get = await client.get(f"/api/v1/documents/{doc_id}")
    assert get.status_code == 404


async def test_pipeline_error_marca_documento(
    client: AsyncClient, mock_embedder: AsyncMock
) -> None:
    """Si el embedder lanza excepción, el documento queda status='error' con error_msg."""
    mock_embedder.embed_batch.side_effect = RuntimeError(
        "API de embeddings no disponible"
    )

    upload = await client.post(
        "/api/v1/documents/upload",
        files=_file("falla.txt", b"Content that will trigger an embedding error."),
    )
    assert upload.status_code == 202
    doc_id = upload.json()["document_id"]

    # Background task completó: el pipeline capturó la excepción y actualizó la DB
    get = await client.get(f"/api/v1/documents/{doc_id}")
    assert get.status_code == 200
    doc = get.json()
    assert doc["status"] == "error"
    assert doc["error_msg"] is not None
    assert "embeddings" in doc["error_msg"]


# ── Smoke test manual ─────────────────────────────────────────────────────────

# Para probar manualmente con Docker:
# 1. docker compose up --build
# 2. docker compose exec backend alembic upgrade head
# 3. curl -X GET http://localhost:8000/api/v1/health
# 4. curl -X POST http://localhost:8000/api/v1/documents/upload \
#      -F "file=@/ruta/a/archivo.pdf"
# 5. curl http://localhost:8000/api/v1/documents/{id}
