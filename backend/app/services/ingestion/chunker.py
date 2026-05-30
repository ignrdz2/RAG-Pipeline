from dataclasses import dataclass


@dataclass
class Chunk:
    document_id: str
    chunk_index: int
    text: str
    page_number: int | None
    start_char: int
    end_char: int


def _token_count(text: str) -> int:
    """Aproximación de tokens como palabras separadas por espacios."""
    return len(text.split())


def _sent_tokenize(text: str) -> list[str]:
    import nltk

    try:
        return nltk.sent_tokenize(text)
    except LookupError:
        nltk.download("punkt_tab", quiet=True)
        return nltk.sent_tokenize(text)


class SmartChunker:
    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        min_chunk_size: int = 100,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    # API pública

    def split(
        self, pages: list[tuple[int | None, str]], document_id: str
    ) -> list[Chunk]:
        full_text, page_map = self._join_pages(pages)
        if not full_text.strip():
            return []

        sentences = self._split_sentences(full_text)
        if not sentences:
            return []

        sentence_spans = self._compute_spans(full_text, sentences)
        return self._build_chunks(sentences, sentence_spans, page_map, document_id)

    # Lógica principal de chunking

    def _build_chunks(
        self,
        sentences: list[str],
        sentence_spans: list[tuple[int, int]],
        page_map: list[tuple[int, int, int | None]],
        document_id: str,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        chunk_index = 0
        i = 0  # inicio del chunk actual (índice en la lista de oraciones)

        while i < len(sentences):
            # Acumular oraciones hasta alcanzar chunk_size
            j = i
            current_tokens = 0

            while j < len(sentences):
                sent = sentences[j]
                sent_tokens = _token_count(sent)

                # Límite de párrafo → preferir cortar aquí si ya hay contenido
                if current_tokens > 0 and sent.startswith("\n\n"):
                    break

                current_tokens += sent_tokens
                j += 1

                if current_tokens >= self.chunk_size:
                    break

            # No se consumió ninguna oración (no debería ocurrir en condiciones normales)
            if j == i:
                i += 1
                continue

            chunk_sents = sentences[i:j]
            text = " ".join(s.strip() for s in chunk_sents).strip()
            tokens = _token_count(text)

            if tokens >= self.min_chunk_size:
                start_char = sentence_spans[i][0]
                end_char = sentence_spans[j - 1][1]
                page_number = self._page_at(page_map, start_char)

                chunks.append(
                    Chunk(
                        document_id=document_id,
                        chunk_index=chunk_index,
                        text=text,
                        page_number=page_number,
                        start_char=start_char,
                        end_char=end_char,
                    )
                )
                chunk_index += 1

            # Avanzar i para el próximo chunk
            if j >= len(sentences):
                # Se consumieron todas las oraciones → terminar, no hace falta overlap
                break

            # Retroceder desde j por chunk_overlap tokens.
            # INVARIANTE: el próximo i debe ser estrictamente mayor al actual
            # para garantizar progreso sin importar el largo del texto.
            overlap_count = self._overlap_count(chunk_sents)
            next_i = j - overlap_count
            i = max(next_i, i + 1)

        return chunks

    # Helpers

    def _join_pages(
        self, pages: list[tuple[int | None, str]]
    ) -> tuple[str, list[tuple[int, int, int | None]]]:
        """Concatena los textos de cada página y devuelve (full_text, page_map).

        page_map: lista de intervalos (start_char, end_char, page_number).
        """
        parts: list[str] = []
        page_map: list[tuple[int, int, int | None]] = []
        offset = 0

        for page_num, text in pages:
            if not text:
                continue
            start = offset
            parts.append(text)
            offset += len(text)
            page_map.append((start, offset, page_num))
            # Separador entre páginas para que las oraciones no se mezclen
            parts.append("\n\n")
            offset += 2

        return "".join(parts), page_map

    def _split_sentences(self, text: str) -> list[str]:
        """Divide el texto en oraciones marcando la primera de cada párrafo."""
        paragraphs = text.split("\n\n")
        sentences: list[str] = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            sents = _sent_tokenize(para)
            for j, s in enumerate(sents):
                # La primera oración de cada párrafo (salvo el primero) recibe
                # el prefijo \n\n para que el chunker prefiera cortar ahí.
                sentences.append(("\n\n" + s) if (j == 0 and sentences) else s)

        return sentences

    def _compute_spans(
        self, full_text: str, sentences: list[str]
    ) -> list[tuple[int, int]]:
        """Mapea cada oración a su offset (inicio, fin) en full_text."""
        spans: list[tuple[int, int]] = []
        cursor = 0

        for sent in sentences:
            needle = sent.strip()
            pos = full_text.find(needle, cursor)
            if pos == -1:
                pos = cursor  # fallback: anclar a la posición actual
            end = pos + len(needle)
            spans.append((pos, end))
            cursor = end

        return spans

    def _overlap_count(self, sents: list[str]) -> int:
        """Cantidad de oraciones finales que juntas cubren chunk_overlap tokens."""
        tokens = 0
        count = 0
        for sent in reversed(sents):
            tokens += _token_count(sent)
            count += 1
            if tokens >= self.chunk_overlap:
                break
        return count

    def _page_at(
        self, page_map: list[tuple[int, int, int | None]], char_pos: int
    ) -> int | None:
        for start, end, page_num in page_map:
            if start <= char_pos < end:
                return page_num
        return page_map[-1][2] if page_map else None
