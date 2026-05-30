# Documentación Técnica — Fase de Ingesta

Esta documentación cubre todo lo implementado hasta el momento en el pipeline de ingesta de documentos del sistema RAG-Pipeline. Está escrita para que alguien sin experiencia previa en sistemas RAG pueda entender qué hace cada pieza y por qué.

---

## Contexto: ¿Qué es RAG?

**RAG** (Retrieval-Augmented Generation) es una técnica para hacer que un modelo de lenguaje (LLM) responda preguntas basándose en documentos específicos en lugar de solo en su conocimiento de entrenamiento.

El flujo general es:

```
Documento → Fragmentos de texto → Vectores numéricos → Base vectorial
                                                              ↓
Pregunta → Vector → Buscar fragmentos similares → LLM → Respuesta con citas
```

Por qué es útil: los LLMs no pueden "leer" documentos en tiempo real ni tienen acceso a información privada. RAG les da ese acceso de manera controlada.

---

## Arquitectura general

```
┌─────────────────────────────────────────────────────────────┐
│                     BACKEND (FastAPI)                       │
│                                                             │
│  POST /upload → IngestionPipeline (background task)         │
│                                                             │
│  ┌──────────┐   ┌──────────┐   ┌───────────┐   ┌────────┐  │
│  │  Parser  │ → │  Chunker │ → │  Embedder │ → │ Qdrant │  │
│  │(PDF/DOCX/│   │(overlap  │   │  (Gemini) │   │(vector │  │
│  │  TXT)    │   │ intelig.)│   │           │   │  store)│  │
│  └──────────┘   └──────────┘   └───────────┘   └────────┘  │
│                                                             │
│  GET /documents, GET /documents/{id}, DELETE /documents/{id}│
│  GET /health                                                │
└─────────────────────────────────────────────────────────────┘
          │
┌─────────▼──────────┐         ┌─────────────────────┐
│    Qdrant Cloud    │         │   PostgreSQL (Docker) │
│  (vectores +       │         │  (metadata de docs)   │
│   payloads)        │         └─────────────────────┘
└────────────────────┘
```

---

## Módulos implementados

### 1. `app/core/config.py` — Configuración centralizada

**Qué hace**: Lee todas las variables de entorno y las expone como un objeto Python con tipado.

```python
class Settings(BaseSettings):
    GEMINI_API_KEY: str = ""
    QDRANT_URL: str = ""
    QDRANT_COLLECTION: str = "chunks"
    MAX_FILE_SIZE_MB: int = 20
    UPLOAD_DIR: str = "./uploads"
    # ... etc
```

**Por qué importa**: usar `pydantic-settings` garantiza que la app arranque con un error claro si falta una variable de entorno crítica, en lugar de fallar silenciosamente en runtime.

**Cómo se usa**: se importa el singleton `settings` en cualquier parte de la app.

```python
from app.core.config import settings
max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
```

---

### 2. `app/core/exceptions.py` — Excepciones HTTP personalizadas

**Qué hace**: define subclases de `HTTPException` con mensajes estandarizados para los errores del dominio.

| Clase | HTTP Status | Cuándo se usa |
|-------|------------|---------------|
| `InvalidFileError` | 400 | Tipo o tamaño inválido |
| `DocumentNotFoundError` | 404 | `GET`/`DELETE` de un doc inexistente |
| `DocumentProcessingError` | 409 | Doc ya en procesamiento |
| `ExternalServiceError` | 503 | Gemini/Cohere/Qdrant no disponible |

---

### 3. `app/db/` — Base de datos relacional

#### `db/base.py`

Declara la clase `Base` de SQLAlchemy de la que heredan todos los modelos. También importa los modelos para que Alembic pueda detectarlos al generar migraciones:

```python
class Base(DeclarativeBase):
    pass

import app.models.document  # hace visible el modelo para alembic autogenerate
```

#### `db/session.py`

Crea el **engine** (conexión a PostgreSQL) y la **session factory** usada en toda la aplicación:

