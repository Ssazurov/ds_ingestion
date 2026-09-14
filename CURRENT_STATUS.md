## 2026-09-14 -- issue #2: lifecycle-метаданные (ADR-0002) в ingestion

- `src/gar_client/metadata_fields.py`: `ensure_domain_schema` регистрирует
  `date_indexed`/`comorbidity_tags`/`reviewed_by` как text-поля (опциональны)
  и `lifecycle_stage` как select с опциями `profile.LIFECYCLE_STAGES` из
  ds_search (unspecified/prenatal/.../adult_life).
- `src/adapter/pipeline.py`: `_METADATA_KEYS` дополнен этими 4 полями,
  `lifecycle_stage` добавлен в `_NORMALIZE_SELECT_KEYS` — payload в GAR не
  теряет значения, неизвестное значение lifecycle_stage отбрасывается, как
  и у других select-полей.
- `category` уже был реализован ранее (не путать с #2 -- только 4 поля были
  реально отсутствующими: date_indexed/lifecycle_stage/comorbidity_tags/reviewed_by).
- Тесты: `tests/test_metadata_fields.py`, `tests/test_pipeline_metadata.py`
  (5 passed). Прогон против реального gar-core-api не выполнялся.

## 2026-09-13 -- ingestion request timeout handling

- `GarClient.ingest_document()` converts `httpx.RequestError` (including request
  timeout) into `GarClientError`; adapter records one failed document and keeps
  processing the remaining source documents.
- No automatic retry is used: a timed-out upload may still be processing in
  `gar-core-api`, so retry could create a duplicate document.
- `GAR_REQUEST_TIMEOUT_S` remains configurable and defaults to `660` seconds,
  matching the documented `gar-docling-intake` subprocess limit plus margin.
