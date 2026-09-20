"""issue #33: reading_time_min = ceil(слов/200) только для doc_type=article."""
from __future__ import annotations

from src.adapter.pipeline import add_reading_time, compute_reading_time_min


def _md(tmp_path, words):
    p = tmp_path / "a.md"
    p.write_text(" ".join(["слово"] * words), encoding="utf-8")
    return p


def test_ceil_words_per_200(tmp_path):
    assert compute_reading_time_min(_md(tmp_path, 200)) == 1
    assert compute_reading_time_min(_md(tmp_path, 201)) == 2
    assert compute_reading_time_min(_md(tmp_path, 1000)) == 5


def test_article_gets_field_news_does_not(tmp_path):
    p = _md(tmp_path, 450)
    assert add_reading_time({"doc_type": "article"}, p)["reading_time_min"] == "3"
    assert "reading_time_min" not in add_reading_time({"doc_type": "news"}, p)
    assert "reading_time_min" not in add_reading_time({}, p)


def test_non_markdown_or_empty_skipped(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    assert compute_reading_time_min(pdf) is None
    assert compute_reading_time_min(_md(tmp_path, 0)) is None
    assert compute_reading_time_min(tmp_path / "missing.md") is None
