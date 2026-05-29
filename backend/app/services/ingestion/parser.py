from pathlib import Path

from app.services.ingestion.parsers import docx, pdf, txt


def parse(file_path: Path, file_type: str) -> list[tuple[int | None, str]]:
    if file_type == "pdf":
        return pdf.parse(file_path)
    if file_type == "docx":
        return docx.parse(file_path)
    if file_type == "txt":
        return txt.parse(file_path)
    raise ValueError(f"Tipo de archivo no soportado: {file_type!r}")
