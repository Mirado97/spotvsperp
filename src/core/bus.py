from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

_DEFAULT_MAXSIZE = 100


class MarketDataBus:
    """
    In-process pub/sub for market data events.
    Topic format: "ticker.BYBIT.BTCUSDT.SPOT", "funding.BYBIT.BTCUSDT", etc.

    When a subscriber queue is full the oldest item is evicted to make room
    for the newest — stale market data is worse than a gap.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Any]]] = defaultdict(list)

    def subscribe(self, topic: str, maxsize: int = _DEFAULT_MAXSIZE) -> asyncio.Queue[Any]:
        q: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._subscribers[topic].append(q)
        return q

    def unsubscribe(self, topic: str, queue: asyncio.Queue[Any]) -> None:
        try:
            self._subscribers[topic].remove(queue)
        except ValueError:
            pass

    def publish(self, topic: str, data: Any) -> None:
        for q in self._subscribers.get(topic, []):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    def subscriber_count(self, topic: str) -> int:
        return len(self._subscribers.get(topic, []))
