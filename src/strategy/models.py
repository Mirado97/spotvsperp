from __future__ import annotations

import dataclasses
from enum import IntEnum

import msgspec


class WorkerState(IntEnum):
    IDLE      = 0
    SEARCHING = 1   # scanning for entry
    EXECUTING = 2   # hedge order in flight
    HOLDING   = 3   # position open, monitoring
    CLOSING   = 4   # closing hedge in flight
    STOPPED   = 5   # graceful stop
    FAILED    = 6   # exceeded max restarts


@dataclasses.dataclass
class StrategyConfig:
    """Per-symbol carry strategy parameters."""
    symbol: str
    min_carry_score: float = 0.05        # 5% annualized carry minimum to enter
    entry_z_score: float = 1.0           # basis z-score (from signal) to enter
    exit_z_score: float = 0.0            # z-score at which we consider basis reverted
    max_holding_periods: int = 21        # 21 × 8h = 7 days forced exit
    position_qty: float = 0.01           # base currency per trade
    heartbeat_timeout_s: float = 30.0    # watchdog considers worker dead after this
    max_restarts: int = 3                # watchdog gives up after this many restarts
    exchange: str = "BYBIT"


class WorkerStatus(msgspec.Struct, frozen=True, gc=False):
    """Point-in-time health report published by each worker."""
    symbol: str
    state: int           # WorkerState value
    heartbeat: float     # unix timestamp of last heartbeat
    periods_held: int
    total_trades: int
    restart_count: int
    ts_ms: int

    @property
    def worker_state(self) -> WorkerState:
        return WorkerState(self.state)

    @property
    def is_alive(self) -> bool:
        return self.state not in (int(WorkerState.STOPPED), int(WorkerState.FAILED))
