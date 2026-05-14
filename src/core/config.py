from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


class ReconnectConfig(BaseModel):
    max_attempts: int = 10
    base_delay: float = 1.0
    max_delay: float = 60.0


class RateLimitConfig(BaseModel):
    requests_per_second: int = 10
    orders_per_second: int = 5


class ExchangeConfig(BaseModel):
    enabled: bool = True
    testnet: bool = False
    ws_public_url: str
    ws_private_url: str
    rest_url: str
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    reconnect: ReconnectConfig = Field(default_factory=ReconnectConfig)


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "json"


class AppConfig(BaseModel):
    name: str = "cexvscex"
    env: str = "development"
    debug: bool = False


class RiskConfig(BaseModel):
    max_position_usd: float = 10_000.0
    max_total_exposure_usd: float = 50_000.0
    max_exchange_exposure_usd: float = 25_000.0
    min_funding_threshold: float = 0.0001
    max_basis_pct: float = 2.0


class MonitoringConfig(BaseModel):
    health_check_interval: int = 30
    metrics_port: int = 9090


class ExchangesConfig(BaseModel):
    bybit: ExchangeConfig | None = None


class StrategiesConfig(BaseModel):
    enabled: list[str] = Field(default_factory=list)


class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    exchanges: ExchangesConfig = Field(default_factory=ExchangesConfig)
    strategies: StrategiesConfig = Field(default_factory=StrategiesConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_env_overrides(config: dict[str, Any]) -> None:
    """Apply APP__ prefixed env vars. APP_LOGGING__LEVEL=DEBUG → config["logging"]["level"] = "DEBUG"."""
    prefix = "APP_"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = key[len(prefix):].lower().split("__")
        node = config
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = value


def load_settings(env: str | None = None) -> Settings:
    env = env or os.getenv("APP_ENV", "development")
    base = _load_yaml(CONFIG_DIR / "base.yaml")
    override = _load_yaml(CONFIG_DIR / f"{env}.yaml")
    merged = _deep_merge(base, override)
    _apply_env_overrides(merged)
    return Settings.model_validate(merged)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings
