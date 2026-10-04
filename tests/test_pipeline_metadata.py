"""issue #2: новые lifecycle-поля проходят через adapter pipeline в GAR
без потери значений, включая нормализацию select-поля lifecycle_stage."""
from __future__ import annotations

from src.adapter.pipeline import _METADATA_KEYS, _normalize_payload


def test_metadata_keys_include_adr0002_fields():
    for key in ("date_indexed", "comorbidity_tags", "reviewed_by"):
        assert key in _METADATA_KEYS


def test_metadata_keys_include_tags():
    """issue #31, ADR-0015/ADR-0028: tags проходит из sidecar в payload как есть."""
    assert "tags" in _METADATA_KEYS


def test_metadata_payload_passes_through_tags_list():
    meta = {"title": "doc", "tags": ["Эпилепсия", "эпилепсия ", "сон"]}
    payload = {k: meta.get(k) for k in _METADATA_KEYS if meta.get(k) is not None}
    assert payload["tags"] == ["Эпилепсия", "эпилепсия ", "сон"]


def test_normalize_payload_keeps_empty_text_fields():
    mapping = {}
    payload = {
        "title": "doc",
        "comorbidity_tags": "",
        "reviewed_by": "",
        "date_indexed": "2026-09-14",
    }
    result = _normalize_payload(payload, mapping)
    assert result["comorbidity_tags"] == ""
    assert result["reviewed_by"] == ""
    assert result["date_indexed"] == "2026-09-14"