```python
engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

`expire_on_commit=False` significa que los objetos cargados de la DB siguen accesibles después de un `commit()` sin necesidad de hacer otra query. Esto es importante en el pipeline de ingesta donde se actualiza el mismo objeto varias veces.

---

### 4. `app/models/document.py` — Modelo de base de datos

Representa la tabla `documents` en PostgreSQL:

```
documents
├── id          UUID (PK, generado por Python con uuid4)
├── filename    TEXT    "contrato.pdf"
├── file_type   TEXT    "pdf" | "docx" | "txt"
├── file_size   INTEGER bytes
├── status      TEXT    "pending" | "processing" | "ready" | "error"
├── error_msg   TEXT    mensaje si status = "error", null en otros casos
├── chunk_count INTEGER cuántos fragmentos se generaron
├── page_count  INTEGER páginas del PDF (null para DOCX/TXT)
├── created_at  TIMESTAMP con timezone, default NOW()
└── updated_at  TIMESTAMP con timezone, se actualiza automáticamente
```

`CheckConstraint` garantiza en la DB que `file_type` y `status` solo acepten los valores permitidos, como segunda línea de defensa después de la validación en el endpoint.

---

### 5. `app/schemas/document.py` — Schemas de API (Pydantic)

Definen la forma de los datos que entran y salen de la API:

**`DocumentCreate`** — campos necesarios para crear un registro (uso interno, no expuesto directamente).

**`DocumentResponse`** — lo que el cliente recibe en `GET /documents` y `GET /documents/{id}`:
```json
{
  "id": "uuid",
  "filename": "contrato.pdf",
  "file_type": "pdf",
  "file_size": 204800,
  "status": "ready",
  "chunk_count": 42,
  "page_count": 12,
  "created_at": "2026-01-15T10:30:00Z",
  "updated_at": "2026-01-15T10:35:00Z"
}
```

**`DocumentUploadResponse`** — respuesta inmediata al subir un archivo (202):
```json
{
  "document_id": "uuid",
  "filename": "contrato.pdf",
  "status": "pending"
}
```

`model_config = {"from_attributes": True}` permite construir el schema directamente desde un objeto SQLAlchemy sin conversión manual.

---

### 6. `app/services/ingestion/parsers/` — Parsers de archivo

Cada parser recibe un `Path` al archivo y retorna una lista de tuplas `(numero_de_pagina, texto)`. El número de página es `None` para formatos que no tienen páginas (DOCX, TXT).

#### `parsers/pdf.py` — Parser PDF con PyMuPDF

```python
def parse(file_path: Path) -> list[tuple[int | None, str]]:
    doc = fitz.open(str(file_path))
    for i in range(len(doc)):
        page = doc.load_page(i)
        text = page.get_text()
        if text.strip():
            pages.append((i + 1, text))  # páginas base-1
```

**Por qué PyMuPDF**: es la librería más rápida y completa para extracción de texto de PDFs en Python. Extrae el texto real del PDF (no OCR), lo que es instantáneo y muy preciso.

**Limitación conocida**: PDFs escaneados (imágenes de texto) no tienen texto extraíble y disparan `ValueError("PDF sin texto extraíble")`.

#### `parsers/docx.py` — Parser Word

```python
def parse(file_path: Path) -> list[tuple[int | None, str]]:
    doc = Document(str(file_path))
    text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [(None, text)]
```

Une todos los párrafos no vacíos con doble salto de línea. El doble `\n\n` es importante porque el chunker lo usa como señal de "cortar el chunk preferentemente aquí".

#### `parsers/txt.py` — Parser texto plano

```python
def parse(file_path: Path) -> list[tuple[int | None, str]]:
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = file_path.read_text(encoding="latin-1")
    return [(None, content)]
```

Intenta UTF-8 primero y cae a Latin-1 si falla. Útil para archivos legacy con codificaciones antiguas.

#### `parser.py` — Orquestador

```python
def parse(file_path: Path, file_type: str) -> list[tuple[int | None, str]]:
    if file_type == "pdf":   return pdf.parse(file_path)
    if file_type == "docx":  return docx.parse(file_path)
    if file_type == "txt":   return txt.parse(file_path)
    raise ValueError(f"Tipo de archivo no soportado: {file_type!r}")
```

Un único punto de entrada que delega al parser correcto según el tipo. El pipeline solo llama a este orquestador, sin saber qué parser específico se usa.

---

### 7. `app/services/ingestion/chunker.py` — SmartChunker

Este es el componente más sofisticado del pipeline de ingesta. El chunking (dividir el texto en fragmentos) es crítico para la calidad del RAG.

#### Dataclass `Chunk`

Representa un fragmento de texto listo para ser embedido e indexado:

```python
@dataclass
class Chunk:
    document_id: str    # UUID del documento padre
    chunk_index: int    # posición del chunk dentro del documento (0, 1, 2...)
    text: str           # texto del fragmento
    page_number: int | None  # página de inicio (solo PDFs)
    start_char: int     # posición de inicio en el texto completo
    end_char: int       # posición de fin en el texto completo
    filename: str = ""  # nombre del archivo (se setea en el pipeline)
