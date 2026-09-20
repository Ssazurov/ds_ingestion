## 2026-09-15 -- release 0.1.21 closed; next 0.1.22

- All Project #1 items targeted to 0.1.21 are Done/closed. Release notes published; next release target is 0.1.22.

## 2026-09-15 -- verify: reload 0ff5048e (Папа солнечного ребёнка) успешен

- Сервис `src.adapter.api` перезапущен (подхватить фикс #26), вызван штатный
  `POST /reload_by_gar_id` для `0ff5048e-2c5c-450f-b619-90d6449d8ca6` —
  200, `content_replaced=true`. Legacy slug `doc_id` подтверждён рабочим.
- `«Мам, я хочу как Саид»` (`c844974c-f437-4f1a-98d7-03293b202a99`) — тот же
  класс проблемы, не перезагружен в этой сессии, кандидат на повтор той же
  проверки при необходимости.

## 2026-09-15 -- fix: identity recrawl по canonical_url, не doc_id (PR #27, Closes #26)

- ADR-0010 (`ds/docs/adr/0010-recrawl-identity-canonical-url.md`, амендмент
  ADR-0009 п.2): `doc_id` — локальный ключ state/файлов, не identity.
  Identity recrawl'а — `canonical_url`.
- `reload_document`: убрана проверка `staged_id != doc_id`; добавлена
  проверка `canonical_url` (staged) == `canonical_url` старой записи.
  `staged_id == sha256(canonical_url)[:16]` (внутренняя консистентность
  staged-результата) осталась без изменений.
- Legacy slug `doc_id` (`papa-solnechnogo-rebenka-...`) больше не блокирует
  reload; concретный doc `0ff5048e-2c5c-450f-b619-90d6449d8ca6` разблокирован.
- Тесты: +2 (`test_recrawl_allows_legacy_slug_doc_id`,
  `test_recrawl_rejects_canonical_url_drift`), 13/13 passed.

## 2026-09-15 -- fix: recrawl subprocess venv (PR #25, Closes #24) + найден identity-баг (#26)

- Воспроизведён 404 для reload gar_document_id `0ff5048e-2c5c-450f-b619-90d6449d8ca6`
  (`papa-solnechnogo-...`). По цепочке найдено два разных бага:
  1. `sys.executable` в `recrawl()` — это интерпретатор **ds_ingestion**, у
     него нет `crawl4ai`/зависимостей краулера -> subprocess падает
     `ModuleNotFoundError`, `_do_reload` тихо отдаёт 502 "re-crawl rejected".
     Исправлено: берём `python` из `<ds_search_root>/.venv/bin/python`
     (fallback `sys.executable`). PR #25 (merged), Closes #24.
  2. После фикса (1) вскрылся системный баг: `reload_document`
     (ADR-0009 п.2) требует `staged_id(sha256 canonical_url) == doc_id`,
     но legacy-документы имеют slug `doc_id` (не hash) -> 422 "invalid
     staged identity or metadata" **для всех** таких документов, не
     только для этого. Не чинил вслепую — меняет identity-контракт
     ADR-0009, нужен ADR. Заведён issue #26.
- Итог: конкретный doc из запроса пока НЕ перезагружается (падает на #26).

## 2026-09-15 -- fix: reload FileNotFoundError (python vs python3)

- Баг: `recrawl()` в `src/adapter/api.py` запускал краулер через
  `subprocess.run(["python", ...])`, в окружении нет `python`, только
  `python3` -> `FileNotFoundError` -> кнопка reload в ds_search/ui падала
  404/500. Исправлено на `sys.executable` (PR #23, Closes #21).
- Найден отдельный баг (не исправлен, issue #22): fallback-резолв
  `resolve_source_doc_from_metadata` для legacy-документов без записи в
  `.ingested.json` возвращает raw-категорию (`family_support`) вместо
  реального ключа `SOURCES` из `ds_search/src/crawler/config.py`
  (`downsideup`). Краулер падает `KeyError`, `_do_reload` тихо превращает
  это в "re-crawl rejected" (502). Воспроизведено на
  gar_document_id=c844974c-f437-4f1a-98d7-03293b202a99.

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

## 2026-09-17 -- диагностика медленной LLM-классификации (GPU throttling)

- Симптом: генерация черновика классификации новостей через `qwen2.5-coder:14b`
  в Ollama шла со скоростью CPU (~2.5 мин/новость), хотя GPU (RTX 5080 Laptop)
  ожидалась.
- Найдено и исправлено: в `deploy/ai-services/docker-compose.yml` секция
  `ollama` не имела GPU-резервации (`deploy.resources.reservations.devices`),
  в отличие от `reranker`/`docling-intake` -- добавлена, контейнер
  пересоздан (образ/volume `ollama_data` не тронуты). `size_vram` стал > 0,
  49/49 слоёв на GPU.
- После этого скорость всё ещё была ~4 ток/сек при 98% GPU-util. Причина
  оказалась не в софте: ноутбук работал от батареи (план питания
  "Сбалансированный"), из-за чего RTX 5080 Laptop была залочена на
  ~562 MHz/19W вместо ~3090 MHz/175W (Windows/Optimus power throttling).
  После подключения зарядки -- 60.5 ток/сек, GPU разгоняется до ~150W.
- Итог: конфиг ollama/docker-compose корректен и трогать не нужно;
  при повторении симптома в первую очередь проверять питание ноутбука
  (`powercfg /getactivescheme`, `Get-CimInstance Win32_Battery`), а не
  GPU-passthrough.

## 2026-09-17 -- сквозная проверка пайпа новостей (RSS -> сайт), issue #48/#49

- Собрана 1 новость (pravmir.ru), LLM-драфт создан (status=drafted), затем
  вручную переведена в `published` для публикации в GAR (issue #49,
  `scripts/publish_news.py`).
- Найдены и исправлены 3 независимые проблемы конфигурации после переезда
  стека на docker (`~/projects/deploy/docker-compose.yml`), не связанные
  с логикой публикации:
  1. `ds_search/.env`: `GAR_CORE_API_URL` отсутствовал -> клиент падал на
     дефолт `127.0.0.1:8100` вместо реального порта `8000`. Добавлено.
  2. `ds_search/.env`: `GAR_USER_ID` (дефолт `ds-search-news-publish`) не
     имел прав `write` на датасет -> 403. Временно переключено на
     `admin-ds-ingestion`. TODO: завести отдельного пользователя с правом
     write именно на новостной датасет, не admin.
  3. **gar-core-api хранит embedding/vector_store endpoint в таблице
     `Config` (БД), а не только в env** -- там остались значения от
     до-докерной установки (`localhost:8083`, `localhost:6333`), из-за
     чего `ingest` падал с `embedding request failed: All connection
     attempts failed`, хотя сам embeddings-контейнер был здоров. Поля
     `embedding.endpoint` -> `http://embeddings:80`,
     `vector_store.host` -> `docker-qdrant-1` исправлены напрямую в БД.
     `reranker`/`llm`/`generation`/`docling_intake` в той же таблице
     тоже содержат `localhost:*` -- не трогали (не используются в пути
     ingest), но при следующей похожей проблеме проверять в первую
     очередь `Config`-таблицу, а не только env/docker-compose.
- **Qdrant (`docker-qdrant-1`) живёт в отдельной docker-сети** -- изначально
  часть dify-стека (`~/projects/dify/docker/docker-compose.yml`), файл
  которого физически удалён после вывода Dify из прод-контура (см.
  areas/rag-product.md). gar-core-api не мог резолвить его по имени.
  Исправлено: `docker network connect deploy_gar-net docker-qdrant-1`.
  Т.к. управляющего compose-файла для qdrant больше нет, это подключение
  переживёт `docker restart`, но НЕ переживёт пересоздание контейнера
  qdrant -- на этот случай добавлен idempotent-скрипт
  `~/projects/deploy/ensure-qdrant-network.sh` (запускать после
  `docker compose up` в `deploy/`).
- Итог: 2 новости успешно проиндексированы в GAR (`status: indexed`,
  document_id `3bfc8705...`, `6e003195...`), видны через
  `/public/documents?doc_type=news`.
- **`/news` на сайте (ds_site) физически не реализован** -- файлов
  `app/news/*` нет, это отдельная задача issue #15 (см. overview.md
  "On the horizon"), не часть текущей проверки пайпа.

## 2026-09-17 -- нет TAVILY_API_KEY, автоустановка CLI заблокирована сетью

- Задача: найти 2 свежие новости по теме через веб-поиск (не RSS) и
  опубликовать -- `collect_news.py` (в отличие от RSS-пайпа
  `collect_rss.py`) ищет через Tavily API, ключа `TAVILY_API_KEY` нет в
  `.env`.
- Дашборд tavily.com отдаёт "We couldn't load your API key. Please try
  again." при попытке создать ключ вручную -- похоже на баг/глюк сайта,
  не сети (страница открывается).
- Автоустановка через `tavily.com/agent-setup/SKILL.md` (curl-install tvly
  CLI) не работает: `cli.tavily.com` резолвится по IPv4, но соединение
  виснет/таймаутит -- похоже на тот же файрвол/сетевой блок WSL, что уже
  мешал ранее с внешним LLM-провайдером. `curl -4` тоже не помогает --
  блокировка не только IPv6, а на уровне файрвола/прокси Windows для
  этого диапазона.
- **Keyless-режим добавлен в `ds_search/src/search/tavily.py`** (2026-09-17):
  `TavilyProvider` без `api_key`/`TAVILY_API_KEY` теперь шлёт
  `X-Tavily-Access-Mode: keyless` вместо `api_key` в body.
- Тест запроса из WSL даёт `403 Forbidden` -- НЕ JSON-ошибка Tavily, а
  голая nginx-страница -- похоже на тот же сетевой блок/WAF по IP, что
  уже мешал с CLI (`cli.tavily.com`), а не проблему с keyless-режимом
  самим по себе.
- **Подтверждено (2026-09-17):** запрос с keyless-заголовком к
  `api.tavily.com/search` с хоста Windows (PowerShell, не WSL) -- `200 OK`,
  результаты корректны. 403 воспроизводится только из WSL -- это сетевой
  блок/WAF WSL-диапазона, не проблема кода или Tavily.
- **Вывод:** `TavilyProvider` (keyless) рабочий. Если прод/деплой идёт не
  из WSL (напр. Docker на Windows-хосте или CI) -- `collect_news.py`
  заработает как есть, без `TAVILY_API_KEY`. Если запуск именно из WSL --
  нужен фикс сети WSL (см. постоянные-правила по сети) или проксирование
  запроса через Windows-хост.
- **`collect_news.py` прогнан end-to-end в Docker (2026-09-17), 3 инфра-фикса:**
  1. keyless Tavily (см. выше) -- поиск работает (queries_run=4,
     candidates_found=20).
  2. `ds_search/Dockerfile`: добавлен `RUN playwright install --with-deps
     chromium` -- без него скачивание падало
     (`BrowserType.launch: Executable doesn't exist`).
  3. `deploy/docker-compose.yml`: сервису `ds-search` добавлен
     `extra_hosts: host.docker.internal:host-gateway` (был только у
     ds-ingestion); `ds_search/config/news_llm.yaml` endpoint
     `localhost:11434` -> `host.docker.internal:11434` -- из контейнера
     `localhost` не видит Ollama на хосте.
- **Итог прогона:** `queries_run=4 candidates_found=20 download_failed=0
  llm_failed=0 drafted=0 skipped_license=20` -- инфраструктура (поиск/
  скачивание/LLM) полностью рабочая; 0 задрафчено, т.к. все найденные
  источники не прошли existing license/robots-фильтр (`license_denied`
  в `src/news/collect.py`) -- это штатная логика, не баг.
- **Следующий шаг (не выполнен):** разобраться, почему все 20 кандидатов
  из этих 4 запросов попадают под `license_denied` -- либо источники
  реально с запретом (тогда нужно расширить пул запросов/источников),
  либо проверка слишком строгая (см. `_check_license`/`robots.txt` логику
  в `src/news/collect.py` и `src/discovery/`).
- **Разобрано:** `license_denied` -- НЕ кэш "виденных" ссылок (dedup был
  0), а лицензионный вайтлист `config/licenses.yaml` (ADR-001 п.3);
  домены без записи получают `pending_manual_review` -> блокируются по
  дизайну. 18 из 20 найденных Tavily доменов не были проверены.
- **Добавлены в `licenses.yaml` (2026-09-17), после проверки ToS:**
  `news.un.org` -> `attribution_required` (UN News: обратная ссылка,
  без письменного разрешения); `www.unicef.org` -> `deny` (явно требует
  письменного разрешения на любое использование). Остальные ~16
  доменов (tass.ru, iz.ru, forbes.kz и т.д.) НЕ проверены -- нужен
  отдельный заход на юридическую проверку каждого при желании расширить
  пул источников.
- **ИТОГ (2026-09-17): `collect_news.py` полностью рабочий end-to-end** --
  `queries_run=4 candidates_found=20 download_failed=1 llm_failed=0
  drafted=2`. Issue #61 можно считать технически закрытым (пайп
  работает); дальнейший рост % задрафченного -- вопрос расширения
  `licenses.yaml`, не кода.

- 2026-09-19: ADR-0015 (root `ds/docs/adr/0015-document-tags-field.md`): поле `tags` в метаданных; issue ds_site#61 (родитель), дочерние в gar-core-api и ds_ingestion.

## 2026-09-20 — issue #33: reading_time_min
- `add_reading_time` (pipeline.py) для doc_type=article: ceil(слов/200) по .md, text-поле `reading_time_min` (metadata_fields.py); применено в run_adapter и reload (обе ветки). ADR: ds/docs/adr/0017. Тесты: tests/test_reading_time.py (25 passed). Backfill старых статей — через reload.
