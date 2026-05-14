from __future__ import annotations

import asyncio

import pytest

from src.core.bus import MarketDataBus


@pytest.mark.asyncio
async def test_publish_and_receive():
    bus = MarketDataBus()
    q = bus.subscribe("ticker.BYBIT.BTCUSDT.SPOT")
    bus.publish("ticker.BYBIT.BTCUSDT.SPOT", {"price": 100})
    item = await asyncio.wait_for(q.get(), timeout=1.0)
    assert item == {"price": 100}


@pytest.mark.asyncio
async def test_fan_out_to_multiple_subscribers():
    bus = MarketDataBus()
    q1 = bus.subscribe("ticker.BYBIT.BTCUSDT.SPOT")
    q2 = bus.subscribe("ticker.BYBIT.BTCUSDT.SPOT")
    bus.publish("ticker.BYBIT.BTCUSDT.SPOT", 42)
    assert await asyncio.wait_for(q1.get(), timeout=1.0) == 42
    assert await asyncio.wait_for(q2.get(), timeout=1.0) == 42


def test_no_cross_topic_delivery():
    bus = MarketDataBus()
    q = bus.subscribe("ticker.BYBIT.BTCUSDT.SPOT")
    bus.publish("ticker.BYBIT.ETHUSDT.SPOT", 99)
    assert q.empty()


def test_publish_to_topic_with_no_subscribers_is_noop():
    bus = MarketDataBus()
    # Should not raise
    bus.publish("ticker.BYBIT.BTCUSDT.SPOT", "data")


def test_backpressure_evicts_oldest():
    bus = MarketDataBus()
    q = bus.subscribe("test.topic", maxsize=3)
    for i in range(5):
        bus.publish("test.topic", i)
    items = [q.get_nowait() for _ in range(3)]
    # First two were evicted; newest three remain
    assert items == [2, 3, 4]


def test_unsubscribe_stops_delivery():
    bus = MarketDataBus()
    q = bus.subscribe("test.topic")
    assert bus.subscriber_count("test.topic") == 1
    bus.unsubscribe("test.topic", q)
    assert bus.subscriber_count("test.topic") == 0
    bus.publish("test.topic", "should_not_arrive")
    assert q.empty()


def test_unsubscribe_unknown_queue_is_noop():
    bus = MarketDataBus()
    import asyncio as _asyncio
    phantom: _asyncio.Queue = _asyncio.Queue()
    bus.unsubscribe("nonexistent.topic", phantom)  # must not raise
