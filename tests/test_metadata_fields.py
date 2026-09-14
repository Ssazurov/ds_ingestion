"""issue #2: lifecycle-поля (date_indexed/category/lifecycle_stage/
comorbidity_tags/reviewed_by) регистрируются в доменной схеме GAR."""
from __future__ import annotations

from src.gar_client.metadata_fields import _TEXT_FIELDS, ensure_domain_schema

DS_SEARCH_ROOT = "/home/vector/projects/ds/ds_search"


class FakeClient:
    def __init__(self):
        self.calls = []

    def ensure_metadata_field(self, dataset_id, key, label, value_type, required, options=None):
        self.calls.append((key, value_type, required, tuple(options or ())))
        return {"id": key, "options": []}


def test_text_fields_include_new_optional_keys():
    keys = {k: required for k, _, required in _TEXT_FIELDS}
    for key in ("date_indexed", "comorbidity_tags", "reviewed_by"):
        assert key in keys
        assert keys[key] is False, f"{key} must be optional per ADR-0002"


def test_ensure_domain_schema_registers_lifecycle_stage_select():
    client = FakeClient()
    ensure_domain_schema(client, "ds-1", DS_SEARCH_ROOT)
    by_key = {c[0]: c for c in client.calls}
    assert by_key["lifecycle_stage"][1] == "select"
    assert "unspecified" in by_key["lifecycle_stage"][3]
    for key in ("date_indexed", "comorbidity_tags", "reviewed_by"):
        assert by_key[key][1] == "text"
        assert by_key[key][2] is False
