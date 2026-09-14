"""CLI-обёртка адаптера (issue #5): python -m src.adapter.cli <source> [--dry-run].

Пример: python -m src.adapter.cli downsideup
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ..gar_client.client import GarClient
from ..gar_client.config import load_settings
from ..gar_client.metadata_fields import ensure_domain_schema
from .pipeline import run_adapter

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="имя источника, папка в <ds_search>/data/raw/<source>")
    parser.add_argument("--dry-run", action="store_true", help="не вызывать GAR, только собрать метаданные")
    args = parser.parse_args(argv)

    settings = load_settings()
    print(f"DEBUG settings: user_id={settings.user_id}, tenant_id={settings.tenant_id}, dataset_name={settings.dataset_name}", flush=True)
    source_dir = Path(settings.ds_search_root).resolve() / "data" / "raw" / args.source
    if not source_dir.is_dir():
        parser.error(f"источник не найден: {source_dir}")

    state_path = Path(__file__).resolve().parents[2] / "data" / f"{args.source}.ingested.json"

    with GarClient(settings) as client:
        dataset_id = client.ensure_dataset(settings.dataset_name)
        if not args.dry_run:
            ensure_domain_schema(client, dataset_id, settings.ds_search_root)
        report = run_adapter(client, dataset_id, source_dir, state_path, dry_run=args.dry_run)

    print(json.dumps(
        {"ingested": len(report.ingested), "skipped": len(report.skipped), "failed": len(report.failed)},
        ensure_ascii=False,
    ))
    if report.failed:
        for item in report.failed:
            logger.error("failed: %s", item)
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
