"""HTTP API ds_ingestion (issue #8, ADR-0007): POST /reload {source, doc_id}.

Запуск: uvicorn src.adapter.api:app --port 8200
Контракт вызывающей стороны (ADR-0005: админка только в ds_search/ui
Streamlit, не ds_site): ds_search дергает этот эндпоинт напрямую.
Auth: X-Ingestion-Key + rate-limit per doc_id, см. ADR-0008.
"""
from __future__ import annotations

from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from ..gar_client.client import GarClient, GarClientError
from ..gar_client.config import load_settings
from .auth import check_auth, check_rate_limit
from .reload import (
    ReloadError,
    reload_document,
    resolve_source_doc,
    resolve_source_doc_from_metadata,
)

app = FastAPI(title="ds_ingestion")


class ReloadRequest(BaseModel):
    source: str
    doc_id: str


class ReloadByGarIdRequest(BaseModel):
    """Вход для кнопки в админке ds_search: там известен только
    gar_document_id из карточки материала (issue ds_search#23)."""

    gar_document_id: str


def _do_reload(settings, source: str, doc_id: str, known_gar_document_id: str | None = None) -> dict:
    source_dir = Path(settings.ds_search_root).resolve() / "data" / "raw" / source
    state_path = Path(__file__).resolve().parents[2] / "data" / f"{source}.ingested.json"
    if not source_dir.is_dir():
        raise HTTPException(404, f"source not found: {source}")

    staging_dir: str | None = None

    def recrawl(url: str, expected_doc_id: str):
        nonlocal staging_dir
        staging = tempfile.mkdtemp(prefix=f"reload-{expected_doc_id}-")
        staging_dir = staging
        proc = subprocess.run(
            [sys.executable, "-m", "src.crawler.crawler", "--recrawl", "--source", source,
             "--doc-id", expected_doc_id, "--url", url, "--staging-dir", staging],
            cwd=settings.ds_search_root, capture_output=True, text=True, timeout=600,
        )
        if proc.returncode:
            return None
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        try:
            result = json.loads(lines[-1])
        except (IndexError, json.JSONDecodeError):
            return None
        result["_staging_dir"] = staging
        return result

    with GarClient(settings) as client:
        dataset_id = client.ensure_dataset(settings.dataset_name)
        try:
            report = reload_document(
                client, dataset_id, source_dir, state_path, doc_id, known_gar_document_id,
                recrawl=recrawl,
            )
        except ReloadError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        finally:
            if staging_dir:
                shutil.rmtree(staging_dir, ignore_errors=True)

    return {
        "doc_id": report.doc_id,
        "gar_document_id": report.gar_document_id,
        "changed_fields": report.changed_fields,
        "preserved_fields": report.preserved_fields,
        "content_replaced": report.content_replaced,
    }


@app.post("/reload", dependencies=[Depends(check_auth)])
def reload_endpoint(body: ReloadRequest) -> dict:
    check_rate_limit(f"{body.source}/{body.doc_id}")
    settings = load_settings()
    return _do_reload(settings, body.source, body.doc_id)


@app.post("/reload_by_gar_id", dependencies=[Depends(check_auth)])
def reload_by_gar_id_endpoint(body: ReloadByGarIdRequest) -> dict:
    """Для кнопки в ds_search/ui: резолвит source/doc_id по gar_document_id
    среди всех *.ingested.json, затем делает обычный reload."""
    check_rate_limit(body.gar_document_id)
    settings = load_settings()
    data_dir = Path(__file__).resolve().parents[2] / "data"
    try:
        source, doc_id = resolve_source_doc(data_dir, body.gar_document_id)
    except ReloadError:
        # Legacy state files have no GAR IDs. Resolve through the document's
        # stable source_url/title, then normal reload validates local state.
        try:
            with GarClient(settings) as client:
                existing = client.get_document(body.gar_document_id)
            source, doc_id = resolve_source_doc_from_metadata(
                Path(settings.ds_search_root).resolve() / "data" / "raw",
                existing.get("metadata") or {},
            )
        except (GarClientError, ReloadError) as exc:
            raise HTTPException(404, str(exc)) from exc
    return _do_reload(settings, source, doc_id, body.gar_document_id)
