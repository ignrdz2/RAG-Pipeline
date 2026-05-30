import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_pipeline, get_vector_store
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.document import Document
from app.schemas.document import DocumentResponse, DocumentUploadResponse

router = APIRouter(prefix="/documents", tags=["documents"])

_ALLOWED_TYPES = {"pdf", "docx", "txt"}


async def _run_ingestion(document_id: str, file_path: Path, file_type: str) -> None:
    """Wrapper que crea su propia sesión de DB para el background task."""
    pipeline = get_pipeline()
    async with AsyncSessionLocal() as db:
        await pipeline.run(
            document_id=document_id,
            file_path=file_path,
            file_type=file_type,
            db=db,
        )


@router.post("/upload", response_model=DocumentUploadResponse, status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    # Validar nombre y extensión
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido")

    file_type = Path(file.filename).suffix.lower().lstrip(".")
    if file_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo no soportado: {file_type!r}. Se aceptan: pdf, docx, txt",
        )

    # Leer contenido y validar tamaño
    content = await file.read()
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Archivo demasiado grande. Máximo: {settings.MAX_FILE_SIZE_MB}MB",
        )

    # Crear registro en DB
    doc = Document(
        filename=file.filename,
        file_type=file_type,
        file_size=len(content),
    )
    db.add(doc)
    await db.commit()

    # Guardar archivo temporal
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{doc.id}_{file.filename}"
    file_path.write_bytes(content)

    # Lanzar background task
    background_tasks.add_task(_run_ingestion, str(doc.id), file_path, file_type)

    return DocumentUploadResponse(
        document_id=doc.id,
        filename=doc.filename,
        status=doc.status,
    )


@router.get("/", response_model=list[DocumentResponse])
async def list_documents(db: AsyncSession = Depends(get_db)) -> list[Document]:
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Document:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return doc


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Documento no encontrado")

    vector_store = get_vector_store()
    await vector_store.delete_by_document(str(document_id))

    await db.delete(doc)
    await db.commit()
    return Response(status_code=204)
