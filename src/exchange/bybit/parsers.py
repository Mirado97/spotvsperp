from __future__ import annotations

from typing import Any

from src.models.funding import FundingRate
from src.models.liquidation import LiquidationEvent
from src.models.market import Exchange, InstrumentType, OpenInterest, Ticker

_EXCHANGE = Exchange.BYBIT


def _float(d: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    """Return the first truthy key value as float, or default."""
    for k in keys:
        v = d.get(k)
        if v:
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    return default


def parse_spot_ticker(data: dict[str, Any], ts_ms: int) -> Ticker | None:
    try:
        d: dict[str, Any] = data["data"]
        symbol: str = d["symbol"]
        last = _float(d, "lastPrice")
        return Ticker(
            exchange=_EXCHANGE,
            symbol=symbol,
            instrument_type=InstrumentType.SPOT,
            bid=_float(d, "bid1Price", "lastPrice"),
            ask=_float(d, "ask1Price", "lastPrice"),
            last=last,
            volume_24h=_float(d, "volume24h"),
            ts_ms=ts_ms,
        )
    except (KeyError, TypeError):
        return None


def parse_linear_ticker(
    data: dict[str, Any], ts_ms: int
) -> tuple[Ticker | None, FundingRate | None, OpenInterest | None]:
    """
    Linear ticker carries spot-equiv ticker + funding + OI in one message.
    Returns a 3-tuple; any element can be None if data is absent.
    """
    try:
        d: dict[str, Any] = data["data"]
        symbol: str = d["symbol"]
        last = _float(d, "lastPrice")

        ticker = Ticker(
            exchange=_EXCHANGE,
            symbol=symbol,
            instrument_type=InstrumentType.PERPETUAL,
            bid=_float(d, "bid1Price", "lastPrice"),
            ask=_float(d, "ask1Price", "lastPrice"),
            last=last,
            volume_24h=_float(d, "volume24h"),
            ts_ms=ts_ms,
        )

        funding: FundingRate | None = None
        if d.get("fundingRate") and d.get("nextFundingTime"):
            funding = FundingRate(
                exchange=_EXCHANGE,
                symbol=symbol,
                rate=float(d["fundingRate"]),
                predicted=_float(d, "predictedFundingRate", "fundingRate"),
                next_funding_ts=int(d["nextFundingTime"]),
                interval_h=8,
                ts_ms=ts_ms,
            )

        oi: OpenInterest | None = None
        if d.get("openInterest"):
            oi = OpenInterest(
                exchange=_EXCHANGE,
                symbol=symbol,
                oi=float(d["openInterest"]),
                oi_value=_float(d, "openInterestValue"),
                ts_ms=ts_ms,
            )

        return ticker, funding, oi

    except (KeyError, TypeError):
        return None, None, None


def parse_liquidation(data: dict[str, Any], ts_ms: int) -> LiquidationEvent | None:
    """
    Parse a Bybit liquidation WS message.
    Bybit side semantics: "Buy" = market buy to cover → long position liquidated.
    """
    try:
        d: dict[str, Any] = data["data"]
        bybit_side: str = d["side"]
        qty = float(d["size"])
        price = float(d["price"])
        return LiquidationEvent(
            exchange=_EXCHANGE,
            symbol=d["symbol"],
            side="long" if bybit_side == "Buy" else "short",
            qty=qty,
            price=price,
            value_usd=qty * price,
            ts_ms=ts_ms,
        )
    except (KeyError, TypeError, ValueError):
        return None
