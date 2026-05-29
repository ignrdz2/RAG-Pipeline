# SPEC.md — RAG Pipeline con Documentos

> Fuente de verdad del proyecto. Toda decisión de arquitectura, diseño y flujo está documentada acá.

---

## 1. Visión del Proyecto

Trata de un sistema RAG (Retrieval-Augmented Generation) que permite subir documentos (PDF, DOCX, TXT), indexarlos semánticamente y consultarlos en lenguaje natural. Las respuestas citan exactamente qué documento y qué fragmento las respalda.

### Objetivos

- Demostrar dominio del stack RAG completo (ingesta → embeddings → retrieval → reranking → generación)
- Implementar diferenciadores reales que separen el proyecto de tutoriales: chunking inteligente, reranking con cross-encoder, y citación exacta con número de página
- Frontend pulido y demo-ready que impresione en entrevistas
- Código organizado como lo haría un equipo profesional: separación de responsabilidades, testeable, deployable

### Nombre del proyecto

`RAG-Pipeline` — repositorio, carpetas y referencias internas usan este nombre.

---

## 2. Stack Tecnológico

### Backend

| Componente    | Tecnología                       | Justificación                                              |
| ------------- | -------------------------------- | ---------------------------------------------------------- |
| Framework     | FastAPI                          | Async nativo, tipado con Pydantic, OpenAPI automático      |
| Runtime       | Python 3.11+                     | Match con librerías de ML                                  |
| LLM           | Google Gemini 2.5 Flash          | 1.500 req/día gratis, sin tarjeta de crédito               |
| Embeddings    | Google Gemini Embedding          | 1.500 req/día gratis, MTEB 68.32                           |
| Reranker      | Cohere Rerank 3.5                | 1.000 req/mes gratis, cubre pipeline RAG completo          |
| Vector DB     | Qdrant Cloud                     | Free tier permanente, mejor DX que pgvector para este caso |
| DB relacional | SQLite (dev) / PostgreSQL (prod) | Metadata de documentos, usuarios, jobs                     |
| ORM           | SQLAlchemy 2.x + Alembic         | Migrations versionadas, async support                      |
| Task queue    | FastAPI BackgroundTasks          | Procesamiento async de documentos sin overhead de Celery   |
| Parser PDF    | PyMuPDF (fitz)                   | Extracción de texto + número de página                     |
| Parser DOCX   | python-docx                      | Soporte nativo de Word                                     |
| Validación    | Pydantic v2                      | Schemas estrictos en toda la API                           |
| Testing       | pytest + pytest-asyncio          | Tests unitarios e integración                              |
| Linting       | ruff + mypy                      | Calidad de código consistente                              |

### Frontend

| Componente    | Tecnología                   | Justificación                              |
| ------------- | ---------------------------- | ------------------------------------------ |
| Framework     | React 18 + Vite              | HMR rápido, ecosistema maduro              |
| Lenguaje      | TypeScript                   | Tipado estricto, mejor DX                  |
| Estilos       | Tailwind CSS                 | Mismo stack que Text-to-SQL, consistencia  |
| Estado global | Zustand                      | Más simple que Redux para este scope       |
| Data fetching | TanStack Query (React Query) | Cache, loading states, refetch automático  |
| HTTP client   | Axios                        | Interceptors para manejo global de errores |
| UI Components | shadcn/ui                    | Componentes accesibles, customizables      |
| Upload        | react-dropzone               | Drag & drop con validación                 |
| Markdown      | react-markdown               | Renderizado de respuestas del LLM          |
| Testing       | Vitest + Testing Library     | Tests de componentes                       |

### Infraestructura

| Componente       | Tecnología                                           |
| ---------------- | ---------------------------------------------------- |
| Containerización | Docker + Docker Compose                              |
| Entorno          | Local únicamente (la app está preparada para deploy) |
| Variables de env | `.env` local (`.env.example` versionado en git)      |

> **Nota de deploy:** la app está estructurada para ser deployable sin cambios de código. Cuando se quiera publicar: backend en Render o Railway, frontend en Vercel, variables de entorno en los dashboards de cada plataforma. No se implementa CI/CD por ahora.

---

## 3. Arquitectura del Sistema

