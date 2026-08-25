"""HTTP-клиент к gar-core-api ingestion/metadata_dictionary (issue #5,
ADR-001 п.1,2). ds_ingestion не строит свой RAG — использует существующий
пайплайн GAR (Docling intake -> chunker -> Qdrant) через /ingestion/* и
/datasets/*/metadata-fields."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from .config import Settings


class GarClientError(RuntimeError):
    """Ошибка при обращении к gar-core-api."""


class GarClient:
    def __init__(self, settings: Settings):
        headers = {"X-User-ID": settings.user_id}
        if settings.tenant_id:
            headers["X-Tenant-ID"] = settings.tenant_id
        self._client = httpx.Client(
            base_url=settings.core_api_url,
            headers=headers,
            timeout=httpx.Timeout(settings.request_timeout_s),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GarClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- datasets ------------------------------------------------------
    def find_dataset_id(self, name: str) -> str | None:
        resp = self._client.get("/ingestion/datasets")
        resp.raise_for_status()
        for row in resp.json().get("datasets", []):
            if row["name"] == name:
                return row["id"]
        return None

    def ensure_dataset(self, name: str) -> str:
        existing = self.find_dataset_id(name)
        if existing:
            return existing
        resp = self._client.post("/ingestion/datasets", json={"name": name})
        if resp.status_code not in (200, 201):
            raise GarClientError(f"create dataset failed: {resp.status_code} {resp.text}")
        return resp.json()["dataset"]["id"]

    # -- metadata dictionary --------------------------------------------
    def list_metadata_fields(self, dataset_id: str) -> dict[str, dict]:
        resp = self._client.get(f"/datasets/{dataset_id}/metadata-fields")
        resp.raise_for_status()
        return {f["key"]: f for f in resp.json().get("fields", [])}

    def ensure_metadata_field(
        self, dataset_id: str, key: str, label: str, value_type: str,
        required: bool, options: list[str] | None = None,
    ) -> dict:
        field = self.list_metadata_fields(dataset_id).get(key)
        if field is None:
            resp = self._client.post(
                f"/datasets/{dataset_id}/metadata-fields",
                json={"key": key, "label": label, "value_type": value_type, "required": required},
            )
            if resp.status_code != 200:
                raise GarClientError(f"create field {key} failed: {resp.status_code} {resp.text}")
            field = resp.json()
        if value_type == "select" and options:
            have = {o["value"] for o in field.get("options", [])}
            for value in options:
                if value in have:
                    continue
                opt = self._client.post(
                    f"/datasets/{dataset_id}/metadata-fields/{field['id']}/options",
                    json={"value": value, "label": value},
                )
                if opt.status_code != 200:
                    raise GarClientError(f"create option {value} for {key} failed: {opt.status_code} {opt.text}")
                field = opt.json()
        return field

    # -- documents --------------------------------------------------------
    def ingest_document(
        self, dataset_id: str, file_path: Path, doc_name: str, metadata: dict,
    ) -> dict:
        with file_path.open("rb") as fh:
            files = {"file": (file_path.name, fh)}
            data = {
                "dataset_id": dataset_id,
                "doc_name": doc_name,
                "metadata": json.dumps(metadata, ensure_ascii=False),
            }
            resp = self._client.post("/ingestion/documents", data=data, files=files)
        if resp.status_code != 200:
            raise GarClientError(f"ingest {file_path.name} failed: {resp.status_code} {resp.text}")
        return resp.json()
