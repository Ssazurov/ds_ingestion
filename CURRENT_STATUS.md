## 2026-09-14 -- ADR-0009: staged recrawl orchestration реализован

- Root ADR: `ds/docs/adr/0009-real-source-recrawl-reload.md`.
- Requirements: `ds/docs/requirements/real-source-recrawl-reload.md`.
- `reload_document` принимает staged crawler callback, проверяет canonical URL,
  стабильный `doc_id`, metadata/content paths до GAR update, сохраняет manual
  metadata и игнорирует `null`; PATCH выполняется до PUT, при ошибке PUT делается
  rollback metadata snapshot, lock действует per GAR document.
- API сохраняет `/reload` и `/reload_by_gar_id`, очищает staging и маппит
  validation/upstream/conflict ошибки в 422/502/409; legacy state резолвится по
  metadata.
- Проверки: `tests/test_reload.py tests/test_auth.py` — 13 passed; `py_compile`;
  `git diff --check`. Остались отдельные live smoke и backup/manual_recovery
  acceptance-сценарии.

## 2026-09-14 -- backup/manual_recovery acceptance slice

- При staged reload перед GAR PATCH сохраняется backup исходных sidecar/content
  в `<source>/.reload-backups/<correlation_id>/`.
- Если PUT content и последующий metadata rollback неуспешны, backup получает
  `manual_recovery.json` с GAR ID, ошибкой и путём восстановления; state не меняется.
- Добавлены тесты backup preservation и manual-recovery marker.
- Live smoke: GAR `/health` — `200`, staged recrawl реального URL
  `alisa-i-chudesa` — exit `0`, стабильный `doc_id=957d4192c8455c1d`, staged
  `.md`/`.json` созданы. Полный API reload не выполнен: текущий `ds_search`
  crawler config содержит только source key `downsideup`, а локальный документ
  находится в `family_support`; это отдельный integration blocker.
- Проверки: focused `pytest` — 15 passed; `py_compile`; `git diff --check`.

## 2026-09-14 -- issue #11: PUT content в reload_document (снят блокер #8)

- gar-core-api PR #317 добавил `PUT /ingestion/documents/{document_id}/content`
  (update-in-place, id сохраняется) -- блокер, описанный ниже в записи по #8,
  снят.
- `GarClient.update_document_content(document_id, file_path)` — вызывает
  новый эндпоинт. `reload_document()` теперь всегда вызывает его после
  успешного PATCH metadata (полный re-index Docling/chunker/Qdrant).
  `ReloadReport.content_replaced: bool` добавлен.
- Условный skip по content-хешу не добавлен: reload -- намеренное ручное
  действие "перезалить статью", GAR-схема не хранит content_hash.
- **Live-проверка выполнена** (локальный gar-core-api, 127.0.0.1:8100,
  пришлось перезапустить процесс -- старый воркер был поднят до мержа PR
  #317/#316 в gar-core-api и не видел новый роут, 404): ingest + reload
  реальной статьи `family_support/alisa-i-chudesa` во временном source_dir/
  state (`/tmp/reload_live_test`, не влияет на прод state) —
  `content_replaced=True`, `status=indexed`, `updated_at` обновился,
  `document_id` стабилен между ingest и reload.
- Тесты: `tests/test_reload.py` — 6/6 passed.
- PR: Ssazurov/ds_ingestion#12, Closes #11.

## #13 — POST /reload_by_gar_id (кнопка в админке ds_search, 2026-09-14)
- ds_site#23 закрыт как "не по адресу": ADR-0005 закрепил, что админка живёт
  только в `ds_search/ui/` (Streamlit). Задача перенесена в
  Ssazurov/ds_search#145 (parent: этот эпик #7).
- `resolve_source_doc(data_dir, gar_document_id)` в `reload.py` — обратный
  поиск (source, doc_id) по `*.ingested.json`, т.к. кнопка в админке знает
  только `gar_document_id`.
- `POST /reload_by_gar_id {gar_document_id}` в `api.py` — резолвит через
  `resolve_source_doc`, дальше обычный `reload_document`.
- Auth не реализован — прода нет (ADR-0007 п.4).
- Тесты: 6/6 passed (py_compile + pytest -k reload).
- PR: Ssazurov/ds_ingestion#14 (squash), Closes #13.

## 2026-09-14 -- Epic #7: Full source reload pipeline (root ADR-0007)

- Root ADR: `ds/docs/adr/0007-full-source-reload-pipeline.md` (update-in-place
  по gar_document_id, state обновляется только после успешного ingest).
- Epic ds_ingestion#7, подзадачи: ds_ingestion#8 (POST /reload endpoint),
  ds_search#141 (re-crawl по URL), ds_search#142 (устойчивый детект битых
  файлов), ds_site#23 (кнопка в админке). Все добавлены в projects/4.
