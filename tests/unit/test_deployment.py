"""Smoke tests: verify all production modules import cleanly."""
from __future__ import annotations

import importlib
import pathlib


# ── Import smoke tests ────────────────────────────────────────────────────────

def _import(module: str) -> None:
    importlib.import_module(module)


def test_import_main():
    _import("src.main")


def test_import_core():
    _import("src.core.app")
    _import("src.core.bus")
    _import("src.core.config")
    _import("src.core.container")
    _import("src.core.logging_setup")


def test_import_exchange():
    _import("src.exchange.bybit.market_feed")
    _import("src.exchange.bybit.rest_client")
    _import("src.exchange.bybit.ws_client")


def test_import_engines():
    _import("src.basis.engine")
    _import("src.funding.engine")
    _import("src.liquidation.engine")


def test_import_execution():
    _import("src.execution.bybit_executor")
    _import("src.execution.hedge_engine")
    _import("src.execution.order_tracker")


def test_import_risk():
    _import("src.risk.engine")
    _import("src.risk.models")


def test_import_strategy():
    _import("src.strategy.carry_worker")
    _import("src.strategy.orchestrator")
    _import("src.strategy.watchdog")


def test_import_storage():
    _import("src.storage.manager")
    _import("src.storage.writer")
    _import("src.storage.repositories")


def test_import_monitoring():
    _import("src.monitoring.manager")
    _import("src.monitoring.collector")
    _import("src.monitoring.exporter")
    _import("src.monitoring.metrics")


def test_import_api():
    _import("src.api.manager")
    _import("src.api.ws_server")
    _import("src.api.serializers")


def test_import_backtest():
    _import("src.backtest.engine")
    _import("src.backtest.monte_carlo")
    _import("src.backtest.simulator")


# ── Config and env files ──────────────────────────────────────────────────────

def test_env_example_exists():
    assert pathlib.Path(".env.example").exists() or \
           pathlib.Path("D:/Antigravity/Progect/CEXvsCEX/.env.example").exists()


def test_dockerfile_exists():
    root = pathlib.Path(__file__).parent.parent.parent
    assert (root / "Dockerfile").exists()
    assert (root / "frontend" / "Dockerfile").exists()


def test_docker_compose_exists():
    root = pathlib.Path(__file__).parent.parent.parent
    assert (root / "docker-compose.yml").exists()


def test_k8s_manifests_exist():
    root = pathlib.Path(__file__).parent.parent.parent
    k8s = root / "k8s"
    expected = [
        "namespace.yaml",
        "configmap.yaml",
        "secrets.yaml",
        "postgres-statefulset.yaml",
        "redis-deployment.yaml",
        "backend-deployment.yaml",
        "frontend-deployment.yaml",
    ]
    for name in expected:
        assert (k8s / name).exists(), f"Missing k8s manifest: {name}"


def test_prometheus_config_exists():
    root = pathlib.Path(__file__).parent.parent.parent
    assert (root / "prometheus.yml").exists()


def test_nginx_config_exists():
    root = pathlib.Path(__file__).parent.parent.parent
    assert (root / "nginx" / "nginx.conf").exists()


# ── next.config.ts has standalone output ─────────────────────────────────────

def test_next_config_standalone():
    root = pathlib.Path(__file__).parent.parent.parent
    content = (root / "frontend" / "next.config.mjs").read_text()
    assert 'output: "standalone"' in content or "output: 'standalone'" in content