```
┌──────────────────────────────────────────────────────────────┐
│                     FRONTEND (React + TS)                    │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │  Upload UI  │  │  Doc Library │  │     Chat UI         │ │
│  │  drag&drop  │  │  + estados   │  │  + fuentes citadas  │ │
│  └──────┬──────┘  └──────┬───────┘  └──────────┬──────────┘ │
└─────────┼────────────────┼─────────────────────┼────────────┘
          │                │                     │  HTTP/REST
┌─────────▼────────────────▼─────────────────────▼────────────┐
│                     BACKEND (FastAPI)                        │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │                   API Layer (Routers)                │    │
│  │  /documents  |  /query  |  /health                  │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌─────────────────────┐  ┌────────────────────────────┐    │
│  │  Ingestion Service  │  │      Query Service         │    │
│  │                     │  │                            │    │
│  │  1. Parse (PDF/DOCX/│  │  1. Embed pregunta         │    │
│  │     TXT)            │  │  2. Vector search (top 10) │    │
│  │  2. Chunk intelig.  │  │  3. Rerank (top 3)         │    │
│  │  3. Embed chunks    │  │  4. Build prompt            │    │
│  │  4. Store en Qdrant │  │  5. LLM genera respuesta   │    │
│  │  5. Guardar metadata│  │  6. Parsear citas           │    │
│  └──────────┬──────────┘  └────────────┬───────────────┘    │
│             │                          │                     │
│  ┌──────────▼──────────┐  ┌────────────▼───────────────┐    │
│  │   Embedding Service │  │    LLM Service             │    │
│  │   (Gemini Embed)    │  │    (Gemini 2.5 Flash)      │    │
│  └──────────┬──────────┘  └────────────┬───────────────┘    │
│             │                          │                     │
│  ┌──────────▼──────────┐  ┌────────────▼───────────────┐    │
│  │   Rerank Service    │  │   Citation Parser          │    │
│  │   (Cohere Rerank)   │  │                            │    │
│  └─────────────────────┘  └────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
          │                                    │
┌─────────▼──────────┐            ┌────────────▼───────────┐
│    Qdrant Cloud    │            │       SQLite/PG         │
│  (vectores +       │            │  (documentos, jobs,     │
│   chunks raw)      │            │   metadatos)            │
└────────────────────┘            └────────────────────────┘
```

---

## 4. Estructura de Carpetas