```

#### `SmartChunker`

**Parámetros por defecto** (definidos en el SPEC):
- `chunk_size = 800` tokens (~palabras)
- `chunk_overlap = 150` tokens
- `min_chunk_size = 100` tokens

**Por qué overlapping**: si una idea importante cae justo en el límite entre dos chunks, sin overlap se perdería en ambos. Con overlap, las últimas `N` oraciones del chunk anterior se repiten al inicio del siguiente, garantizando que ningún contexto quede truncado.

#### Método principal: `split(pages, document_id)`

```
Flujo completo:
1. _join_pages()    — Une todas las páginas en un texto continuo,
                      guardando un mapa de "qué posición de carácter
                      corresponde a qué página"

2. _split_sentences() — Divide el texto en oraciones usando nltk.
                        Marca la primera oración de cada párrafo con
                        "\n\n" al inicio, para que el chunker la
                        prefiera como punto de corte

3. _compute_spans()   — Calcula la posición exacta (inicio, fin) de
                        cada oración dentro del texto completo

4. _build_chunks()    — Acumula oraciones hasta llegar a chunk_size,
                        luego retrocede chunk_overlap tokens para el
                        próximo chunk
```

#### `_build_chunks()` — Lógica de chunking con overlap

```
i = 0  ← inicio del chunk actual (índice en lista de oraciones)

MIENTRAS hay oraciones sin procesar:
  j = i
  tokens_acumulados = 0

  MIENTRAS j < total_oraciones:
    si la oración empieza con "\n\n" Y ya hay contenido → CORTAR
    tokens_acumulados += tokens(oracion[j])
    j++
    si tokens_acumulados >= chunk_size → CORTAR

  chunk_texto = join(oraciones[i:j])
  si tokens(chunk_texto) >= min_chunk_size:
    guardar Chunk

  # Calcular dónde empieza el próximo chunk (overlap)
  overlap_count = oraciones finales que suman >= chunk_overlap tokens
  next_i = j - overlap_count
  i = max(next_i, i + 1)  ← garantía de progreso para no loop infinito
```

**Invariante crítica**: `i` siempre avanza al menos 1 posición. Sin esto, si una sola oración supera `chunk_size`, el algoritmo quedaría en un loop infinito.

#### Helpers del chunker

**`_join_pages()`**: concatena páginas con `"\n\n"` entre ellas y construye `page_map`: una lista de intervalos `(char_inicio, char_fin, numero_pagina)`. Se usa después para saber en qué página cae el inicio de cada chunk.

**`_page_at(page_map, char_pos)`**: dado un offset de carácter en el texto completo, retorna el número de página correspondiente. Así el chunk sabe desde qué página viene.

**`_split_sentences()`**: usa `nltk.sent_tokenize` para dividir el texto en oraciones respetando puntuación real (no solo espacios). Descarga automáticamente el modelo `punkt_tab` de NLTK si no está instalado.

---

### 8. `app/services/retrieval/embedder.py` — GeminiEmbedder

**Qué es un embedding**: una representación numérica de un texto como un vector de 768 números. Textos con significado similar producen vectores que están "cerca" en el espacio vectorial, lo que permite búsqueda semántica.

```python
class GeminiEmbedder:
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._model = settings.GEMINI_EMBED_MODEL  # "models/text-embedding-004"
```

#### Métodos

**`embed_single(text: str) → list[float]`**

Embeds un solo texto usando `task_type="RETRIEVAL_QUERY"`. Se usa para embedir la pregunta del usuario en el pipeline de consulta.

**`embed_batch(texts: list[str]) → list[list[float]]`**

Embeds múltiples textos usando `task_type="RETRIEVAL_DOCUMENT"`. Se usa para embedir los chunks durante la ingesta. Procesa en lotes de 100 (límite de la API de Gemini).

**Por qué task_type diferente**: Gemini text-embedding-004 está optimizado para búsqueda asimétrica. Los documentos se indexan con `RETRIEVAL_DOCUMENT` y las queries se buscan con `RETRIEVAL_QUERY`. Esto mejora la calidad de los resultados de búsqueda.

#### Retry con backoff exponencial

Todos los llamados a la API usan `_call_with_retry()`:

```
Intento 1 → si falla, esperar 1s
Intento 2 → si falla, esperar 2s
Intento 3 → si falla, esperar 4s
Intento 4 → si falla, lanzar RuntimeError
```

Esto hace al sistema resiliente ante rate limits o cortes de red temporales.

Como la API de Gemini es síncrona, se ejecuta en un thread pool con `asyncio.to_thread()` para no bloquear el event loop de FastAPI.

---

### 9. `app/services/retrieval/vector_store.py` — QdrantVectorStore

**Qué es Qdrant**: una base de datos vectorial. Almacena vectores numéricos y permite buscar los N más similares a un vector de query (búsqueda por similitud semántica).

```python
class QdrantVectorStore:
    def __init__(self, url: str, api_key: str, collection_name: str):
        self._client = AsyncQdrantClient(url=url, api_key=api_key)
        self._collection = collection_name