- Триггер: найдены файлы в ds_search/data/raw/family_support с буквальными
  \n вместо переносов строк (5 исправлено вручную и перезалито в GAR через
  ds_ingestion adapter). Ещё 11 файлов с полным отсутствием переносов не
  перезалиты -- ждут реализации #8.
- **issue #8 реализован**: `POST /reload {source, doc_id}` (`src/adapter/api.py`,
  FastAPI, `uvicorn src.adapter.api:app`). Логика в `src/adapter/reload.py`:
  re-classify локального sidecar-json -> diff с текущей записью GAR
  (`GarClient.get_document`) -> поля, отсутствующие в новом выводе классификатора,
  но присутствующие в старой записи, переносятся as is (ручные правки не
  затираются) -> `GarClient.update_document_metadata` (PATCH). При сбое любого
  шага state не трогается.
- State-файлы `<source>.ingested.json` сменили формат: список doc_id ->
  `{doc_id: gar_document_id}` (нужен id для PATCH). Старый list-формат читается
  как `{doc_id: None}` (backward-compat), при следующем успешном ingest
  дозаполняется. Записи с `None` (созданные до этого изменения) требуют
  повторного полного ingest перед reload -- `reload_document` кидает понятную
  ошибку в этом случае.
- **Блокер (не устранён в рамках #8)**: gar-core-api не даёт заменить бинарный
  контент документа по существующему `document_id` -- есть только PATCH
  метаданных и POST с `supersedes_document_id` (создаёт НОВЫЙ id, что запрещено
  ADR-0007 п.1). Поэтому `/reload` сейчас обновляет только метаданные;
  исправление "битого" контента (буквальный `\n`, см. ADR-0007 п.3) этим
  эндпоинтом не решается. Нужна доработка gar-core-api (PUT/replace content по
  document_id) -- заведён как отдельный блокер, см. комментарий в issue #8.
- Тесты: `tests/test_reload.py` (6 кейсов: preserve/changed, missing source,
  doc_id не в state, legacy state без gar_document_id, сбой update). Прогон
  против реального gar-core-api не выполнялся.

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

## 2026-09-14 -- auth + rate-limit для /reload (ADR-0008, issue #9)

- ADR-0008 (root `ds/docs/adr/`, т.к. контракт ds_search↔ds_ingestion):
  shared secret `X-Ingestion-Key` (сравнение через `secrets.compare_digest`)
  + in-memory rate-limit (1 reload/doc/60s, общий лимит 20/мин), без Redis.
- `src/adapter/auth.py`: `check_auth` (FastAPI dependency), `check_rate_limit`.
  `INGESTION_API_KEY` из env; при `ENV=prod` без ключа -- fail-fast при импорте.
- `src/adapter/api.py`: `/reload`, `/reload_by_gar_id` -- `Depends(check_auth)`
  + вызов `check_rate_limit` внутри хендлера.
- `ds_search/ui/materials_tab.py`: `_reload_from_source` шлёт заголовок
  `X-Ingestion-Key` из `DS_INGESTION_API_KEY`, если задан.
- `.env.example`: добавлены `ENV`, `INGESTION_API_KEY`.
- Тесты: `tests/test_auth.py` (401 без/с неверным ключом, 429 при повторе,
  fail-fast в prod без ключа) -- 4 passed. Полный прогон: 15 passed.
- Разблокирует прод-выкатку issue #8 (см. ADR-0007 п.4).
## 2026-09-14 -- legacy state reload resolution

- `POST /reload_by_gar_id` теперь умеет находить локальный sidecar для старых
  `*.ingested.json` в list-формате без `gar_document_id`: сначала по
  `source_url`/`canonical_url`, затем по уникальному `title` из текущей записи
  GAR.
- Причина фикса: документ `c844974c-f437-4f1a-98d7-03293b202a99` существовал в
  GAR и локальном raw, но его legacy state содержал только `doc_id`, из-за чего
  кнопка возвращала 404.
- Тесты: добавлен тест URL-resolver.
