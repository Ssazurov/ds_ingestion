"""Auth + rate-limit для /reload, /reload_by_gar_id (ADR-0008, issue #9).

X-Ingestion-Key заголовок сверяется с INGESTION_API_KEY (secrets.compare_digest).
Rate-limit: in-memory token bucket per doc_id (1/60s) + общий лимит на
инстанс (20/мин). Без Redis -- single instance (YAGNI).
"""
from __future__ import annotations

import os
import secrets
import time
from collections import deque

from fastapi import Header, HTTPException

_API_KEY = os.environ.get("INGESTION_API_KEY")
_ENV = os.environ.get("ENV", "dev")

if _ENV == "prod" and not _API_KEY:
    raise RuntimeError(
        "INGESTION_API_KEY не задан при ENV=prod (ADR-0008): отказ старта."
    )

_PER_DOC_WINDOW_S = 60.0
_GLOBAL_LIMIT = 20
_GLOBAL_WINDOW_S = 60.0

_last_call_by_doc: dict[str, float] = {}
_global_calls: deque[float] = deque()


def check_auth(x_ingestion_key: str | None = Header(default=None)) -> None:
    if not _API_KEY:
        return  # dev-режим без ключа, см. ADR-0008 п.3
    if not x_ingestion_key or not secrets.compare_digest(x_ingestion_key, _API_KEY):
        raise HTTPException(401, "invalid or missing X-Ingestion-Key")


def check_rate_limit(doc_id: str) -> None:
    now = time.monotonic()

    while _global_calls and now - _global_calls[0] > _GLOBAL_WINDOW_S:
        _global_calls.popleft()
    if len(_global_calls) >= _GLOBAL_LIMIT:
        raise HTTPException(429, "global reload rate limit exceeded, retry later")

    last = _last_call_by_doc.get(doc_id)
    if last is not None and now - last < _PER_DOC_WINDOW_S:
        wait = _PER_DOC_WINDOW_S - (now - last)
        raise HTTPException(429, f"reload for {doc_id} rate-limited, retry in {wait:.0f}s")

    _last_call_by_doc[doc_id] = now
    _global_calls.append(now)
