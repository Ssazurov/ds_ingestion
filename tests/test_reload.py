"""issue #8, ADR-0007: reload_document -- update-in-place по gar_document_id,
diff со старой записью (preserve ручных правок), state не трогается при сбое."""
from __future__ import annotations

import json

import pytest

from src.adapter.reload import (
    ReloadError,
    ReloadValidationError,
    reload_document,
    resolve_source_doc_from_metadata,
)


class FakeClient:
    def __init__(self, existing_metadata: dict, fail_update: bool = False, fail_content: bool = False):
        self.existing_metadata = existing_metadata
        self.fail_update = fail_update
        self.fail_content = fail_content
        self.updated_with: dict | None = None
        self.content_path = None
        self.calls = []

    def list_metadata_fields(self, dataset_id):
        return {}

    def get_document(self, document_id):
        return {"document_id": document_id, "metadata": self.existing_metadata}

    def update_document_metadata(self, document_id, metadata):
        if self.fail_update:
            from src.gar_client.client import GarClientError
            raise GarClientError("boom")
        self.updated_with = metadata
        self.calls.append(("metadata", metadata))
        return {"document_id": document_id}

    def update_document_content(self, document_id, file_path):
        if self.fail_content:
            from src.gar_client.client import GarClientError
            raise GarClientError("boom-content")
        self.content_path = file_path
        self.calls.append(("content", file_path))
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


def test_resolve_source_doc_from_metadata_matches_source_url(tmp_path):
    raw_dir = tmp_path / "raw" / "family_support"
    raw_dir.mkdir(parents=True)
    (raw_dir / "doc1.json").write_text(
        json.dumps({"source_url": "https://example.test/doc", "title": "Title"}),
        encoding="utf-8",
    )

    assert resolve_source_doc_from_metadata(
        tmp_path / "raw", {"source_url": "https://example.test/doc"}
    ) == ("family_support", "doc1")


def test_recrawl_preserves_manual_fields_and_ignores_null(tmp_path):
    import hashlib

    canonical = "https://example.test/doc"
    doc_id = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    source_dir = _write_source(tmp_path, doc_id, {
        "source_url": canonical, "title": "Old", "reviewed_by": "editor",
    })
    state_path = _write_state(tmp_path, {doc_id: "gar-1"})
    staged = tmp_path / "staged"
    staged.mkdir()
    content = staged / f"{doc_id}.md"
    content.write_text("fresh", encoding="utf-8")
    metadata = staged / f"{doc_id}.json"
    metadata.write_text("{}", encoding="utf-8")
    client = FakeClient(existing_metadata={"title": "Old", "reviewed_by": "editor", "note": "keep"})
    report = reload_document(
        client, "dataset-1", source_dir, state_path, doc_id,
        recrawl=lambda _url, _doc_id: {
                "doc_id": doc_id,
            "canonical_url": canonical, "content_path": str(content),
            "metadata_path": str(metadata), "metadata": {"title": "Fresh", "note": None},
        },
    )
    assert report.preserved_fields == ["reviewed_by", "note"]
    assert client.updated_with["note"] == "keep"
    assert client.updated_with["title"] == "Fresh"
    assert [call[0] for call in client.calls] == ["metadata", "content"]


def test_recrawl_rejects_unstable_doc_id_without_gar_update(tmp_path):
    source_dir = _write_source(tmp_path, "doc1", {"source_url": "https://example.test/doc"})
    state_path = _write_state(tmp_path, {"doc1": "gar-1"})
    client = FakeClient(existing_metadata={})
    with pytest.raises(ReloadValidationError):
        reload_document(
            client, "dataset-1", source_dir, state_path, "doc1",
            recrawl=lambda _url, _doc_id: {
                "doc_id": "wrong", "canonical_url": "https://example.test/doc",
                "content_path": str(tmp_path / "missing.md"),
                "metadata_path": str(tmp_path / "missing.json"), "metadata": {},
            },
        )
    assert client.updated_with is None


def test_recrawl_allows_legacy_slug_doc_id(tmp_path):
    """ADR-0010 (амендмент ADR-0009 п.2, issue #26): identity -- canonical_url,
    не doc_id. Legacy doc_id -- slug, не sha256(canonical_url), и это ок."""
    canonical = "https://example.test/papa-solnechnogo-rebenka"
    doc_id = "papa-solnechnogo-rebenka-o-sebe-o-syne"
    source_dir = _write_source(tmp_path, doc_id, {"source_url": canonical, "title": "Old"})
    state_path = _write_state(tmp_path, {doc_id: "gar-1"})
    staged = tmp_path / "staged"
    staged.mkdir()
    content = staged / f"{doc_id}.md"
    content.write_text("fresh", encoding="utf-8")
    metadata = staged / f"{doc_id}.json"
    metadata.write_text("{}", encoding="utf-8")
    staged_id = __import__("hashlib").sha256(canonical.encode()).hexdigest()[:16]
    client = FakeClient(existing_metadata={"title": "Old"})

    report = reload_document(
        client, "dataset-1", source_dir, state_path, doc_id,
        recrawl=lambda _url, _doc_id: {
            "doc_id": staged_id, "canonical_url": canonical,
            "content_path": str(content), "metadata_path": str(metadata),
            "metadata": {"title": "Fresh"},
        },
    )
    assert report.gar_document_id == "gar-1"
    assert client.updated_with["title"] == "Fresh"