```
docmind/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── deps.py               # Dependencias compartidas (DB session, etc.)
│   │   │   └── routers/
│   │   │       ├── documents.py      # Upload, list, delete
│   │   │       ├── query.py          # Chat/query endpoint
│   │   │       └── health.py         # Health check
│   │   ├── core/
│   │   │   ├── config.py             # Settings con pydantic-settings
│   │   │   ├── logging.py            # Configuración de logging
│   │   │   └── exceptions.py         # Custom exceptions
│   │   ├── db/
│   │   │   ├── base.py               # Base declarativa de SQLAlchemy
│   │   │   ├── session.py            # Engine y session factory
│   │   │   └── migrations/           # Alembic migrations
│   │   ├── models/
│   │   │   ├── document.py           # Modelo Document (SQLAlchemy)
│   │   │   └── chunk.py              # Modelo Chunk (SQLAlchemy)
│   │   ├── schemas/
│   │   │   ├── document.py           # Pydantic schemas (request/response)
│   │   │   └── query.py              # Pydantic schemas para query/response
│   │   ├── services/
│   │   │   ├── ingestion/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── parser.py         # Orquesta parsers por tipo de archivo
│   │   │   │   ├── parsers/
│   │   │   │   │   ├── pdf.py        # PyMuPDF, extrae texto + página
│   │   │   │   │   ├── docx.py       # python-docx
│   │   │   │   │   └── txt.py        # Built-in
│   │   │   │   ├── chunker.py        # Chunking con overlap inteligente
│   │   │   │   └── pipeline.py       # Orquesta parse → chunk → embed → store
│   │   │   ├── retrieval/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── embedder.py       # Wrapper Gemini Embedding
│   │   │   │   ├── vector_store.py   # Wrapper Qdrant
│   │   │   │   └── reranker.py       # Wrapper Cohere Rerank
│   │   │   └── generation/
│   │   │       ├── __init__.py
│   │   │       ├── llm.py            # Wrapper Gemini 2.5 Flash
│   │   │       ├── prompt_builder.py # Construye prompts con contexto
│   │   │       └── citation_parser.py# Extrae y estructura citas del output
│   │   └── main.py                   # App FastAPI, lifespan, CORS, routers
│   ├── tests/
│   │   ├── unit/
│   │   │   ├── test_chunker.py
│   │   │   ├── test_citation_parser.py
│   │   │   └── test_parsers.py
│   │   └── integration/
│   │       ├── test_ingestion_pipeline.py
│   │       └── test_query_endpoint.py
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.ts             # Instancia Axios con interceptors
│   │   │   ├── documents.ts          # Endpoints de documentos
│   │   │   └── query.ts              # Endpoint de query
│   │   ├── components/
│   │   │   ├── upload/
│   │   │   │   ├── DropZone.tsx      # Drag & drop
│   │   │   │   └── UploadProgress.tsx
│   │   │   ├── documents/
│   │   │   │   ├── DocumentCard.tsx
│   │   │   │   └── DocumentList.tsx
│   │   │   ├── chat/
│   │   │   │   ├── ChatInput.tsx
│   │   │   │   ├── MessageBubble.tsx
│   │   │   │   ├── CitationChip.tsx  # Chip clickeable que muestra fragmento
│   │   │   │   └── SourceViewer.tsx  # Panel con fragmento resaltado
│   │   │   └── ui/                   # shadcn/ui re-exports
│   │   ├── hooks/
│   │   │   ├── useDocuments.ts       # TanStack Query para documentos
│   │   │   └── useChat.ts            # Estado del chat
│   │   ├── store/
│   │   │   └── chat.ts               # Zustand: mensajes, doc seleccionados
│   │   ├── types/
│   │   │   └── index.ts              # Tipos TypeScript globales
│   │   ├── lib/
│   │   │   └── utils.ts              # cn(), formatters
│   │   ├── pages/
│   │   │   └── Home.tsx              # Layout principal (single page)
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── Dockerfile
│   ├── package.json
│   └── vite.config.ts
│
├── docker-compose.yml
├── .github/
│   └── workflows/
│       └── ci.yml
└── README.md
```

---

## 5. Modelos de Datos

### SQLite/PostgreSQL

```sql
-- Tabla principal de documentos
CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename    TEXT NOT NULL,
    file_type   TEXT NOT NULL CHECK (file_type IN ('pdf', 'docx', 'txt')),
    file_size   INTEGER NOT NULL,               -- bytes
    status      TEXT NOT NULL DEFAULT 'pending' -- pending | processing | ready | error
                CHECK (status IN ('pending', 'processing', 'ready', 'error')),
    error_msg   TEXT,                           -- null si no hay error
    chunk_count INTEGER DEFAULT 0,
    page_count  INTEGER,                        -- null para txt/docx sin paginación
    created_at  TIMESTAMP DEFAULT now(),
    updated_at  TIMESTAMP DEFAULT now()
);
```

### Qdrant — Colección `chunks`

```json
{
  "vector": [0.12, -0.45, ...],        // 768 dimensiones (Gemini Embedding)
  "payload": {
    "document_id": "uuid",
    "chunk_index": 0,                  // índice dentro del documento
    "text": "texto del fragmento...",
    "page_number": 3,                  // null para txt/docx
    "filename": "contrato.pdf",
    "start_char": 1240,               // posición en el texto original
    "end_char": 1680
  }
}
```

---

## 6. API Contract

### `POST /api/v1/documents/upload`

**Request:** `multipart/form-data`

```
file: File  (PDF | DOCX | TXT, max 20MB)
```

**Response 202:**

```json
{
  "document_id": "uuid",
  "filename": "contrato.pdf",
  "status": "pending"
}
```

El procesamiento ocurre en background. El cliente hace polling a `/documents/{id}` hasta que `status === "ready"`.

---

### `GET /api/v1/documents`

**Response 200:**

