"""HTTP API ds_ingestion (issue #8, ADR-0007): POST /reload {source, doc_id}.

Запуск: uvicorn src.adapter.api:app --port 8200
Контракт вызывающей стороны (ADR-0005: админка только в ds_search/ui
Streamlit, не ds_site): ds_search дергает этот эндпоинт напрямую.
Auth: не реализован -- прода нет, см. ADR-0007 п.4.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..gar_client.client import GarClient
from ..gar_client.config import load_settings
from .reload import ReloadError, reload_document, resolve_source_doc

app = FastAPI(title="ds_ingestion")


class ReloadRequest(BaseModel):
    source: str
    doc_id: str


class ReloadByGarIdRequest(BaseModel):
    """Вход для кнопки в админке ds_search: там известен только
    gar_document_id из карточки материала (issue ds_search#23)."""

    gar_document_id: str


def _do_reload(settings, source: str, doc_id: str) -> dict:
    source_dir = Path(settings.ds_search_root).resolve() / "data" / "raw" / source
    state_path = Path(__file__).resolve().parents[2] / "data" / f"{source}.ingested.json"
    if not source_dir.is_dir():
        raise HTTPException(404, f"source not found: {source}")

    with GarClient(settings) as client:
        dataset_id = client.ensure_dataset(settings.dataset_name)
        try:
            report = reload_document(client, dataset_id, source_dir, state_path, doc_id)
        except ReloadError as exc:
            raise HTTPException(404, str(exc)) from exc

    return {
        "doc_id": report.doc_id,
        "gar_document_id": report.gar_document_id,
        "changed_fields": report.changed_fields,
        "preserved_fields": report.preserved_fields,
        "content_replaced": report.content_replaced,
    }


@app.post("/reload")
def reload_endpoint(body: ReloadRequest) -> dict:
    settings = load_settings()
    return _do_reload(settings, body.source, body.doc_id)


@app.post("/reload_by_gar_id")
def reload_by_gar_id_endpoint(body: ReloadByGarIdRequest) -> dict:
    """Для кнопки в ds_search/ui: резолвит source/doc_id по gar_document_id
    среди всех *.ingested.json, затем делает обычный reload."""
    settings = load_settings()
    data_dir = Path(__file__).resolve().parents[2] / "data"
    try:
        source, doc_id = resolve_source_doc(data_dir, body.gar_document_id)
    except ReloadError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _do_reload(settings, source, doc_id)
