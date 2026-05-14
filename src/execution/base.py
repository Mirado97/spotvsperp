from __future__ import annotations

from abc import ABC, abstractmethod

from src.models.execution import OrderRequest
from src.models.orders import Order


class BaseExecutor(ABC):
    """Interface that HedgeEngine depends on. Allows fake implementations in tests."""

    @abstractmethod
    async def place(self, request: OrderRequest) -> Order: ...

    @abstractmethod
    async def cancel(self, client_order_id: str) -> bool: ...

    @abstractmethod
    async def reprice(self, client_order_id: str, new_price: float) -> str | None:
        """Cancel current order and place new one at new_price.
        Returns new client_order_id, or None if original already terminal."""
        ...
