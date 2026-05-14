from __future__ import annotations

import msgspec
import orjson


def _struct_to_dict(obj) -> dict:
    """Serialize msgspec Struct → plain Python dict via JSON round-trip."""
    return orjson.loads(msgspec.json.encode(obj))


def basis_msg(exchange: str, symbol: str, snap) -> str:
    return orjson.dumps({
        "type": "basis",
        "exchange": exchange,
        "symbol": symbol,
        "data": _struct_to_dict(snap),
    }).decode()


def funding_msg(exchange: str, symbol: str, analysis) -> str:
    return orjson.dumps({
        "type": "funding",
        "exchange": exchange,
        "symbol": symbol,
        "data": _struct_to_dict(analysis),
    }).decode()


def risk_alert_msg(exchange: str, alert) -> str:
    return orjson.dumps({
        "type": "risk_alert",
        "exchange": exchange,
        "data": _struct_to_dict(alert),
    }).decode()


def risk_snapshot_msg(exchange: str, snap) -> str:
    return orjson.dumps({
        "type": "risk_snapshot",
        "exchange": exchange,
        "data": _struct_to_dict(snap),
    }).decode()


def fill_msg(exchange: str, symbol: str, fill) -> str:
    return orjson.dumps({
        "type": "fill",
        "exchange": exchange,
        "symbol": symbol,
        "data": _struct_to_dict(fill),
    }).decode()


def liq_alert_msg(exchange: str, symbol: str, alert) -> str:
    return orjson.dumps({
        "type": "liq_alert",
        "exchange": exchange,
        "symbol": symbol,
        "data": _struct_to_dict(alert),
    }).decode()


def workers_msg(exchange: str, statuses: list) -> str:
    return orjson.dumps({
        "type": "workers",
        "exchange": exchange,
        "data": [_struct_to_dict(s) for s in statuses],
    }).decode()


def balance_msg(exchange: str, currency: str, available: float, total: float) -> str:
    return orjson.dumps({
        "type": "balance",
        "exchange": exchange,
        "data": {"currency": currency, "available": available, "total": total},
    }).decode()


def equity_msg(exchange: str, total_equity: float) -> str:
    return orjson.dumps({
        "type": "equity",
        "exchange": exchange,
        "data": {"total_equity": total_equity},
    }).decode()
