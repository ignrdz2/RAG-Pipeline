import asyncio
import logging

import google.generativeai as genai

from app.core.config import settings

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100
_RETRY_DELAYS = (1.0, 2.0, 4.0)


class GeminiEmbedder:
    def __init__(self) -> None:
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._model = settings.GEMINI_EMBED_MODEL

    async def embed_single(self, text: str) -> list[float]:
        """Embeds una query usando task_type RETRIEVAL_QUERY."""
        batch = await self._call_with_retry([text], task_type="RETRIEVAL_QUERY")
        return batch[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embeds múltiples textos para indexación en batches de 100."""
        vectors: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch_texts = texts[i : i + _BATCH_SIZE]
            batch_vectors = await self._call_with_retry(
                batch_texts, task_type="RETRIEVAL_DOCUMENT"
            )
            vectors.extend(batch_vectors)
        return vectors

    async def _call_with_retry(
        self, texts: list[str], task_type: str
    ) -> list[list[float]]:
        last_exc: Exception | None = None
        for attempt, delay in enumerate(_RETRY_DELAYS):
            try:
                return await asyncio.to_thread(self._embed_sync, texts, task_type)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Gemini embed error (intento %d/%d): %s — reintentando en %.0fs",
                    attempt + 1,
                    len(_RETRY_DELAYS),
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
        # Último intento sin capturar
        try:
            return await asyncio.to_thread(self._embed_sync, texts, task_type)
        except Exception as exc:
            raise RuntimeError(
                f"Gemini embedding falló después de {len(_RETRY_DELAYS) + 1} intentos"
            ) from exc

    def _embed_sync(self, texts: list[str], task_type: str) -> list[list[float]]:
        # Pasar lista siempre para obtener list[list[float]] de vuelta
        result = genai.embed_content(
            model=self._model,
            content=texts,
            task_type=task_type,
        )
        embedding = result["embedding"]
        # Si el SDK devuelve list[float] (un solo texto), lo envolvemos
        if texts and not isinstance(embedding[0], list):
            return [embedding]
        return embedding  # type: ignore[return-value]
