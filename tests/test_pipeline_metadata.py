"""issue #2: новые lifecycle-поля проходят через adapter pipeline в GAR
без потери значений, включая нормализацию select-поля lifecycle_stage."""
from __future__ import annotations

from src.adapter.pipeline import _METADATA_KEYS, _normalize_payload


def test_metadata_keys_include_adr0002_fields():
    for key in ("date_indexed", "lifecycle_stage", "comorbidity_tags", "reviewed_by"):
        assert key in _METADATA_KEYS


def test_normalize_payload_keeps_lifecycle_stage_and_empty_text_fields():
    mapping = {"lifecycle_stage": {"prenatal": "prenatal", "unspecified": "unspecified"}}
    payload = {
        "title": "doc",
        "lifecycle_stage": "prenatal",
        "comorbidity_tags": "",
        "reviewed_by": "",
        "date_indexed": "2026-09-14",
    }
    result = _normalize_payload(payload, mapping)
    assert result["lifecycle_stage"] == "prenatal"
    assert result["comorbidity_tags"] == ""
    assert result["reviewed_by"] == ""
    assert result["date_indexed"] == "2026-09-14"


def test_normalize_payload_drops_unknown_lifecycle_stage():
    mapping = {"lifecycle_stage": {"prenatal": "prenatal"}}
    payload = {"lifecycle_stage": "not_a_real_stage"}
    result = _normalize_payload(payload, mapping)
    assert "lifecycle_stage" not in result
