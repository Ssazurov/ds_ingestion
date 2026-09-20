"""Reload одной статьи из существующего локального источника (issue #8,
ADR-0007): re-classify -> diff со старой записью GAR -> update-in-place по
gar_document_id (metadata PATCH + content PUT, issue #11).

gar-core-api PR #317 добавил PUT /ingestion/documents/{document_id}/content
(update-in-place, id сохраняется). reload_document теперь всегда вызывает
update_document_content() после успешного PATCH метаданных (полный
re-index Docling/chunker/Qdrant локального content_path) -- reload есть
намеренное ручное действие "перезалить статью", условный skip по хешу не
нужен и не добавлен: GAR-схема не хранит content_hash (GAR -- источник
истины метаданных, заводить новое поле только под этот диф избыточно).

Re-crawl исходника передаётся через callback ``recrawl`` и проверяется до
изменения GAR; обычный вызов без callback сохраняет legacy-поведение.
"""
from __future__ import annotations

import json
import logging
import hashlib
import shutil
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..gar_client.client import GarClient, GarClientError
from .pipeline import (
    _METADATA_KEYS, _build_select_mapping, _load_state, _normalize_payload, add_reading_time,
)

logger = logging.getLogger(__name__)


class ReloadError(RuntimeError):
    """Recoverable reload failure (не найден doc/source/gar_document_id)."""

    status_code = 404


class ReloadValidationError(ReloadError):
    status_code = 422


class ReloadConflictError(ReloadError):
    status_code = 409


class ReloadUpstreamError(ReloadError):
    status_code = 502


def resolve_source_doc(data_dir: Path, gar_document_id: str) -> tuple[str, str]:
    """Обратный поиск (source, doc_id) по gar_document_id среди *.ingested.json
    (issue ds_search#23 / ADR-0007 п.4: кнопка в админке знает только
    gar_document_id из карточки материала, не локальный source/doc_id)."""
    for state_path in sorted(data_dir.glob("*.ingested.json")):
        state = _load_state(state_path)
        for doc_id, gid in state.items():
            if gid == gar_document_id:
                return state_path.stem.removesuffix(".ingested"), doc_id
    raise ReloadError(f"no local source/doc_id found for gar_document_id={gar_document_id!r}")


def resolve_source_doc_from_metadata(raw_dir: Path, metadata: dict) -> tuple[str, str]:
    """Find local source/doc_id for legacy state files without GAR IDs.

    Older ``*.ingested.json`` files contain only a list of doc IDs.  Match the
    GAR document to its local sidecar by stable source URL (title is a weaker
    fallback for old records without URL metadata).
    """
    source_url = metadata.get("source_url") or metadata.get("canonical_url")
    title = metadata.get("title")
    title_match: tuple[str, str] | None = None
    for json_path in sorted(raw_dir.glob("*/*.json")):
        try:
            local = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if source_url and local.get("source_url") == source_url:
            return json_path.parent.name, json_path.stem
        if title and title_match is None and local.get("title") == title:
            title_match = (json_path.parent.name, json_path.stem)
    if title_match:
        return title_match
    raise ReloadError("no local source/doc_id matches GAR document metadata")