```json
[
  {
    "id": "uuid",
    "filename": "contrato.pdf",
    "file_type": "pdf",
    "file_size": 204800,
    "status": "ready",
    "chunk_count": 42,
    "page_count": 12,
    "created_at": "2026-01-15T10:30:00Z"
  }
]
```

---

### `GET /api/v1/documents/{id}`

Mismo schema que el item de la lista. Usado para polling de estado.

---

### `DELETE /api/v1/documents/{id}`

Elimina el documento de SQLite **y** todos sus chunks de Qdrant.

**Response 204:** No content.

---

### `POST /api/v1/query`

**Request:**

```json
{
  "question": "¿Cuáles son las condiciones de rescisión del contrato?",
  "document_ids": ["uuid1", "uuid2"], // vacío = busca en todos
  "top_k": 3 // chunks a usar (default 3, max 5)
}
```

**Response 200:**

```json
{
  "answer": "Las condiciones de rescisión se encuentran en la cláusula 8...",
  "sources": [
    {
      "document_id": "uuid1",
      "filename": "contrato.pdf",
      "chunk_text": "Cláusula 8: Cualquiera de las partes podrá...",
      "page_number": 7,
      "relevance_score": 0.94
    }
  ],
  "model_used": "gemini-2.5-flash",
  "processing_time_ms": 1240
}
```

---

### `GET /api/v1/health`

```json
{
  "status": "ok",
  "qdrant": "connected",
  "db": "connected"
}
```

---

## 7. Lógica de Negocio Crítica

### 7.1 Chunking Inteligente

El chunker **no** corta cada N caracteres. Respeta estructura semántica:

```
Parámetros:
  chunk_size:    800 tokens  (target)
  chunk_overlap: 150 tokens  (overlap entre chunks consecutivos)
  min_chunk:     100 tokens  (descartar chunks muy pequeños)

Algoritmo:
  1. Dividir texto en oraciones usando nltk.sent_tokenize
  2. Acumular oraciones hasta acercarse a chunk_size
  3. Al crear un nuevo chunk, incluir las últimas N oraciones
     del chunk anterior (overlap)
  4. Preservar saltos de párrafo como puntos de corte
     preferidos (no cortar un párrafo a la mitad si se puede
     evitar)
  5. Para PDFs: mantener referencia a la página de inicio
     del chunk (la página donde empieza la primera oración)
```

Por qué importa: sin overlap, una respuesta que cruza el límite entre dos chunks se pierde. Con overlap, el contexto siempre está disponible.

---

### 7.2 Pipeline de Ingesta

```
upload() → background_task(pipeline(document_id))

pipeline(document_id):
  1. Cambiar status → "processing"
  2. Parsear archivo según tipo:
       PDF  → PyMuPDF: [(page_num, text), ...]
       DOCX → python-docx: texto concatenado
       TXT  → open().read()
  3. Chunker.split(text) → List[Chunk]
  4. Embedder.embed_batch(chunks) → List[vector]
     (batch de 100 chunks máximo por llamada API)
  5. VectorStore.upsert(chunks + vectors)
  6. Actualizar documento: status → "ready", chunk_count = N
  7. En caso de excepción en cualquier paso:
       status → "error", error_msg = str(e)
       Limpiar chunks de Qdrant si ya se habían insertado
```

---

### 7.3 Pipeline de Query

```
query(question, document_ids, top_k):
  1. Embedder.embed(question) → vector
  2. VectorStore.search(
       vector=vector,
       filter={"document_id": {"any": document_ids}},  // si hay filtro
       limit=10   // siempre traer 10 para reranking
     ) → List[ScoredChunk]
  3. Reranker.rerank(
       query=question,
       documents=[chunk.text for chunk in scored_chunks],
       top_n=top_k   // reducir a top_k después de reranking
     ) → List[RankedChunk]
  4. PromptBuilder.build(question, ranked_chunks) → prompt
  5. LLM.generate(prompt) → raw_answer
  6. CitationParser.parse(raw_answer, ranked_chunks) → QueryResponse
```

---

### 7.4 Sistema de Citación

El LLM recibe un prompt que le instruye a citar usando marcadores `[1]`, `[2]`, etc., donde cada número corresponde a un chunk del contexto. El `CitationParser` luego convierte esos marcadores en objetos `Source` con metadata real.

