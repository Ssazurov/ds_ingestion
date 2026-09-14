"""HTTP API ds_ingestion (issue #8, ADR-0007): POST /reload {source, doc_id}.

Запуск: uvicorn src.adapter.api:app --port 8200
Контракт вызывающей стороны (ds_site админка, см. ADR-0007 п.5): ds_site
дергает этот эндпоинт, а не ds_search напрямую.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from ..gar_client.client import GarClient
from ..gar_client.config import load_settings
from .reload import ReloadError, reload_document

app = FastAPI(title="ds_ingestion")


class ReloadRequest(BaseModel):
    source: str
    doc_id: str


@app.post("/reload")
def reload_endpoint(body: ReloadRequest) -> dict:
    settings = load_settings()
    source_dir = Path(settings.ds_search_root).resolve() / "data" / "raw" / body.source
    state_path = Path(__file__).resolve().parents[2] / "data" / f"{body.source}.ingested.json"
    if not source_dir.is_dir():
        raise HTTPException(404, f"source not found: {body.source}")

    with GarClient(settings) as client:
        dataset_id = client.ensure_dataset(settings.dataset_name)
        try:
            report = reload_document(client, dataset_id, source_dir, state_path, body.doc_id)
        except ReloadError as exc:
            raise HTTPException(404, str(exc)) from exc

    return {
        "doc_id": report.doc_id,
        "gar_document_id": report.gar_document_id,
        "changed_fields": report.changed_fields,
        "preserved_fields": report.preserved_fields,
    }
