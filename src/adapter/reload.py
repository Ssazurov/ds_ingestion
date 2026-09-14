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

Re-crawl исходника (ds_search#141) тоже пока не реализован: reload читает
текущий локальный sidecar-json как есть.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ..gar_client.client import GarClient, GarClientError
from .pipeline import _METADATA_KEYS, _build_select_mapping, _load_state, _normalize_payload

logger = logging.getLogger(__name__)


class ReloadError(RuntimeError):
    """Recoverable reload failure (не найден doc/source/gar_document_id)."""


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


@dataclass
class ReloadReport:
    doc_id: str
    gar_document_id: str
    changed_fields: dict
    preserved_fields: list[str]
    content_replaced: bool


def reload_document(
    client: GarClient, dataset_id: str, source_dir: Path, state_path: Path, doc_id: str,
) -> ReloadReport:
    json_path = source_dir / f"{doc_id}.json"
    if not json_path.is_file():
        raise ReloadError(f"source doc not found: {json_path}")

    state = _load_state(state_path)
    if doc_id not in state:
        raise ReloadError(f"doc_id {doc_id!r} not in state ({state_path.name}); run initial ingest first")
    gar_document_id = state[doc_id]
    if not gar_document_id:
        raise ReloadError(
            f"doc_id {doc_id!r} has no known gar_document_id in state "
            f"({state_path.name}, legacy формат); нужен повторный полный ingest"
        )

    meta = json.loads(json_path.read_text(encoding="utf-8"))
    select_mapping = _build_select_mapping(client, dataset_id)
    new_payload = _normalize_payload(
        {k: meta.get(k) for k in _METADATA_KEYS if meta.get(k) is not None},
        select_mapping,
    )

    try:
        existing = client.get_document(gar_document_id)
    except GarClientError as exc:
        raise ReloadError(f"failed to fetch existing document {gar_document_id}: {exc}") from exc
    old_meta = existing.get("metadata") or {}

    # ADR-0007 п.2: поля, которых нет в новом выводе классификатора, но есть
    # в старой записи (потенциально правились вручную), переносятся as is.
    preserved = [k for k in old_meta if k not in new_payload and old_meta[k] not in (None, "")]
    merged = {**{k: old_meta[k] for k in preserved}, **new_payload}
    changed = {k: v for k, v in new_payload.items() if old_meta.get(k) != v}

    try:
        client.update_document_metadata(gar_document_id, merged)
    except GarClientError as exc:
        # state не трогаем при сбое -- старая версия в GAR остаётся источником правды.
        raise ReloadError(f"update failed for {gar_document_id}: {exc}") from exc

    content_path = Path(meta["content_path"])
    try:
        client.update_document_content(gar_document_id, content_path)
    except GarClientError as exc:
        # metadata уже обновлена -- контент не тронут, старый текст/индекс остаются.
        raise ReloadError(f"content replace failed for {gar_document_id}: {exc}") from exc

    logger.info(
        "reload %s -> %s: changed=%s preserved=%s content_replaced=True",
        doc_id, gar_document_id, list(changed), preserved,
    )
    return ReloadReport(
        doc_id=doc_id, gar_document_id=gar_document_id,
        changed_fields=changed, preserved_fields=preserved, content_replaced=True,
    )