**Prompt template:**

```
Sos un asistente experto en análisis de documentos.
Respondé la pregunta basándote ÚNICAMENTE en los fragmentos
de documentos provistos. Si la información no está en los
fragmentos, decilo explícitamente.

Al citar información, usá el marcador [N] donde N es el
número del fragmento. Podés usar múltiples marcadores en
la misma oración si la información viene de varios fragmentos.

FRAGMENTOS:
[1] (contrato.pdf, página 7): "Cláusula 8: Cualquiera de las partes..."
[2] (contrato.pdf, página 8): "La rescisión deberá notificarse..."
[3] (anexo.pdf, página 2): "Los plazos establecidos son..."

PREGUNTA: {question}

RESPUESTA:
```

**Output esperado del LLM:**

```
Las condiciones de rescisión [1] establecen que cualquiera de las partes
puede rescindir el contrato. La notificación debe hacerse [2] con al menos
30 días de anticipación. Los plazos pueden modificarse [3] según lo acordado
en el anexo.
```

El `CitationParser` extrae las referencias `[N]`, las mapea a los chunks correspondientes, y construye el array `sources` de la respuesta.

---

### 7.5 Manejo de Errores

**Reglas generales:**

- Todos los errores del backend retornan JSON `{"detail": "mensaje"}` con el HTTP status correcto
- Los errores durante la ingesta se loguean y se marcan en el documento, nunca se propagan al usuario como 500
- Los errores de API externas (Gemini, Cohere, Qdrant) tienen retry con backoff exponencial (máx 3 intentos)

**Códigos de error:**

```
400 — Archivo inválido (tipo no soportado, demasiado grande, corrupto)
404 — Documento no encontrado
409 — Documento ya está siendo procesado
422 — Parámetros de query inválidos
503 — Servicio externo no disponible (Gemini, Cohere, Qdrant)
```

---

## 8. Frontend — Diseño y UX

### Layout

Single Page Application con dos paneles principales:

```
┌────────────────────────────────────────────────────┐
│  DocMind                              [Upload Doc] │  ← Header
├──────────────────┬─────────────────────────────────┤
│                  │                                 │
│  📄 contrato.pdf │  ┌─────────────────────────────┐│
│  ✅ ready · 42ch │  │ ¿En qué puedo ayudarte?     ││
│                  │  └─────────────────────────────┘│
│  📄 anexo.docx   │                                 │
│  ⏳ processing   │  [Usuario]: ¿Cuáles son las     │
│                  │  condiciones de rescisión?       │
│  📄 manual.txt   │                                 │
│  ✅ ready · 18ch │  [AI]: Las condiciones [1][2]   │
│                  │  establecen que...               │
│                  │                                 │
│                  │  ┌──────────────────────────┐   │
│                  │  │ [1] contrato.pdf · p.7   │   │
│                  │  │ "Cláusula 8: Cualquiera..│   │
│                  │  └──────────────────────────┘   │
│                  │                                 │
│                  │  ┌─────────────────────────────┐│
│                  │  │ Escribí tu pregunta...   [→] ││
│                  │  └─────────────────────────────┘│
└──────────────────┴─────────────────────────────────┘
```

### Estados de documentos

| Estado       | Visual en sidebar                    |
| ------------ | ------------------------------------ |
| `pending`    | Ícono gris, sin chips                |
| `processing` | Spinner animado, barra de progreso   |
| `ready`      | Check verde, chip con # de chunks    |
| `error`      | X roja, tooltip con mensaje de error |

### Interacciones clave

- **Upload:** drag & drop sobre el sidebar o botón "Upload Doc". Muestra nombre, tamaño, y preview de ícono por tipo. Progress bar durante el procesamiento.
- **Selección de documentos:** checkboxes en el sidebar para filtrar qué documentos incluir en la query. Por default: todos los que están `ready`.
- **Citaciones:** los marcadores `[1]`, `[2]` en las respuestas son chips clickeables que expanden un panel lateral con el fragmento completo resaltado.
- **Estado de carga:** skeleton loaders mientras se espera la respuesta, typing indicator animado.

---

## 9. Variables de Entorno

### Backend (`.env.example`)

