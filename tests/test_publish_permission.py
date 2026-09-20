"""issue #35, ADR-0018: publish_permission в метаданных документа."""
from __future__ import annotations

from src.adapter.pipeline import (
    _METADATA_KEYS, _normalize_payload, apply_publish_permission_default,
)
from src.gar_client.metadata_fields import PUBLISH_PERMISSIONS, ensure_domain_schema

DS_SEARCH_ROOT = "/home/vector/projects/ds/ds_search"


class FakeClient:
    def __init__(self):
        self.calls = []

    def ensure_metadata_field(self, dataset_id, key, label, value_type, required, options=None):
        self.calls.append((key, value_type, required, tuple(options or ())))
        return {"id": key, "options": []}


def test_key_passes_through_pipeline():
    assert "publish_permission" in _METADATA_KEYS


def test_schema_registers_optional_select_with_four_options():
    client = FakeClient()
    ensure_domain_schema(client, "ds-1", DS_SEARCH_ROOT)
    by_key = {c[0]: c for c in client.calls}
    key, vtype, required, options = by_key["publish_permission"]
    assert vtype == "select" and required is False
    assert set(options) == {"not_set", "not_required", "granted", "denied"}
    assert options == tuple(PUBLISH_PERMISSIONS)


def test_default_is_not_set_when_missing():
    assert apply_publish_permission_default({"title": "x"})["publish_permission"] == "not_set"


def test_default_keeps_inherited_value():
    payload = {"publish_permission": "granted"}
    assert apply_publish_permission_default(payload)["publish_permission"] == "granted"


def test_invalid_value_dropped_then_not_set():
    mapping = {"publish_permission": {v: v for v in PUBLISH_PERMISSIONS}}
    payload = _normalize_payload({"publish_permission": "yes-please"}, mapping)
    assert "publish_permission" not in payload
    assert apply_publish_permission_default(payload)["publish_permission"] == "not_set"


def test_valid_value_normalized():
    mapping = {"publish_permission": {v: v for v in PUBLISH_PERMISSIONS}}
    assert _normalize_payload({"publish_permission": "Granted"}, mapping)["publish_permission"] == "granted"


def test_reload_preserves_manual_override_and_missing_key_does_not_reset():
    from src.adapter.reload import _merge_metadata
    # ручной override в GAR (denied) != sidecar (granted) -> сохраняется
    merged, changed, preserved = _merge_metadata(
        {"publish_permission": "denied"}, {"publish_permission": "granted"},
        {"publish_permission": "granted"},
    )
    assert merged["publish_permission"] == "denied" and "publish_permission" in preserved
    # sidecar без ключа: значение GAR не сбрасывается (дефолт в reload не ставится)
    merged, _, _ = _merge_metadata({"publish_permission": "granted"}, {}, {})
    assert merged["publish_permission"] == "granted"