```

#### Métodos

**`ensure_collection(vector_size=768)`**

Crea la colección "chunks" en Qdrant si no existe. Una colección es análoga a una tabla en SQL. Se usa distancia COSINE porque es la métrica estándar para similitud semántica de texto.

**`upsert(chunks, vectors)`**

Inserta o actualiza chunks en Qdrant. Cada punto tiene:
- **ID**: UUID determinístico generado como `uuid5(document_id + chunk_index)`. Esto hace las operaciones **idempotentes**: si el mismo chunk se inserta dos veces, actualiza el existente en lugar de duplicarlo.
- **Vector**: los 768 números del embedding.
- **Payload**: todos los campos del `Chunk` como JSON (document_id, text, page_number, filename, etc.).

Se procesa en batches de 100 para no saturar la API.

**`search(vector, filter_doc_ids=None, limit=10)`**

Busca los `limit` chunks más similares al vector dado. Si se especifican `filter_doc_ids`, solo busca dentro de esos documentos (filtro por `payload.document_id` usando `MatchAny`).

Retorna `list[ScoredPoint]` con la similitud de cada resultado.

**`delete_by_document(document_id)`**

Elimina todos los chunks de un documento dado usando un filtro sobre `payload.document_id`. Se usa cuando el usuario borra un documento.

**`health_check() → bool`**

Verifica que Qdrant responde. Si lanza cualquier excepción retorna `False`.

---

### 10. `app/services/ingestion/pipeline.py` — IngestionPipeline

El orquestador de todo el proceso de ingesta. Recibe un archivo y lo convierte en chunks indexados en Qdrant.

```python
class IngestionPipeline:
    def __init__(self, embedder: GeminiEmbedder, vector_store: QdrantVectorStore):
        self._embedder = embedder
        self._vector_store = vector_store
        self._chunker = SmartChunker()  # parámetros del SPEC: 800/150/100
```

#### `run(document_id, file_path, file_type, db)`

Flujo completo con manejo de errores:

```
a. DB: status → "processing"
        ↓
b. parse(file_path, file_type)
   → list[(page_num, text)]
        ↓
c. SmartChunker.split(pages, document_id)
   → list[Chunk]
   (también se setea chunk.filename = doc.filename en cada chunk)
        ↓
d. GeminiEmbedder.embed_batch([chunk.text for chunk in chunks])
   → list[list[float]]
        ↓
e. QdrantVectorStore.upsert(chunks, vectors)
   chunks_uploaded = True  ← bandera para el cleanup de errores
        ↓
f. DB: status → "ready", chunk_count = N,
       page_count = max(page_numbers)  (o None si es DOCX/TXT)
