"""Разовый бэкфилл: doc_type=article для документов с source_domain=
downsideup.org и пустым metadata.doc_type (issue: doc_type не проставлялся
веб-статьям, 107/300 документов не показывались на /articles).
Пишет ТОЛЬКО через gar-core-api PATCH /ingestion/documents/{id}
(ADR: все записи в GAR — только через REST, не напрямую в Postgres)."""
from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("GAR_CORE_API_URL", "http://127.0.0.1:8100")
USER = os.environ.get("GAR_USER_ID", "admin-ds-ingestion")
DATASET_NAME = os.environ.get("GAR_DATASET_NAME", "sindrom-dauna")

headers = {"X-User-ID": USER}


def main() -> int:
    with httpx.Client(base_url=BASE, headers=headers, timeout=30) as client:
        resp = client.get("/ingestion/datasets")
        resp.raise_for_status()
        dataset_id = next(
            d["id"] for d in resp.json()["datasets"] if d["name"] == DATASET_NAME
        )

        params = {"dataset_id": dataset_id, "status": "indexed"}
        resp = client.get("/ingestion/documents", params=params)
        resp.raise_for_status()
        docs = resp.json()["documents"]

        targets = [
            d for d in docs
            if not d.get("doc_type") and d.get("metadata", {}).get("source_domain") == "downsideup.org"
        ]
        print(f"Найдено документов без doc_type (downsideup.org): {len(targets)}")

        ok, fail = 0, 0
        for d in targets:
            doc_id = d["document_id"]
            r = client.patch(f"/ingestion/documents/{doc_id}", json={"doc_type": "article"})
            if r.status_code == 200:
                ok += 1
            else:
                fail += 1
                print(f"FAIL {doc_id}: {r.status_code} {r.text[:200]}")
        print(f"Готово: обновлено {ok}, ошибок {fail}")
        return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
