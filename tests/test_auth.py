"""ADR-0008 / issue #9: auth + rate-limit на /reload."""
import importlib
import os

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_key(monkeypatch):
    monkeypatch.setenv("INGESTION_API_KEY", "secret123")
    monkeypatch.delenv("ENV", raising=False)
    from src.adapter import auth as auth_mod
    importlib.reload(auth_mod)
    from src.adapter import api as api_mod
    importlib.reload(api_mod)
    return TestClient(api_mod.app), auth_mod, api_mod


def test_reload_rejects_missing_key(client_with_key):
    client, _, _ = client_with_key
    resp = client.post("/reload", json={"source": "s", "doc_id": "d"})
    assert resp.status_code == 401


def test_reload_rejects_wrong_key(client_with_key):
    client, _, _ = client_with_key
    resp = client.post(
        "/reload", json={"source": "s", "doc_id": "d"},
        headers={"X-Ingestion-Key": "wrong"},
    )
    assert resp.status_code == 401


def test_rate_limit_blocks_second_call_same_doc(client_with_key):
    _, auth_mod, _ = client_with_key
    auth_mod.check_rate_limit("s/d")
    with pytest.raises(HTTPException) as exc:
        auth_mod.check_rate_limit("s/d")
    assert exc.value.status_code == 429


def test_prod_without_key_fails_fast(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.delenv("INGESTION_API_KEY", raising=False)
    from src.adapter import auth as auth_mod
    with pytest.raises(RuntimeError):
        importlib.reload(auth_mod)
    # cleanup: вернуть модуль в dev-состояние для остальных тестов
    monkeypatch.setenv("ENV", "dev")
    importlib.reload(auth_mod)
