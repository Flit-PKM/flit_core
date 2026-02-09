"""Tests for config/settings (e.g. CORS_ORIGINS parsing)."""

import os

import pytest

from config import Settings


def _minimal_d1_env(monkeypatch: pytest.MonkeyPatch, **env_overrides: str) -> None:
    """Set minimal env so Settings() can load with D1 backend; then apply overrides."""
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("DB_BACKEND", "d1")
    monkeypatch.setenv("CF_ACCOUNT_ID", "test-account")
    monkeypatch.setenv("CF_API_TOKEN", "test-token")
    monkeypatch.setenv("CF_DATABASE_ID", "test-db-id")
    monkeypatch.setenv("ENVIRONMENT", "test")
    for k, v in env_overrides.items():
        if v is None:
            monkeypatch.delitem(os.environ, k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def test_cors_origins_default_when_empty(monkeypatch: pytest.MonkeyPatch):
    """CORS_ORIGINS missing or empty/blank => default list."""
    _minimal_d1_env(monkeypatch, CORS_ORIGINS="")
    s = Settings()
    assert s.CORS_ORIGINS == ["http://localhost:5173"]
    _minimal_d1_env(monkeypatch, CORS_ORIGINS="   ")
    s2 = Settings()
    assert s2.CORS_ORIGINS == ["http://localhost:5173"]


def test_cors_origins_comma_separated(monkeypatch: pytest.MonkeyPatch):
    """CORS_ORIGINS as comma-separated => list of origins."""
    _minimal_d1_env(monkeypatch, CORS_ORIGINS="http://a.com,http://b.com")
    s = Settings()
    assert s.CORS_ORIGINS == ["http://a.com", "http://b.com"]


def test_cors_origins_comma_separated_strips_and_filters_empty(monkeypatch: pytest.MonkeyPatch):
    """Comma-separated with spaces and empty segments."""
    _minimal_d1_env(monkeypatch, CORS_ORIGINS=" http://a.com , , http://b.com ")
    s = Settings()
    assert s.CORS_ORIGINS == ["http://a.com", "http://b.com"]


def test_cors_origins_json(monkeypatch: pytest.MonkeyPatch):
    """CORS_ORIGINS as JSON array => list of origins."""
    _minimal_d1_env(monkeypatch, CORS_ORIGINS='["http://a.com"]')
    s = Settings()
    assert s.CORS_ORIGINS == ["http://a.com"]


def test_cors_origins_json_multiple(monkeypatch: pytest.MonkeyPatch):
    """CORS_ORIGINS as JSON array with multiple origins."""
    _minimal_d1_env(monkeypatch, CORS_ORIGINS='["http://a.com", "http://b.com"]')
    s = Settings()
    assert s.CORS_ORIGINS == ["http://a.com", "http://b.com"]


def test_cors_origins_invalid_json_raises(monkeypatch: pytest.MonkeyPatch):
    """CORS_ORIGINS starting with [ but invalid JSON raises ValueError on access."""
    _minimal_d1_env(monkeypatch, CORS_ORIGINS="[invalid")
    s = Settings()
    with pytest.raises(ValueError, match="CORS_ORIGINS: invalid JSON"):
        _ = s.CORS_ORIGINS
