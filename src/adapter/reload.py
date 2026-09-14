"""Reload одной статьи из существующего локального источника (issue #8,
ADR-0007): re-classify -> diff со старой записью GAR -> update-in-place по
gar_document_id.

ИЗВЕСТНОЕ ОГРАНИЧЕНИЕ: gar-core-api сейчас не даёт заменить бинарный
контент документа по существующему document_id -- PATCH меняет только
metadata, POST создаёт новую версию через supersedes_document_id (другой
id). Поэтому reload обновляет только метаданные существующей записи;
замена "битого" контента (см. ADR-0007 п.3) требует доработки gar-core-api
(PUT/replace content) -- заведено отдельным блокером, см. CURRENT_STATUS.md.

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


@dataclass
class ReloadReport:
    doc_id: str
    gar_document_id: str
    changed_fields: dict
    preserved_fields: list[str]


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

    logger.info("reload %s -> %s: changed=%s preserved=%s", doc_id, gar_document_id, list(changed), preserved)
    return ReloadReport(doc_id=doc_id, gar_document_id=gar_document_id, changed_fields=changed, preserved_fields=preserved)
