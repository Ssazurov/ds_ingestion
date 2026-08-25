"""Валидация допустимых форматов перед загрузкой в GAR (issue #5).

gar-docling-intake принимает только .pdf/.md/.docx (AGENTS.md GAR п.8).
ds_search сейчас отдаёт только .md (Crawl4AI markdown) — конвертация
других форматов (.html/.doc и т.п.) не входит в MVP-скоуп issue #5, но
модуль — единая точка, куда её добавить, не трогая pipeline.py.
"""
from __future__ import annotations

from pathlib import Path

ALLOWED_EXTENSIONS = {".pdf", ".md", ".docx"}


class UnsupportedFormatError(ValueError):
    """Формат файла не входит в ALLOWED_EXTENSIONS и не может быть загружен."""


def ensure_allowed_format(path: Path) -> Path:
    """Возвращает path, если формат допустим, иначе бросает исключение."""
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"{path.name}: unsupported extension {path.suffix} "
            f"(allowed: {sorted(ALLOWED_EXTENSIONS)})"
        )
    return path
