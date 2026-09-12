"""Bootstrap-регистрация доменного профиля метаданных на датасете GAR
(issue #5, ADR-001 п.2).

ВАЖНО (уточнено 2026-09-12, разбор alisa-i-chudesa.json): эталонная схема
полей метаданных живёт в GAR (датасет sindrom-dauna), редактируется ТОЛЬКО
через gar-admin-ui/gar-core-api. `ds_search/config/categories.yaml` и эта
функция — не источник правды, а bootstrap для пустого/нового датасета:
ensure_metadata_field идемпотентно ДОБАВЛЯЕТ отсутствующие поля/опции, но
никогда не удаляет и не переименовывает уже существующие в GAR. Читать
актуальную схему для валидации/классификации нужно из GAR напрямую —
см. ds_search/src/metadata/gar_schema.py (issue #89), а не из categories.yaml.
Направление синхронизации: GAR -> ds_search/categories.yaml (вручную,
при необходимости), не наоборот."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .client import GarClient


def _load_pkg(name: str, init_path: Path, search_dir: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, init_path, submodule_search_locations=[str(search_dir)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_domain_schema(ds_search_root: str):
    # Прямая загрузка по пути (importlib), а не через sys.path + "import src...":
    # имя пакета "src" совпадает у ds_ingestion и ds_search, что даёт коллизию
    # в sys.modules при запуске `python -m src.adapter.cli` из ds_ingestion.
    # schema.py делает `from .profile import ...` — относительный импорт,
    # поэтому регистрируем src и src.metadata как настоящие пакеты в
    # sys.modules (под уникальными именами), иначе exec_module падает с
    # ImportError: attempted relative import with no known parent package.
    root = Path(ds_search_root).resolve()
    _load_pkg("_ds_search_src", root / "src" / "__init__.py", root / "src")
    _load_pkg(
        "_ds_search_src.metadata",
        root / "src" / "metadata" / "__init__.py",
        root / "src" / "metadata",
    )
    schema_path = root / "src" / "metadata" / "schema.py"
    spec = importlib.util.spec_from_file_location("_ds_search_src.metadata.schema", schema_path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "_ds_search_src.metadata"
    sys.modules["_ds_search_src.metadata.schema"] = module
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
