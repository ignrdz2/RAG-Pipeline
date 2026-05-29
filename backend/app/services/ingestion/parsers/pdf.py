from pathlib import Path

import fitz  # PyMuPDF


def parse(file_path: Path) -> list[tuple[int | None, str]]:
    doc = fitz.open(str(file_path))
    pages: list[tuple[int | None, str]] = []

    for i in range(len(doc)):
        page = doc.load_page(i)
        text = page.get_text()
        if text.strip():
            pages.append((i + 1, text))

    doc.close()

    if not pages:
        raise ValueError("PDF sin texto extraíble")

    return pages
