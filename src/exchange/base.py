from __future__ import annotations

from abc import ABC, abstractmethod


class ExchangeMarketFeed(ABC):
    """Abstract market data feed. Each exchange adapter implements this."""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def subscribe_spot_ticker(self, symbol: str) -> None: ...

    @abstractmethod
    async def subscribe_perp_ticker(self, symbol: str) -> None: ...

    @abstractmethod
    async def subscribe_spot_orderbook(self, symbol: str, depth: int = 50) -> None: ...

    @abstractmethod
    async def subscribe_perp_orderbook(self, symbol: str, depth: int = 50) -> None: ...

    @abstractmethod
    async def subscribe_liquidations(self, symbol: str) -> None: ...
