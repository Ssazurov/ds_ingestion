"""Адаптер загрузки в GAR ingestion pipeline (issue #5, ADR-001 п.1,2).

Читает `data/raw/<source>/*.json`+`*.md` из ds_search (issue #2/#3), для
каждого документа: проверяет допустимый формат, license.downloadable,
маппит sidecar-json в доменный профиль метаданных GAR, вызывает
POST /ingestion/documents. Идемпотентность: уже загруженные doc_id (по
sha256(source_url) — тот же hash, что использует crawler для имени файла)
пишутся в state-файл, повторный запуск их пропускает.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .convert import UnsupportedFormatError, ensure_allowed_format
from ..gar_client.client import GarClient, GarClientError

logger = logging.getLogger(__name__)

_SKIP_LICENSE_STATUSES = {"deny", "pending_manual_review"}
_SKIP_CONTENT_STATUSES = {"rejected_thin_content"}


_METADATA_KEYS = (
    "source_url", "source_domain", "title", "direction", "license",
    "attribution", "category", "doc_type", "target_audience", "author",
    "publish_date", "description", "keywords", "age_group",
)


@dataclass
class IngestReport:
    ingested: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)


def _load_state(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    return set(json.loads(state_path.read_text(encoding="utf-8")))


def _save_state(state_path: Path, doc_ids: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(sorted(doc_ids)), encoding="utf-8")


def _iter_source_docs(source_dir: Path):
    for json_path in sorted(source_dir.glob("*.json")):
        yield json_path.stem, json_path


def run_adapter(
    client: GarClient, dataset_id: str, source_dir: Path, state_path: Path,
    dry_run: bool = False,
) -> IngestReport:
    """Загружает все документы одного источника (data/raw/<source>/) в GAR.

    Последовательно (без параллелизма): gar-docling-intake — один GPU-контейнер
    без пула воркеров (main.py: subprocess на запрос, до 600с), параллельные
    запросы будут просто конкурировать за GPU без выигрыша в throughput (см.
    комментарий в issue #5 / ADR-001 п.6).
    """
    report = IngestReport()
    done = _load_state(state_path)
    for doc_id, json_path in _iter_source_docs(source_dir):
        if doc_id in done:
            report.skipped.append({"doc_id": doc_id, "reason": "already_ingested"})
            continue
        meta = json.loads(json_path.read_text(encoding="utf-8"))
        if meta.get("license") in _SKIP_LICENSE_STATUSES:
            report.skipped.append({"doc_id": doc_id, "reason": f"license={meta.get('license')}"})
            continue
        if meta.get("content_status") in _SKIP_CONTENT_STATUSES:
            report.skipped.append({"doc_id": doc_id, "reason": "rejected_thin_content"})
            continue
        content_path = Path(meta["content_path"])
        try:
            ensure_allowed_format(content_path)
        except UnsupportedFormatError as exc:
            report.failed.append({"doc_id": doc_id, "error": str(exc)})
            continue
        payload = {k: meta.get(k) for k in _METADATA_KEYS if meta.get(k) is not None}
        if dry_run:
            report.ingested.append({"doc_id": doc_id, "dry_run": True, "metadata": payload})
            continue
        try:
            result = client.ingest_document(
                dataset_id=dataset_id, file_path=content_path,
                doc_name=meta.get("title") or doc_id, metadata=payload,
            )
        except GarClientError as exc:
            logger.error("ingest failed for %s: %s", doc_id, exc)
            report.failed.append({"doc_id": doc_id, "error": str(exc)})
            continue
        done.add(doc_id)
        report.ingested.append({"doc_id": doc_id, "document_id": result.get("document_id")})
    if not dry_run:
        _save_state(state_path, done)
    return report
