"""issue #8, ADR-0007: reload_document -- update-in-place по gar_document_id,
diff со старой записью (preserve ручных правок), state не трогается при сбое."""
from __future__ import annotations

import json

import pytest

from src.adapter.reload import ReloadError, reload_document


class FakeClient:
    def __init__(self, existing_metadata: dict, fail_update: bool = False, fail_content: bool = False):
        self.existing_metadata = existing_metadata
        self.fail_update = fail_update
        self.fail_content = fail_content
        self.updated_with: dict | None = None
        self.content_path = None

    def list_metadata_fields(self, dataset_id):
        return {}

    def get_document(self, document_id):
        return {"document_id": document_id, "metadata": self.existing_metadata}

    def update_document_metadata(self, document_id, metadata):
        if self.fail_update:
            from src.gar_client.client import GarClientError
            raise GarClientError("boom")
        self.updated_with = metadata
        return {"document_id": document_id}

    def update_document_content(self, document_id, file_path):
        if self.fail_content:
            from src.gar_client.client import GarClientError
            raise GarClientError("boom-content")
        self.content_path = file_path
        return {"document_id": document_id}


def _write_source(tmp_path, doc_id, meta):
    source_dir = tmp_path / "source"
    source_dir.mkdir(exist_ok=True)
    (source_dir / f"{doc_id}.json").write_text(json.dumps(meta), encoding="utf-8")
    return source_dir


def _write_state(tmp_path, state):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return state_path


def test_reload_preserves_manually_edited_fields_not_in_new_output(tmp_path):
    source_dir = _write_source(tmp_path, "doc1", {"title": "New Title", "content_path": "doc1.md"})
    state_path = _write_state(tmp_path, {"doc1": "gar-1"})
    client = FakeClient(existing_metadata={"title": "Old Title", "reviewed_by": "editor@x"})

    report = reload_document(client, "dataset-1", source_dir, state_path, "doc1")

    assert report.gar_document_id == "gar-1"
    assert client.updated_with == {"reviewed_by": "editor@x", "title": "New Title"}
    assert report.preserved_fields == ["reviewed_by"]
    assert report.changed_fields == {"title": "New Title"}
    assert report.content_replaced is True
    assert str(client.content_path) == "doc1.md"


def test_reload_content_replace_failure_wraps_client_error(tmp_path):
    source_dir = _write_source(tmp_path, "doc1", {"title": "T", "content_path": "doc1.md"})
    state_path = _write_state(tmp_path, {"doc1": "gar-1"})
    client = FakeClient(existing_metadata={}, fail_content=True)
    with pytest.raises(ReloadError, match="content replace failed"):
        reload_document(client, "dataset-1", source_dir, state_path, "doc1")


def test_reload_missing_source_file_raises(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    state_path = _write_state(tmp_path, {"doc1": "gar-1"})
    client = FakeClient(existing_metadata={})
    with pytest.raises(ReloadError, match="source doc not found"):
        reload_document(client, "dataset-1", source_dir, state_path, "doc1")


def test_reload_doc_id_not_in_state_raises(tmp_path):
    source_dir = _write_source(tmp_path, "doc1", {"title": "T"})
    state_path = _write_state(tmp_path, {})
    client = FakeClient(existing_metadata={})
    with pytest.raises(ReloadError, match="not in state"):
        reload_document(client, "dataset-1", source_dir, state_path, "doc1")


def test_reload_legacy_state_without_gar_document_id_raises(tmp_path):
    source_dir = _write_source(tmp_path, "doc1", {"title": "T"})
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(["doc1"]), encoding="utf-8")  # legacy list-формат
    client = FakeClient(existing_metadata={})
    with pytest.raises(ReloadError, match="no known gar_document_id"):
        reload_document(client, "dataset-1", source_dir, state_path, "doc1")


def test_reload_update_failure_does_not_raise_reloaderror_wraps_client_error(tmp_path):
    source_dir = _write_source(tmp_path, "doc1", {"title": "T"})
    state_path = _write_state(tmp_path, {"doc1": "gar-1"})
    client = FakeClient(existing_metadata={}, fail_update=True)
    with pytest.raises(ReloadError, match="update failed"):
        reload_document(client, "dataset-1", source_dir, state_path, "doc1")
