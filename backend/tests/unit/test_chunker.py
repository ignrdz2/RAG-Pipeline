from app.services.ingestion.chunker import Chunk, SmartChunker


def _words(n: int, word: str = "palabra") -> str:
    """Generate a string of exactly n words."""
    return " ".join([word] * n)


def _pages(text: str, page: int | None = None) -> list[tuple[int | None, str]]:
    return [(page, text)]


# Tests


def test_texto_corto_un_chunk() -> None:
    chunker = SmartChunker(chunk_size=800, chunk_overlap=150, min_chunk_size=10)
    pages = _pages(_words(50))

    chunks = chunker.split(pages, document_id="doc1")

    assert len(chunks) == 1
    assert chunks[0].document_id == "doc1"
    assert chunks[0].chunk_index == 0


def test_texto_largo_multiples_chunks() -> None:
    chunker = SmartChunker(chunk_size=100, chunk_overlap=20, min_chunk_size=10)
    
    text = " ".join(
        f"Esta es la oración número {i} y tiene suficientes palabras para el test."
        for i in range(50)
    )
    pages = _pages(text)

    chunks = chunker.split(pages, document_id="doc2")

    assert len(chunks) > 1
    for chunk in chunks:
        tokens = len(chunk.text.split())
        assert tokens <= chunker.chunk_size * 2, f"Chunk demasiado grande: {tokens}"


def test_overlap_correcto() -> None:
    chunker = SmartChunker(chunk_size=30, chunk_overlap=10, min_chunk_size=5)
    sentences = [
        "El gato estaba sentado tranquilamente sobre la alfombra roja de la sala.",
        "El perro corría velozmente por el parque verde lleno de árboles altos.",
        "El pájaro volaba alto en el cielo azul mientras cantaba una melodía.",
        "La tortuga caminaba despacio por el sendero de piedras del jardín.",
        "El pez nadaba en círculos dentro de la pecera redonda de vidrio.",
    ]
    text = " ".join(sentences)
    pages = _pages(text)

    chunks = chunker.split(pages, document_id="doc3")

    assert len(chunks) >= 2
    for i in range(len(chunks) - 1):
        words_end = set(chunks[i].text.split()[-15:])
        words_start = set(chunks[i + 1].text.split()[:15])
        assert words_end & words_start, (
            f"No hay overlap entre chunk {i} y {i + 1}\n"
            f"  fin    : {chunks[i].text[-80:]!r}\n"
            f"  inicio : {chunks[i + 1].text[:80]!r}"
        )


def test_chunk_minimo_descartado() -> None:
    chunker = SmartChunker(chunk_size=800, chunk_overlap=150, min_chunk_size=100)
    pages = _pages(_words(10))

    chunks = chunker.split(pages, document_id="doc4")

    assert chunks == []


def test_page_number_asignado() -> None:
    chunker = SmartChunker(chunk_size=40, chunk_overlap=5, min_chunk_size=5)
    # Simula un pdf de 2 paginas
    page1_text = " ".join(
        "La primera página contiene información relevante sobre contratos."
        for _ in range(8)
    )
    page2_text = " ".join(
        "La segunda página describe las condiciones de rescisión del acuerdo."
        for _ in range(8)
    )
    pages: list[tuple[int | None, str]] = [(1, page1_text), (2, page2_text)]

    chunks = chunker.split(pages, document_id="doc5")

    assert len(chunks) >= 2
    # Primer chunk debe venir de la página 1
    assert chunks[0].page_number == 1
    # Ultimo chunk debe venir de la página 2
    assert chunks[-1].page_number == 2


def test_chunk_index_secuencial() -> None:
    chunker = SmartChunker(chunk_size=30, chunk_overlap=5, min_chunk_size=5)
    text = " ".join(
        f"Oración {i} con contenido suficiente para generar varios chunks distintos."
        for i in range(20)
    )
    pages = _pages(text)

    chunks = chunker.split(pages, document_id="doc6")

    for expected_idx, chunk in enumerate(chunks):
        assert chunk.chunk_index == expected_idx


def test_start_end_char_coherentes() -> None:
    chunker = SmartChunker(chunk_size=800, chunk_overlap=150, min_chunk_size=10)
    text = _words(50)
    pages = _pages(text)

    chunks = chunker.split(pages, document_id="doc7")

    assert len(chunks) == 1
    c = chunks[0]
    assert c.start_char >= 0
    assert c.end_char > c.start_char


def test_input_sin_texto_retorna_vacio() -> None:
    chunker = SmartChunker()
    chunks = chunker.split([(None, "   ")], document_id="doc8")
    assert chunks == []
