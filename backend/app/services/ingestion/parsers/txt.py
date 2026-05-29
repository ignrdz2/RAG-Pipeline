from pathlib import Path


def parse(file_path: Path) -> list[tuple[int | None, str]]:
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = file_path.read_text(encoding="latin-1")
    return [(None, content)]
