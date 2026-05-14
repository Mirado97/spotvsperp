from __future__ import annotations

# WebSocket path suffixes appended to ws_public_url
SPOT_PATH = "/spot"
LINEAR_PATH = "/linear"  # USDT perpetuals

HEARTBEAT_INTERVAL = 20.0  # seconds; Bybit drops connection after 30s silence


# ── Bybit topic builders ───────────────────────────────────────────────────────

def ticker_topic(symbol: str) -> str:
    return f"tickers.{symbol}"


def orderbook_topic(symbol: str, depth: int = 50) -> str:
    return f"orderbook.{depth}.{symbol}"


def trade_topic(symbol: str) -> str:
    return f"publicTrade.{symbol}"


def liquidation_topic(symbol: str) -> str:
    return f"liquidation.{symbol}"


# ── MarketDataBus topic builders ──────────────────────────────────────────────

def bus_ticker_topic(exchange: str, symbol: str, category: str) -> str:
    return f"ticker.{exchange}.{symbol}.{category}"


def bus_orderbook_topic(exchange: str, symbol: str, category: str) -> str:
    return f"orderbook.{exchange}.{symbol}.{category}"


def bus_funding_topic(exchange: str, symbol: str) -> str:
    return f"funding.{exchange}.{symbol}"


def bus_oi_topic(exchange: str, symbol: str) -> str:
    return f"oi.{exchange}.{symbol}"


def bus_liquidation_topic(exchange: str, symbol: str) -> str:
    return f"liquidation.{exchange}.{symbol}"
