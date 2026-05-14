from __future__ import annotations

import datetime
from typing import Any

from src.basis.models import BasisSnapshot, CarryMetrics
from src.funding.models import FundingAnalysis
from src.models.liquidation import LiquidationEvent
from src.models.orders import Fill
from src.storage.postgres import PostgresPool


class TradeRepository:
    """Insert / query trades and fills."""

    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    async def insert_trade(
        self,
        strategy_id: str,
        exchange: str,
        symbol: str,
        side: str,
        qty: float,
        spot_entry: float,
        perp_entry: float,
        entry_basis: float,
        opened_at: datetime.datetime,
    ) -> int:
        return await self._pool.fetchval(
            """
            INSERT INTO trades
                (strategy_id, exchange, symbol, side, qty,
                 spot_entry, perp_entry, entry_basis, opened_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING id
            """,
            strategy_id, exchange, symbol, side, qty,
            spot_entry, perp_entry, entry_basis, opened_at,
        )

    async def close_trade(
        self,
        trade_id: int,
        spot_exit: float,
        perp_exit: float,
        exit_basis: float,
        realized_pnl: float,
        realized_basis: float,
    ) -> None:
        await self._pool.execute(
            """
            UPDATE trades
            SET closed_at=NOW(), spot_exit=$2, perp_exit=$3,
                exit_basis=$4, realized_pnl=$5, realized_basis=$6, status='closed'
            WHERE id=$1
            """,
            trade_id, spot_exit, perp_exit,
            exit_basis, realized_pnl, realized_basis,
        )

    async def insert_fill(self, fill: Fill, strategy_id: str | None = None) -> None:
        await self._pool.execute(
            """
            INSERT INTO fills
                (strategy_id, exchange, symbol, client_order_id, exchange_order_id,
                 side, instrument_type, qty, price, fee, fee_currency, ts_ms)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            """,
            strategy_id,
            fill.exchange.name,
            fill.symbol,
            fill.order_id,
            fill.fill_id,
            fill.side.name,
            fill.instrument_type.name,
            fill.qty,
            fill.price,
            fill.fee,
            fill.fee_currency,
            fill.ts_ms,
        )

    async def get_open_trades(self, exchange: str, symbol: str) -> list[Any]:
        return await self._pool.fetch(
            "SELECT * FROM trades WHERE exchange=$1 AND symbol=$2 AND status='open'",
            exchange, symbol,
        )


class PositionRepository:
    """Upsert and query current positions."""

    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    async def upsert(
        self,
        exchange: str,
        symbol: str,
        spot_qty: float,
        perp_qty: float,
        spot_avg_price: float,
        perp_avg_price: float,
        net_delta_usd: float,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO positions
                (exchange, symbol, spot_qty, perp_qty,
                 spot_avg_price, perp_avg_price, net_delta_usd, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
            ON CONFLICT (exchange, symbol) DO UPDATE SET
                spot_qty=$3, perp_qty=$4,
                spot_avg_price=$5, perp_avg_price=$6,
                net_delta_usd=$7, updated_at=NOW()
            """,
            exchange, symbol, spot_qty, perp_qty,
            spot_avg_price, perp_avg_price, net_delta_usd,
        )

    async def get(self, exchange: str, symbol: str) -> Any:
        return await self._pool.fetchrow(
            "SELECT * FROM positions WHERE exchange=$1 AND symbol=$2",
            exchange, symbol,
        )

    async def get_all(self) -> list[Any]:
        return await self._pool.fetch("SELECT * FROM positions ORDER BY exchange, symbol")


class MarketRepository:
    """Insert market data: basis, funding, carry metrics, liquidations, spreads."""

    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    async def insert_basis(self, snap: BasisSnapshot) -> None:
        await self._pool.execute(
            """
            INSERT INTO basis_history
                (exchange, symbol, spot_mid, perp_mid, basis, basis_bps,
                 annualized_basis, funding_rate, carry_score, ts_ms)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            """,
            snap.exchange.name, snap.symbol,
            snap.spot_mid, snap.perp_mid,
            snap.basis, snap.basis_bps,
            snap.annualized_basis, snap.funding_rate,
            snap.carry_score, snap.ts_ms,
        )

    async def insert_funding(self, analysis: FundingAnalysis) -> None:
        await self._pool.execute(
            """
            INSERT INTO funding
                (exchange, symbol, rate, predicted, regime, is_extreme, ts_ms)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            """,
            analysis.exchange.name, analysis.symbol,
            analysis.current_rate, analysis.predicted_rate,
            analysis.regime, analysis.is_extreme,
            analysis.ts_ms,
        )

    async def insert_carry(self, metrics: CarryMetrics) -> None:
        await self._pool.execute(
            """
            INSERT INTO carry_metrics
                (exchange, symbol, gross_carry_ann, net_carry_ann,
                 estimated_cost_ann, ts_ms)
            VALUES ($1,$2,$3,$4,$5,$6)
            """,
            metrics.exchange.name, metrics.symbol,
            metrics.gross_carry_ann, metrics.net_carry_ann,
            metrics.estimated_cost_ann, metrics.ts_ms,
        )

    async def insert_liquidation(self, event: LiquidationEvent) -> None:
        await self._pool.execute(
            """
            INSERT INTO liquidation_events
                (exchange, symbol, side, qty, price, value_usd, ts_ms)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            """,
            event.exchange.name, event.symbol,
            event.side, event.qty, event.price,
            event.value_usd, event.ts_ms,
        )

    async def insert_spread(
        self,
        exchange: str,
        symbol: str,
        instrument: str,
        bid: float,
        ask: float,
        spread_bps: float,
        ts_ms: int,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO spreads
                (exchange, symbol, instrument, bid, ask, spread_bps, ts_ms)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            """,
            exchange, symbol, instrument, bid, ask, spread_bps, ts_ms,
        )


class BalanceRepository:
    """Upsert wallet balances and insert PnL snapshots."""

    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    async def upsert(
        self,
        exchange: str,
        currency: str,
        available: float,
        total: float,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO balances (exchange, currency, available, total, updated_at)
            VALUES ($1,$2,$3,$4,NOW())
            ON CONFLICT (exchange, currency) DO UPDATE SET
                available=$3, total=$4, updated_at=NOW()
            """,
            exchange, currency, available, total,
        )

    async def insert_pnl(
        self,
        exchange: str,
        total_equity: float,
        unrealized_pnl: float = 0.0,
        realized_pnl: float = 0.0,
        total_fees: float = 0.0,
        drawdown_pct: float = 0.0,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO pnl_history
                (exchange, total_equity, unrealized_pnl,
                 realized_pnl, total_fees, drawdown_pct)
            VALUES ($1,$2,$3,$4,$5,$6)
            """,
            exchange, total_equity, unrealized_pnl,
            realized_pnl, total_fees, drawdown_pct,
        )


class MetricsRepository:
    """Insert latency metrics."""

    def __init__(self, pool: PostgresPool) -> None:
        self._pool = pool

    async def insert_latency(
        self,
        operation: str,
        exchange: str,
        latency_ms: float,
        symbol: str | None = None,
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO latency_metrics (operation, exchange, symbol, latency_ms)
            VALUES ($1,$2,$3,$4)
            """,
            operation, exchange, symbol, latency_ms,
        )
