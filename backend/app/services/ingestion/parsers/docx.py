from pathlib import Path

from docx import Document


def parse(file_path: Path) -> list[tuple[int | None, str]]:
    doc = Document(str(file_path))
    text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [(None, text)]
