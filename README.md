# RAG-Pipeline

Sistema de preguntas y respuestas sobre documentos propios. Subís un PDF, DOCX o TXT; el sistema lo procesa automáticamente; luego hacés preguntas en lenguaje natural y recibís respuestas que citan exactamente qué fragmento del documento las respalda.

---

## Qué hace

1. **Subís un documento** → el sistema lo parsea, lo divide en fragmentos y los indexa semánticamente.
2. **Hacés una pregunta** → el sistema busca los fragmentos más relevantes, los re-rankea y le pide a un LLM que genere una respuesta basada únicamente en esos fragmentos.
3. **La respuesta incluye citas** → cada afirmación lleva un marcador `[1]`, `[2]`, etc., que enlaza al fragmento exacto del documento original, incluyendo número de página para PDFs.

---

## Stack

| Capa | Tecnología |
|------|-----------|
| API | FastAPI (Python 3.11) |
| LLM | Google Gemini 2.5 Flash |
| Embeddings | Google Gemini text-embedding-004 |
| Reranker | Cohere Rerank 3.5 |
| Base vectorial | Qdrant Cloud |
| Base relacional | PostgreSQL 16 |
| ORM | SQLAlchemy 2 + Alembic |
| Contenedores | Docker + Docker Compose |

---

## Requisitos

- Docker y Docker Compose instalados
- Cuentas gratuitas en:
  - [Google AI Studio](https://aistudio.google.com) → `GEMINI_API_KEY`
  - [Qdrant Cloud](https://cloud.qdrant.io) → `QDRANT_URL` + `QDRANT_API_KEY`
  - [Cohere](https://cohere.com) → `COHERE_API_KEY`

---

## Levantar el proyecto

### 1. Clonar y configurar variables de entorno

```bash
git clone <repo-url>
cd RAG-Pipeline
cp backend/.env.example backend/.env
```

Editá `backend/.env` con tus claves:

```env
GEMINI_API_KEY=tu_clave_aqui
QDRANT_URL=https://xxxx.qdrant.io
QDRANT_API_KEY=tu_clave_aqui
COHERE_API_KEY=tu_clave_aqui
```

### 2. Levantar con Docker

```bash
docker compose up --build
```

Esto levanta el backend (puerto 8000) y PostgreSQL (puerto 5432).

### 3. Correr las migraciones de base de datos

```bash
docker compose exec backend alembic upgrade head
```

Solo es necesario la primera vez (o cuando haya nuevas migraciones).

### 4. Verificar que todo funciona

```bash
curl http://localhost:8000/api/v1/health
```

Respuesta esperada:
```json
{"status": "ok", "db": "connected", "qdrant": "connected"}
```

---

## API

### Subir un documento

```bash
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@/ruta/al/archivo.pdf"
```

Responde `202` inmediatamente. El procesamiento ocurre en background.

### Ver estado del documento

```bash
curl http://localhost:8000/api/v1/documents/{document_id}
```

El campo `status` pasa de `pending` → `processing` → `ready` (o `error`).

### Listar todos los documentos

```bash
curl http://localhost:8000/api/v1/documents/
```

### Eliminar un documento

```bash
curl -X DELETE http://localhost:8000/api/v1/documents/{document_id}
```

Elimina el documento de la base de datos y sus fragmentos de Qdrant.

### Hacer una consulta

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "¿Cuáles son las condiciones de rescisión?",
    "document_ids": [],
    "top_k": 3
  }'
```

`document_ids` vacío busca en todos los documentos indexados.

---

## Correr los tests

```bash
# Todos los tests
docker compose exec backend pytest tests/ -v

# Solo unit tests
docker compose exec backend pytest tests/unit/ -v

# Solo integration tests
docker compose exec backend pytest tests/integration/ -v
```

Los tests de integración usan SQLite en memoria y mocks de todos los servicios externos; no requieren conexión a Gemini, Qdrant ni Cohere.

---

## Comandos útiles

```bash
# Ver logs del backend en tiempo real
docker compose logs -f backend

# Linting
docker compose exec backend ruff check .

# Type checking
docker compose exec backend mypy app/

# Resetear base de datos (borra todos los datos)
docker compose down -v && docker compose up --build
docker compose exec backend alembic upgrade head
```

---

## Estructura de carpetas

```
RAG-Pipeline/
├── backend/
│   ├── app/
│   │   ├── api/            # Endpoints y dependencias
│   │   ├── core/           # Config, logging, exceptions
│   │   ├── db/             # Engine, sesiones, base declarativa
│   │   ├── models/         # Modelos SQLAlchemy
│   │   ├── schemas/        # Schemas Pydantic
│   │   └── services/
│   │       ├── ingestion/  # Parsers, chunker, pipeline
│   │       └── retrieval/  # Embedder, vector store, reranker (TODO)
│   ├── tests/
│   │   ├── unit/           # Tests de lógica pura (chunker, parsers)
│   │   └── integration/    # Tests de endpoints con mocks
│   ├── pyproject.toml
│   └── .env.example
├── docker-compose.yml
├── SPEC.md                 # Fuente de verdad del proyecto
└── docs/
    └── INGESTION.md        # Documentación técnica detallada
```

---

## Límites conocidos

- **Rate limits**: Gemini Embedding (1.500 req/día), Cohere Rerank (1.000 req/mes). Suficiente para desarrollo y demos.
- **Sin autenticación**: todos los documentos son accesibles para cualquier usuario.
- **PDFs escaneados**: no soportados (requieren OCR). Solo PDFs con texto seleccionable.
- **Tamaño máximo**: 20 MB por archivo.
- **Sin historial de chat**: cada consulta es independiente.

---

## Documentación técnica

Ver [docs/INGESTION.md](docs/INGESTION.md) para una explicación detallada de cada módulo, clase y función implementada.
