"""Регистрация доменного профиля метаданных на датасете GAR (issue #5,
ADR-001 п.2). Вызывается один раз при инициализации адаптера: заводит
per-dataset metadata dictionary полей source_url/title/... и select-полей
direction/category/doc_type/target_audience/license с опциями."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from .client import GarClient


def _load_domain_schema(ds_search_root: str):
    # Прямая загрузка по пути (importlib), а не через sys.path + "import src...":
    # имя пакета "src" совпадает у ds_ingestion и ds_search, что даёт коллизию
    # в sys.modules при запуске `python -m src.adapter.cli` из ds_ingestion.
    schema_path = Path(ds_search_root).resolve() / "src" / "metadata" / "schema.py"
    spec = importlib.util.spec_from_file_location("ds_search_metadata_schema", schema_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    categories = sorted({c for cats in module.load_categories().values() for c in cats})
    return (
        module.DIRECTIONS, module.DOC_TYPES, module.TARGET_AUDIENCES,
        module.LICENSE_STATUSES, categories,
    )


# text-поля профиля (ADR-001 п.2): value_type="text", не select.
_TEXT_FIELDS = [
    ("source_url", "Source URL", True),
    ("source_domain", "Source domain", True),
    ("title", "Title", True),
    ("attribution", "Attribution", False),
    ("author", "Author", False),
    ("publish_date", "Publish date", False),
    ("description", "Description", False),
    ("keywords", "Keywords", False),
    ("age_group", "Age group", False),
]


def ensure_domain_schema(client: GarClient, dataset_id: str, ds_search_root: str) -> None:
    """Идемпотентно заводит доменный профиль метаданных на датасете."""
    directions, doc_types, audiences, licenses, categories = _load_domain_schema(ds_search_root)
    for key, label, required in _TEXT_FIELDS:
        client.ensure_metadata_field(dataset_id, key, label, "text", required)
    select_fields = [
        ("direction", "Direction", directions, True),
        ("category", "Category", categories, False),
        ("doc_type", "Doc type", doc_types, False),
        ("target_audience", "Target audience", audiences, False),
        ("license", "License", licenses, True),
    ]
    for key, label, options, required in select_fields:
        client.ensure_metadata_field(dataset_id, key, label, "select", required, options)