```

#### Manejo de errores en el pipeline

Si cualquier paso falla:

```python
except Exception as exc:
    logger.error(..., exc_info=True)   # log con traceback completo

    await db.rollback()                # limpia la transacción pendiente

    # Actualiza el estado en DB usando SQL directo (no ORM)
    # porque después de rollback() los objetos ORM quedan expirados
    await db.execute(
        update(Document).where(Document.id == doc_uuid).values(
            status="error",
            error_msg=str(exc)[:2000],
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    # Si ya se habían subido chunks a Qdrant, los eliminamos
    # para no dejar datos huérfanos
    if chunks_uploaded:
        await vector_store.delete_by_document(document_id)
```

**Por qué SQL directo después del rollback**: SQLAlchemy marca los objetos ORM como "expirados" (sus datos en memoria son descartados) después de un `rollback()`. Acceder a `doc.status` después del rollback dispararía un lazy load, que falla en contexto async. Usar `update()` de SQLAlchemy core evita este problema.

#### Cleanup del archivo temporal

```python
finally:
    file_path.unlink(missing_ok=True)  # siempre, éxito o error
```

El archivo temporal se borra siempre al final, sin importar si el pipeline tuvo éxito o falló.

---

### 11. `app/api/deps.py` — Dependencias compartidas

Define funciones que FastAPI inyecta automáticamente en los endpoints:

**`get_db()`** — generador async que abre y cierra una sesión de DB por request:
```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

**`get_embedder()`**, **`get_vector_store()`**, **`get_pipeline()`** — singletons con `@lru_cache(maxsize=1)`:
```python
@lru_cache(maxsize=1)
def get_embedder() -> GeminiEmbedder:
    return GeminiEmbedder()
```

`@lru_cache(maxsize=1)` garantiza que la instancia se crea una sola vez en toda la vida del proceso. Crear el cliente de Qdrant o configurar Gemini tiene un costo; hacerlo por cada request sería innecesario e ineficiente.

---

### 12. `app/api/routers/documents.py` — Endpoints de documentos

#### `POST /api/v1/documents/upload`

```
1. Validar que file.filename tiene extensión pdf/docx/txt
2. Leer todo el contenido del archivo en memoria
3. Validar que no supera MAX_FILE_SIZE_MB (default: 20 MB)
4. Crear registro Document en DB con status="pending"
5. Escribir archivo en UPLOAD_DIR/{document_id}_{filename}
6. Agregar _run_ingestion como BackgroundTask
7. Retornar 202 con document_id, filename, status
```

El `202 Accepted` significa "recibí tu pedido, lo estoy procesando". El cliente debe hacer polling a `GET /documents/{id}` para saber cuándo terminó.

**`_run_ingestion(document_id, file_path, file_type)`** — función helper que:
1. Crea su propia sesión de DB (independiente de la del request, que ya se cerró)
2. Llama a `pipeline.run()`

```python
async def _run_ingestion(document_id, file_path, file_type):
    pipeline = get_pipeline()
    async with AsyncSessionLocal() as db:
        await pipeline.run(document_id, file_path, file_type, db)
```

#### `GET /api/v1/documents/`

Retorna todos los documentos ordenados por `created_at DESC` (el más reciente primero). Mapea el resultado de la query SQLAlchemy al schema `DocumentResponse` via `from_attributes=True`.

#### `GET /api/v1/documents/{document_id}`

Busca el documento por UUID. Retorna 404 si no existe.

**Para qué sirve el polling**: el frontend llama a este endpoint cada 2 segundos para saber si el procesamiento terminó. Cuando `status` cambia a `"ready"` o `"error"`, deja de hacer polling.

#### `DELETE /api/v1/documents/{document_id}`

1. Verifica que el documento existe (404 si no)
2. Llama `vector_store.delete_by_document()` — elimina todos los chunks de Qdrant
3. Elimina el registro de la DB
4. Retorna 204 No Content

El orden importa: se borra Qdrant primero. Si la DB falla después, podemos reintentar el delete de DB. Si fuera al revés (DB primero), podría quedar data huérfana en Qdrant sin forma de identificarla.

---

### 13. `app/api/routers/health.py` — Health check

```python
@router.get("/health")
async def health_check(db, vector_store):
    # verifica PostgreSQL
    await db.execute(text("SELECT 1"))

    # verifica Qdrant
    qdrant_ok = await vector_store.health_check()

    return {"status": "ok", "db": "connected", "qdrant": "connected"}
```

Usado por Docker healthchecks y por monitoring externo para saber si el servicio está operativo.

---

### 14. `app/main.py` — Entrada de la aplicación FastAPI

```python
app = FastAPI(title="RAG-Pipeline", version="0.1.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], ...)

app.include_router(health.router,    prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(query.router,     prefix="/api/v1")
```

CORS configurado para el frontend en Vite (puerto 5173). `lifespan` inicializa el sistema de logging al arrancar.

---

## Tests

### Unit tests (`tests/unit/`)

Prueban lógica pura sin dependencias externas ni base de datos.

**`test_chunker.py`**: verifica que el `SmartChunker`:
- Genera un solo chunk para texto corto
- Genera múltiples chunks con overlap correcto para texto largo
- Descarta chunks que no llegan al mínimo de tokens
- Preserva el número de página correcto para cada chunk

**`test_parsers.py`**: verifica que cada parser:
- PDF: retorna lista de (página, texto) con número de página base-1
- DOCX: retorna texto concatenado de todos los párrafos no vacíos
- TXT: retorna contenido raw, con fallback a Latin-1

### Integration tests (`tests/integration/test_ingestion_pipeline.py`)

Prueban el flujo completo de los endpoints HTTP con mocks de servicios externos.

**Infraestructura de test**:
- **SQLite en archivo temporal** con `NullPool`: permite que el request y el background task abran sesiones independientes sin deadlock.
- **`AsyncMock` para Gemini y Qdrant**: ningún test hace llamadas reales a APIs externas.
- **Mock de `parse()`**: los parsers reales se testean en unit tests; aquí se simula su salida.
- **Dos niveles de override**: `app.dependency_overrides` para los `Depends()` de FastAPI + `patch()` para las llamadas directas en `documents.py`.

**Por qué los background tasks ya terminaron cuando el test hace el GET**: Starlette ejecuta `await self.background()` dentro del ciclo ASGI antes de retornar. Con `ASGITransport` (httpx), esto significa que `await client.post(...)` solo retorna cuando el background task completó.

| Test | Qué verifica |
|------|-------------|
| `test_upload_pdf_exitoso` | 202 + status "ready" tras background task |
| `test_upload_tipo_invalido` | `.exe` → 400 |
| `test_upload_muy_grande` | Archivo > MAX_FILE_SIZE_MB → 400 |
| `test_list_documentos` | 2 uploads → lista con 2 items ordenados |
| `test_delete_documento` | 204 + Qdrant notificado + GET posterior 404 |
| `test_pipeline_error_marca_documento` | Embedder falla → doc.status="error" |

---

## Flujo de datos completo (ingesta)

```
Cliente                  FastAPI              Background Task
  │                         │                       │
  │  POST /upload (PDF)      │                       │
  ├────────────────────────→ │                       │
  │                         │ validar ext/tamaño    │
  │                         │ crear Document (DB)   │
  │                         │ guardar archivo       │
  │                         │ add_task(_run_ingest) │
  │  202 + document_id       │                       │
  ←─────────────────────── │                       │
  │                         │                       │ status → "processing"
  │                         │                       │ parse() → pages
  │  GET /documents/{id}     │                       │ split() → chunks
  ├────────────────────────→ │                       │ embed_batch() → vectors
  │  {"status":"processing"} │                       │ upsert() → Qdrant
  ←─────────────────────── │                       │ status → "ready"
  │                         │                       │ borrar archivo temp
  │  GET /documents/{id}     │                       │
  ├────────────────────────→ │                       │
  │  {"status":"ready",      │                       │
  │   "chunk_count":42}      │                       │
  ←─────────────────────── │                       │
```

---

## Decisiones de diseño destacadas

**BackgroundTasks de FastAPI en lugar de Celery**: el procesamiento de documentos es asíncrono pero no necesita workers separados. FastAPI `BackgroundTasks` es suficiente para este scope y elimina la necesidad de Redis como broker.

**IDs determinísticos en Qdrant**: los chunks se identifican con `uuid5(document_id + chunk_index)`. Si el mismo documento se procesa dos veces (retry), los puntos se actualizan en lugar de duplicarse.

**El pipeline solo conoce sus dependencias, no cómo se crean**: `IngestionPipeline` recibe `embedder` y `vector_store` como parámetros. Esto facilita testear con mocks sin tocar el código de producción.

**`NullPool` en tests de integración**: `StaticPool` (una sola conexión compartida) causaría un deadlock porque el request tiene su sesión abierta mientras el background task intenta abrir otra. `NullPool` crea conexiones independientes.

---

## Qué falta implementar (próximas fases)

- **`services/retrieval/reranker.py`**: wrapper de Cohere Rerank para re-ordenar los resultados de Qdrant por relevancia real.
- **`services/generation/llm.py`**: wrapper de Gemini 2.5 Flash para generar respuestas.
- **`services/generation/prompt_builder.py`**: construye el prompt con los chunks como contexto.
- **`services/generation/citation_parser.py`**: extrae los marcadores `[1]`, `[2]` de la respuesta y los mapea a los chunks reales.
- **`api/routers/query.py`**: endpoint `POST /query` que orquesta todo el pipeline de consulta.
- **Frontend**: React + Vite + Tailwind con chat UI, drag-and-drop y visualización de citas.