```env
# App
APP_ENV=development          # development | production
APP_PORT=8000
LOG_LEVEL=INFO

# Database
DATABASE_URL=sqlite:///./docmind.db

# Qdrant
QDRANT_URL=https://xxxx.qdrant.io
QDRANT_API_KEY=your_key_here
QDRANT_COLLECTION=chunks

# Google Gemini
GEMINI_API_KEY=your_key_here
GEMINI_LLM_MODEL=gemini-2.5-flash
GEMINI_EMBED_MODEL=models/text-embedding-004

# Cohere
COHERE_API_KEY=your_key_here

# Upload
MAX_FILE_SIZE_MB=20
UPLOAD_DIR=./uploads
```

### Frontend (`.env.example`)

```env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

---

## 10. Tests

### Estrategia

- **Unit tests** para lógica de negocio pura: chunker, citation parser, parsers de archivo
- **Integration tests** para los endpoints principales usando `httpx.AsyncClient` y mocks de servicios externos
- No testear wrappers de API externas (Gemini, Cohere, Qdrant) — mockear en tests de integración

### Tests obligatorios

```
tests/unit/
  test_chunker.py
    ✓ chunk de texto corto genera un solo chunk
    ✓ chunk largo genera múltiples con overlap correcto
    ✓ respeta límite mínimo de chunk_min
    ✓ chunks de PDF mantienen referencia a página

  test_citation_parser.py
    ✓ parsea [1] y [2] correctamente
    ✓ maneja respuesta sin citas
    ✓ ignora marcadores fuera de rango

  test_parsers.py
    ✓ PDF con texto retorna lista de (página, texto)
    ✓ DOCX retorna texto concatenado
    ✓ TXT retorna contenido raw

tests/integration/
  test_ingestion_pipeline.py
    ✓ upload PDF → status pending → processing → ready
    ✓ upload archivo inválido → 400
    ✓ delete documento elimina chunks de Qdrant

  test_query_endpoint.py
    ✓ query con documentos listos retorna respuesta con sources
    ✓ query con document_ids vacío busca en todos
    ✓ query sin documentos indexados retorna error claro
```

---

## 11. Entorno Local con Docker

Todo corre con un solo comando:

```bash
docker compose up --build
```

### `docker-compose.yml` — servicios

```yaml
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app # hot reload en desarrollo
      - uploads_data:/app/uploads
    env_file: ./backend/.env
    depends_on:
      - db

  frontend:
    build: ./frontend
    ports:
      - "5173:5173"
    volumes:
      - ./frontend/src:/app/src # hot reload en desarrollo
    env_file: ./frontend/.env
    depends_on:
      - backend

  db:
    image: postgres:16-alpine # PostgreSQL desde el inicio en Docker
    environment:
      POSTGRES_DB: docmind
      POSTGRES_USER: docmind
      POSTGRES_PASSWORD: docmind
    volumes:
      - pg_data:/var/lib/postgresql/data
    ports:
      - "5432:5432" # expuesto para inspección con DBeaver/psql

volumes:
  pg_data:
  uploads_data:
```

> **Nota:** se usa PostgreSQL directamente en Docker (no SQLite) para que el entorno local sea idéntico a producción. La conexión es `postgresql://docmind:docmind@db:5432/docmind`.

### Comandos útiles

```bash
# Levantar todo
docker compose up --build

# Solo backend (si el frontend ya está corriendo)
docker compose up backend

# Correr migrations
docker compose exec backend alembic upgrade head

# Correr tests
docker compose exec backend pytest tests/ -v

# Linting
docker compose exec backend ruff check .
docker compose exec backend mypy app/

# Ver logs del backend
docker compose logs -f backend

# Resetear base de datos
docker compose down -v && docker compose up --build
```

### Preparado para deploy

Cuando se quiera publicar, no se necesita cambiar código:

- **Backend** → Render o Railway: apuntar al `Dockerfile` del backend, setear variables de entorno en el dashboard
- **Frontend** → Vercel: apuntar al `Dockerfile` del frontend o build directo con `npm run build`
- **DB** → Supabase o Render PostgreSQL: cambiar `DATABASE_URL` en las env vars
- **Qdrant** → ya usa Qdrant Cloud, no cambia nada

