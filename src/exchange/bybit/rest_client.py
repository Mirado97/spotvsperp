from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import aiohttp

from src.core.logging_setup import get_logger
from src.models.execution import OrderRequest
from src.models.orders import OrderSide, OrderStatus, OrderType, Order
from src.models.market import Exchange

logger = get_logger(__name__)

_TESTNET_URL = "https://api-testnet.bybit.com"
_MAINNET_URL = "https://api.bybit.com"

_RECV_WINDOW = "5000"

# ── OrderType → Bybit timeInForce ─────────────────────────────────────────────
_TIF: dict[OrderType, str] = {
    OrderType.LIMIT:     "GTC",
    OrderType.POST_ONLY: "PostOnly",
    OrderType.IOC:       "IOC",
    OrderType.FOK:       "FOK",
    OrderType.MARKET:    "GTC",  # not used but prevents KeyError
}

_SIDE: dict[OrderSide, str] = {
    OrderSide.BUY:  "Buy",
    OrderSide.SELL: "Sell",
}

_STATUS_MAP: dict[str, OrderStatus] = {
    "New":              OrderStatus.NEW,
    "PartiallyFilled":  OrderStatus.PARTIALLY_FILLED,
    "Filled":           OrderStatus.FILLED,
    "Cancelled":        OrderStatus.CANCELLED,
    "Rejected":         OrderStatus.REJECTED,
    "Deactivated":      OrderStatus.CANCELLED,
    "Untriggered":      OrderStatus.NEW,
}


class BybitRestClient:
    """
    Bybit V5 private REST client.

    Handles HMAC-SHA256 request signing.
    All methods are async and share a single aiohttp.ClientSession (lazy-init).
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = True,
        base_url: str | None = None,
    ) -> None:
        self._key = api_key
        self._secret = api_secret
        self._base = base_url or (_TESTNET_URL if testnet else _MAINNET_URL)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Content-Type": "application/json"},
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Signing ───────────────────────────────────────────────────────────────

    def _sign(self, body: str) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        payload = ts + self._key + _RECV_WINDOW + body
        sig = hmac.new(
            self._secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-BAPI-API-KEY":      self._key,
            "X-BAPI-TIMESTAMP":    ts,
            "X-BAPI-SIGN":         sig,
            "X-BAPI-RECV-WINDOW":  _RECV_WINDOW,
        }

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        import orjson
        raw = orjson.dumps(body).decode()
        headers = self._sign(raw)
        session = await self._get_session()
        async with session.post(
            f"{self._base}{path}",
            data=raw,
            headers=headers,
        ) as resp:
            data = await resp.json(content_type=None)
        if data.get("retCode", -1) != 0:
            logger.warning(
                "bybit_rest.error",
                path=path,
                code=data.get("retCode"),
                msg=data.get("retMsg"),
            )
        return data

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        import urllib.parse
        qs = urllib.parse.urlencode(params)
        headers = self._sign(qs)
        session = await self._get_session()
        async with session.get(
            f"{self._base}{path}",
            params=params,
            headers=headers,
        ) as resp:
            data = await resp.json(content_type=None)
        return data

    async def _get_public(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        # Public market data: always mainnet, fresh session without Content-Type
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{_MAINNET_URL}{path}", params=params) as resp:
                return await resp.json(content_type=None)

    # ── Order API ─────────────────────────────────────────────────────────────

    async def place_order(self, request: OrderRequest) -> str:
        """Submit order. Returns exchange orderId."""
        body: dict[str, Any] = {
            "category":    request.category,
            "symbol":      request.symbol,
            "side":        _SIDE[request.side],
            "orderType":   "Market" if request.order_type == OrderType.MARKET else "Limit",
            "qty":         str(request.qty),
            "timeInForce": _TIF[request.order_type],
            "orderLinkId": request.client_order_id,
        }
        if request.price > 0 and request.order_type != OrderType.MARKET:
            body["price"] = str(request.price)
        if request.reduce_only:
            body["reduceOnly"] = True

        resp = await self._post("/v5/order/create", body)
        return resp.get("result", {}).get("orderId", "")

    async def cancel_order(self, symbol: str, client_order_id: str, category: str = "linear") -> bool:
        resp = await self._post("/v5/order/cancel", {
            "category":    category,
            "symbol":      symbol,
            "orderLinkId": client_order_id,
        })
        return resp.get("retCode", -1) == 0

    async def amend_order(
        self,
        symbol: str,
        client_order_id: str,
        new_price: float,
        category: str = "linear",
    ) -> bool:
        resp = await self._post("/v5/order/amend", {
            "category":    category,
            "symbol":      symbol,
            "orderLinkId": client_order_id,
            "price":       str(new_price),
        })
        return resp.get("retCode", -1) == 0

    async def get_order(
        self,
        symbol: str,
        client_order_id: str,
        category: str = "linear",
    ) -> dict[str, Any] | None:
        resp = await self._get("/v5/order/realtime", {
            "category":    category,
            "symbol":      symbol,
            "orderLinkId": client_order_id,
        })
        items = resp.get("result", {}).get("list", [])
        return items[0] if items else None

    async def get_wallet_balance(self, coin: str = "USDT") -> float:
        resp = await self._get("/v5/account/wallet-balance", {
            "accountType": "UNIFIED",
            "coin": coin,
        })
        coins = (
            resp.get("result", {})
                .get("list", [{}])[0]
                .get("coin", [])
        )
        for c in coins:
            if c.get("coin") == coin:
                return float(c.get("walletBalance", 0))
        return 0.0

    async def get_linear_ticker(self, symbol: str) -> dict[str, Any] | None:
        """Fetch a single linear/perpetual ticker via public REST (no auth required)."""
        resp = await self._get_public(
            "/v5/market/tickers",
            {"category": "linear", "symbol": symbol},
        )
        items = resp.get("result", {}).get("list", [])
        return items[0] if items else None

    async def get_all_linear_tickers(self) -> list[dict[str, Any]]:
        """Fetch all linear/perpetual tickers in one request."""
        try:
            resp = await self._get_public("/v5/market/tickers", {"category": "linear"})
        except Exception:
            logger.exception("bybit_rest.get_all_linear_tickers_error")
            return []
        items = resp.get("result", {}).get("list", [])
        if not items:
            logger.warning("bybit_rest.get_all_linear_tickers_empty", resp_keys=list(resp.keys()),
                           ret_code=resp.get("retCode"), ret_msg=resp.get("retMsg"))
        return items

    async def get_top_usdt_perp_symbols(self, n: int = 100) -> list[str]:
        """Return top-N USDT-margined perpetual symbols sorted by 24h turnover."""
        tickers = await self.get_all_linear_tickers()
        usdt_perps = [
            t for t in tickers
            if t.get("symbol", "").endswith("USDT")
            and t.get("contractType", "") == "LinearPerpetual"
        ]
        usdt_perps.sort(key=lambda t: float(t.get("turnover24h") or 0), reverse=True)
        return [t["symbol"] for t in usdt_perps[:n]]
