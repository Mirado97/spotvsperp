from __future__ import annotations

import os

import pytest

from src.core.config import _deep_merge, load_settings


def test_deep_merge_nested():
    base = {"a": 1, "b": {"c": 2, "d": 3}, "e": {"f": 4}}
    override = {"b": {"c": 99}, "g": 5}
    result = _deep_merge(base, override)
    assert result == {"a": 1, "b": {"c": 99, "d": 3}, "e": {"f": 4}, "g": 5}


def test_deep_merge_override_non_dict():
    base = {"a": {"b": 1}}
    override = {"a": "scalar"}
    result = _deep_merge(base, override)
    assert result["a"] == "scalar"


def test_load_development_settings():
    settings = load_settings("development")
    assert settings.app.name == "cexvscex"
    assert settings.app.debug is True
    assert settings.logging.format == "console"
    assert settings.logging.level == "DEBUG"
    assert settings.exchanges.bybit is not None
    assert settings.exchanges.bybit.testnet is True


def test_load_production_settings():
    settings = load_settings("production")
    assert settings.exchanges.bybit is not None
    assert settings.exchanges.bybit.testnet is False
    assert settings.logging.format == "json"


def test_env_var_override(monkeypatch):
    monkeypatch.setenv("APP_LOGGING__LEVEL", "WARNING")
    settings = load_settings("development")
    assert settings.logging.level == "WARNING"


def test_env_var_override_nested_risk(monkeypatch):
    monkeypatch.setenv("APP_RISK__MAX_POSITION_USD", "5000.0")
    settings = load_settings("development")
    # env override delivers string; pydantic coerces to float
    assert float(settings.risk.max_position_usd) == 5000.0


def test_bybit_exchange_config():
    settings = load_settings("development")
    bybit = settings.exchanges.bybit
    assert bybit is not None
    assert "bybit.com" in bybit.ws_public_url
    assert bybit.rate_limit.requests_per_second == 10
    assert bybit.reconnect.max_attempts == 10


def test_container_register_get():
    from src.core.container import ServiceContainer

    container = ServiceContainer()

    class FakeService:
        value = 42

    svc = FakeService()
    container.register(FakeService, svc)
    assert container.get(FakeService) is svc


def test_container_missing_raises():
    from src.core.container import ServiceContainer

    container = ServiceContainer()

    class Missing:
        pass

    with pytest.raises(KeyError, match="Missing"):
        container.get(Missing)


@pytest.mark.asyncio
async def test_container_lifecycle_order():
    from src.core.container import ServiceContainer

    container = ServiceContainer()
    order: list[str] = []

    async def startup_a() -> None:
        order.append("startup_a")

    async def startup_b() -> None:
        order.append("startup_b")

    async def shutdown_a() -> None:
        order.append("shutdown_a")

    async def shutdown_b() -> None:
        order.append("shutdown_b")

    container.on_startup(startup_a)
    container.on_startup(startup_b)
    container.on_shutdown(shutdown_a)
    container.on_shutdown(shutdown_b)

    await container.startup()
    await container.shutdown()

    assert order == ["startup_a", "startup_b", "shutdown_b", "shutdown_a"]
