"""Конфигурация ds_ingestion из переменных окружения (.env), issue #5."""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class Settings:
    core_api_url: str
    tenant_id: str | None
    user_id: str
    dataset_name: str
    request_timeout_s: float
    ds_search_root: str


def load_settings() -> Settings:
    return Settings(
        core_api_url=os.environ.get("GAR_CORE_API_URL", "http://127.0.0.1:8100"),
        tenant_id=os.environ.get("GAR_TENANT_ID") or None,
        user_id=os.environ.get("GAR_USER_ID", "ds-ingestion-adapter"),
        dataset_name=os.environ.get("GAR_DATASET_NAME", "sindrom-dauna"),
        # >= SUBPROCESS_TIMEOUT_S (600s) в gar-docling-intake + запас.
        request_timeout_s=float(os.environ.get("GAR_REQUEST_TIMEOUT_S", "660")),
        ds_search_root=os.environ.get("DS_SEARCH_ROOT", "../ds_search"),
    )