def test_recrawl_rejects_canonical_url_drift(tmp_path):
    """Стабильность источника проверяется по canonical_url, не по doc_id."""
    old_canonical = "https://example.test/old-page"
    new_canonical = "https://example.test/new-page"
    doc_id = "some-slug"
    source_dir = _write_source(tmp_path, doc_id, {"source_url": old_canonical, "title": "Old"})
    state_path = _write_state(tmp_path, {doc_id: "gar-1"})
    staged_id = __import__("hashlib").sha256(new_canonical.encode()).hexdigest()[:16]
    client = FakeClient(existing_metadata={})
    with pytest.raises(ReloadValidationError):
        reload_document(
            client, "dataset-1", source_dir, state_path, doc_id,
            recrawl=lambda _url, _doc_id: {
                "doc_id": staged_id, "canonical_url": new_canonical,
                "content_path": str(tmp_path / "missing.md"),
                "metadata_path": str(tmp_path / "missing.json"), "metadata": {},
            },
        )
    assert client.updated_with is None


def test_recrawl_keeps_backup_when_content_replace_fails(tmp_path):
    import hashlib

    canonical = "https://example.test/doc"
    doc_id = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    source_dir = _write_source(tmp_path, doc_id, {
        "source_url": canonical, "title": "Old", "content_path": str(tmp_path / "source" / f"{doc_id}.md"),
    })
    old_content = source_dir / f"{doc_id}.md"
    old_content.write_text("old", encoding="utf-8")
    state_path = _write_state(tmp_path, {doc_id: "gar-1"})
    staged = tmp_path / "staged"
    staged.mkdir()
    new_content = staged / f"{doc_id}.md"
    new_content.write_text("new", encoding="utf-8")
    staged_meta = staged / f"{doc_id}.json"
    staged_meta.write_text("{}", encoding="utf-8")
    client = FakeClient(existing_metadata={"title": "Old"}, fail_content=True)

    with pytest.raises(ReloadError, match="content replace failed"):
        reload_document(client, "dataset-1", source_dir, state_path, doc_id,
                        recrawl=lambda *_: {
                            "doc_id": doc_id, "canonical_url": canonical,
                            "content_path": str(new_content), "metadata_path": str(staged_meta),
                            "metadata": {"title": "Fresh"},
                            "provenance": {"correlation_id": "corr-1"},
                        })

    backup = source_dir / ".reload-backups" / "corr-1"
    assert (backup / f"{doc_id}.json").read_text(encoding="utf-8")
    assert (backup / f"{doc_id}.md").read_text(encoding="utf-8") == "old"


def test_recrawl_marks_manual_recovery_when_metadata_rollback_fails(tmp_path):
    import hashlib

    canonical = "https://example.test/doc"
    doc_id = hashlib.sha256(canonical.encode()).hexdigest()[:16]
    source_dir = _write_source(tmp_path, doc_id, {
        "source_url": canonical, "title": "Old", "content_path": str(tmp_path / "source" / f"{doc_id}.md"),
    })
    old_content = source_dir / f"{doc_id}.md"
    old_content.write_text("old", encoding="utf-8")
    state_path = _write_state(tmp_path, {doc_id: "gar-1"})
    staged = tmp_path / "staged"
    staged.mkdir()
    new_content = staged / f"{doc_id}.md"
    new_content.write_text("new", encoding="utf-8")
    staged_meta = staged / f"{doc_id}.json"
    staged_meta.write_text("{}", encoding="utf-8")

    class RollbackFailClient(FakeClient):
        def __init__(self):
            super().__init__({"title": "Old"}, fail_content=True)
            self.metadata_calls = 0

        def update_document_metadata(self, document_id, metadata):
            self.metadata_calls += 1
            if self.metadata_calls == 2:
                from src.gar_client.client import GarClientError
                raise GarClientError("rollback unavailable")
            return super().update_document_metadata(document_id, metadata)

    client = RollbackFailClient()
    with pytest.raises(ReloadError, match="metadata rollback failed"):
        reload_document(client, "dataset-1", source_dir, state_path, doc_id,
                        recrawl=lambda *_: {
                            "doc_id": doc_id, "canonical_url": canonical,
                            "content_path": str(new_content), "metadata_path": str(staged_meta),
                            "metadata": {"title": "Fresh"},
                            "provenance": {"correlation_id": "corr-2"},
                        })
    marker = source_dir / ".reload-backups" / "corr-2" / "manual_recovery.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["status"] == "manual_recovery"