---

## 12. Plan de Desarrollo

### Fase 1 — Ingesta (Semana 1)

- [ ] Setup del proyecto: estructura de carpetas, pyproject.toml, Dockerfile
- [ ] Modelos SQLAlchemy + migrations Alembic
- [ ] Parser PDF (PyMuPDF), DOCX (python-docx), TXT
- [ ] Chunker con overlap inteligente
- [ ] Wrapper Qdrant (crear colección, upsert, search, delete)
- [ ] Wrapper Gemini Embedding (embed_single, embed_batch)
- [ ] Pipeline de ingesta completo + background task
- [ ] Endpoints: `POST /upload`, `GET /documents`, `GET /documents/{id}`, `DELETE /documents/{id}`
- [ ] Unit tests de chunker y parsers

### Fase 2 — Query Engine (Semana 2)

- [ ] Wrapper Gemini LLM
- [ ] Wrapper Cohere Rerank
- [ ] PromptBuilder con template de citación
- [ ] CitationParser
- [ ] Pipeline de query completo
- [ ] Endpoint: `POST /query`
- [ ] Integration tests de query
- [ ] Manejo de errores y retry logic

### Fase 3 — Frontend (Semanas 3-4)

- [ ] Setup React + Vite + Tailwind + shadcn/ui
- [ ] API client con Axios + interceptors
- [ ] TanStack Query hooks para documentos
- [ ] DropZone con validación y progress
- [ ] DocumentList con estados visuales y polling
- [ ] ChatInput + MessageBubble con Markdown
- [ ] CitationChip + SourceViewer
- [ ] Zustand store para estado del chat
- [ ] Diseño pulido: tipografía, colores, animaciones, responsive

### Fase 4 — Polish y cierre (Días finales)

- [ ] Docker Compose completo y funcional con un solo `docker compose up`
- [ ] Migrations corriendo automáticamente al iniciar el backend
- [ ] README con instrucciones de setup local (variables de entorno, comandos)
- [ ] Demo GIF o screenshots para el portfolio
- [ ] docs/ARCHITECTURE.md (versión pública del SPEC, sin notas internas)

---

## 13. Decisiones de Diseño y Trade-offs

| Decisión                                 | Alternativa descartada | Razón                                                                                             |
| ---------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------- |
| FastAPI BackgroundTasks para ingesta     | Celery + Redis         | Menor overhead, suficiente para este scope. Celery requiere Redis como broker.                    |
| PostgreSQL en Docker desde el inicio     | SQLite en dev          | El entorno local replica producción exactamente. Docker elimina la fricción de instalar Postgres. |
| Qdrant Cloud                             | pgvector en Supabase   | Mejor DX para RAG puro. pgvector requiere más configuración manual de índices.                    |
| Polling para estado de documento         | WebSockets             | Menor complejidad. El procesamiento tarda 5-30s, polling cada 2s es suficiente.                   |
| sentence-transformers local (descartado) | Gemini Embedding       | Gemini free tier cubre el caso de uso sin costo de cómputo local.                                 |
| top_k=10 para búsqueda, top_n=3 para LLM | top_k=3 directo        | El reranking necesita candidatos suficientes para ser efectivo.                                   |
| Zustand                                  | Redux Toolkit          | El estado global es simple (mensajes + docs seleccionados). Redux es overkill.                    |

---

## 14. Limitaciones Conocidas

- **Rate limits:** Gemini Embedding (1.500/día) y Cohere Rerank (1.000/mes) limitan el uso intensivo. Suficiente para demo y desarrollo.
- **Sin auth:** el proyecto no implementa autenticación de usuarios. Todos los documentos son compartidos. Agregar auth es una extensión natural post-MVP.
- **Archivos escaneados:** PDFs escaneados sin texto seleccionable no son soportados (requieren OCR con Tesseract, fuera de scope).
- **Tamaño máximo:** 20MB por archivo. Documentos más grandes requieren streaming de parseo.
- **Sin historial de chat:** cada query es independiente. El LLM no recuerda preguntas anteriores de la sesión.

---

_Última actualización: inicio del proyecto_
_Stack verificado: Mayo 2026_