_RELOAD_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(document_id: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _RELOAD_LOCKS.setdefault(document_id, threading.Lock())


def _merge_metadata(old_gar: dict, old_source: dict, new: dict) -> tuple[dict, dict, list[str]]:
    merged = dict(old_gar)
    changed: dict = {}
    preserved: list[str] = []
    for key, value in old_gar.items():
        if key not in new and value not in (None, ""):
            preserved.append(key)
    for key, value in new.items():
        if value is None:
            continue
        if key in old_gar and key in old_source and old_gar[key] != old_source[key]:
            if key not in preserved:
                preserved.append(key)
            continue
        if old_gar.get(key) != value:
            changed[key] = value
        merged[key] = value
    return merged, changed, preserved


def _backup_source(source_dir: Path, json_path: Path, content_path: Path, correlation_id: str) -> Path:
    """Save pre-reload source files for operator recovery."""
    backup_dir = source_dir / ".reload-backups" / correlation_id
    backup_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(json_path, backup_dir / json_path.name)
    if content_path.is_file():
        shutil.copy2(content_path, backup_dir / content_path.name)
    return backup_dir


def _write_manual_recovery(backup_dir: Path, document_id: str, error: Exception) -> None:
    """Persist recovery instructions when metadata rollback also fails."""
    (backup_dir / "manual_recovery.json").write_text(
        json.dumps({
            "status": "manual_recovery",
            "document_id": document_id,
            "error": str(error),
            "backup_dir": str(backup_dir),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


@dataclass
class ReloadReport:
    doc_id: str
    gar_document_id: str
    changed_fields: dict
    preserved_fields: list[str]
    content_replaced: bool


def reload_document(
    client: GarClient, dataset_id: str, source_dir: Path, state_path: Path, doc_id: str,
    known_gar_document_id: str | None = None,
    recrawl=None,
) -> ReloadReport:
    json_path = source_dir / f"{doc_id}.json"
    if not json_path.is_file():
        raise ReloadError(f"source doc not found: {json_path}")

    state = _load_state(state_path)
    if doc_id not in state:
        raise ReloadError(f"doc_id {doc_id!r} not in state ({state_path.name}); run initial ingest first")
    gar_document_id = state[doc_id] or known_gar_document_id
    if not gar_document_id:
        raise ReloadError(
            f"doc_id {doc_id!r} has no known gar_document_id in state "
            f"({state_path.name}, legacy формат); нужен повторный полный ingest"
        )

    meta = json.loads(json_path.read_text(encoding="utf-8"))
    select_mapping = _build_select_mapping(client, dataset_id)
    try:
        existing = client.get_document(gar_document_id)
    except GarClientError as exc:
        raise ReloadError(f"failed to fetch existing document {gar_document_id}: {exc}") from exc
    old_meta = existing.get("metadata") or {}

    lock = _lock_for(gar_document_id)
    if not lock.acquire(blocking=False):
        raise ReloadConflictError(f"reload already in progress for {gar_document_id}")
    try:
        if recrawl is not None:
            staged = recrawl(meta.get("source_url") or meta.get("canonical_url"), doc_id)
            if not staged:
                raise ReloadUpstreamError("re-crawl rejected")
            canonical_url = staged.get("canonical_url")
            staged_id = staged.get("doc_id")
            metadata_path = Path(staged.get("metadata_path") or "")
            old_canonical_url = meta.get("canonical_url") or meta.get("source_url")
            # ADR-0010 (амендмент ADR-0009 п.2): identity recrawl'а -- canonical_url,
            # не doc_id. Legacy doc_id -- slug, не sha256(canonical_url); staged_id
            # сверяется только с собственным canonical_url (внутренняя консистентность
            # staged-результата), а стабильность источника -- через canonical_url
            # старой записи, не через doc_id.
            if (not canonical_url or not staged_id or
                    staged_id != hashlib.sha256(canonical_url.encode()).hexdigest()[:16] or
                    not old_canonical_url or canonical_url != old_canonical_url or
                    not metadata_path.is_file()):
                raise ReloadValidationError("invalid staged identity or metadata")
            staged_meta = staged.get("metadata") or {}
            content_path = Path(staged.get("content_path") or "")
            if not isinstance(staged_meta, dict) or not content_path.is_file():
                raise ReloadValidationError("staged content or metadata is missing")
            correlation_id = (staged.get("provenance") or {}).get("correlation_id") or str(uuid.uuid4())
            backup_dir = _backup_source(source_dir, json_path, Path(meta.get("content_path") or ""), correlation_id)
            new_payload = _normalize_payload(
                {k: staged_meta.get(k) for k in _METADATA_KEYS if staged_meta.get(k) is not None},
                select_mapping,
            )
            add_reading_time(new_payload, content_path)
        else:
            new_payload = _normalize_payload(
                {k: meta.get(k) for k in _METADATA_KEYS if meta.get(k) is not None},
                select_mapping,
            )
            add_reading_time(new_payload, Path(meta.get("content_path") or ""))

    # ADR-0007 п.2: поля, которых нет в новом выводе классификатора, но есть
    # в старой записи (потенциально правились вручную), переносятся as is.
        if recrawl is None:
            preserved = [k for k in old_meta if k not in new_payload and old_meta[k] not in (None, "")]
            merged = {**{k: old_meta[k] for k in preserved}, **new_payload}
            changed = {k: v for k, v in new_payload.items() if old_meta.get(k) != v}
        else:
            merged, changed, preserved = _merge_metadata(old_meta, meta, new_payload)

        try:
            client.update_document_metadata(gar_document_id, merged)
        except GarClientError as exc:
            raise ReloadError(f"update failed for {gar_document_id}: {exc}") from exc

        content_path = content_path if recrawl is not None else Path(meta["content_path"])
        try:
            client.update_document_content(gar_document_id, content_path)
        except GarClientError as exc:
            try:
                client.update_document_metadata(gar_document_id, old_meta)
            except GarClientError as rollback_exc:
                if recrawl is not None:
                    _write_manual_recovery(backup_dir, gar_document_id, rollback_exc)
                raise ReloadError(f"content replace failed; metadata rollback failed for {gar_document_id}") from exc
            raise ReloadError(f"content replace failed for {gar_document_id}: {exc}") from exc

        logger.info(
            "reload %s -> %s: changed=%s preserved=%s content_replaced=True",
            doc_id, gar_document_id, list(changed), preserved,
        )
        return ReloadReport(
            doc_id=doc_id, gar_document_id=gar_document_id,
            changed_fields=changed, preserved_fields=preserved, content_replaced=True,
        )
    finally:
        lock.release()
