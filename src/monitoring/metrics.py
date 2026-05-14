from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Basis / carry ─────────────────────────────────────────────────────────────

basis_bps = Gauge(
    "cex_basis_bps",
    "Current basis in basis points (perp-spot)/spot * 10000",
    ["exchange", "symbol"],
)

carry_score = Gauge(
    "cex_carry_score",
    "Annualised carry attractiveness score (funding_yield + annualised_basis)",
    ["exchange", "symbol"],
)

annualized_basis = Gauge(
    "cex_annualized_basis",
    "Basis annualised (basis * 1095)",
    ["exchange", "symbol"],
)

# ── Funding ───────────────────────────────────────────────────────────────────

funding_rate = Gauge(
    "cex_funding_rate",
    "Current 8-hour funding rate",
    ["exchange", "symbol"],
)

funding_rate_predicted = Gauge(
    "cex_funding_rate_predicted",
    "Predicted next-period funding rate",
    ["exchange", "symbol"],
)

funding_is_extreme = Gauge(
    "cex_funding_is_extreme",
    "1 if funding rate is in extreme regime, 0 otherwise",
    ["exchange", "symbol"],
)

funding_extreme_streak = Gauge(
    "cex_funding_extreme_streak",
    "Consecutive periods of extreme funding",
    ["exchange", "symbol"],
)

# ── Execution ─────────────────────────────────────────────────────────────────

orders_placed_total = Counter(
    "cex_orders_placed_total",
    "Total orders placed",
    ["exchange", "symbol", "side"],
)

orders_filled_total = Counter(
    "cex_orders_filled_total",
    "Total orders fully filled",
    ["exchange", "symbol"],
)

orders_rejected_total = Counter(
    "cex_orders_rejected_total",
    "Total orders rejected by the exchange",
    ["exchange", "symbol"],
)

hedge_success_total = Counter(
    "cex_hedge_success_total",
    "Total successfully executed hedge pairs",
    ["exchange", "symbol"],
)

hedge_failure_total = Counter(
    "cex_hedge_failure_total",
    "Total failed hedge executions",
    ["exchange", "symbol"],
)

# ── Latency ───────────────────────────────────────────────────────────────────

hedge_latency_ms = Histogram(
    "cex_hedge_latency_ms",
    "End-to-end hedge execution latency in milliseconds",
    ["exchange", "symbol"],
    buckets=[5, 10, 25, 50, 100, 200, 500, 1000, 2000],
)

order_place_latency_ms = Histogram(
    "cex_order_place_latency_ms",
    "REST order placement latency in milliseconds",
    ["exchange"],
    buckets=[5, 10, 25, 50, 100, 200, 500, 1000],
)

ws_message_latency_ms = Histogram(
    "cex_ws_message_latency_ms",
    "WebSocket message processing latency in milliseconds",
    ["exchange"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 25, 50],
)

# ── Strategy / workers ────────────────────────────────────────────────────────

worker_state = Gauge(
    "cex_worker_state",
    "Current WorkerState integer value (0=IDLE 1=SEARCHING 3=HOLDING 5=STOPPED)",
    ["exchange", "symbol"],
)

active_workers = Gauge(
    "cex_active_workers",
    "Number of workers not in STOPPED or FAILED state",
    ["exchange"],
)

trades_total = Counter(
    "cex_trades_total",
    "Total completed carry trades (entry counted)",
    ["exchange", "symbol"],
)

# ── Risk ──────────────────────────────────────────────────────────────────────

risk_level = Gauge(
    "cex_risk_level",
    "Current risk level (0=OK 1=WARNING 2=CRITICAL 3=EMERGENCY)",
    ["exchange"],
)

drawdown_pct = Gauge(
    "cex_drawdown_pct",
    "Cumulative fee drawdown as fraction of initial equity",
    ["exchange"],
)

total_exposure_usd = Gauge(
    "cex_total_exposure_usd",
    "Total two-sided position exposure in USD",
    ["exchange"],
)

max_delta_usd = Gauge(
    "cex_max_delta_usd",
    "Largest absolute net delta across all symbols in USD",
    ["exchange"],
)

# ── Exchange health ───────────────────────────────────────────────────────────

ws_connected = Gauge(
    "cex_ws_connected",
    "1 if WebSocket feed is connected, 0 otherwise",
    ["exchange"],
)

ws_reconnects_total = Counter(
    "cex_ws_reconnects_total",
    "Total WebSocket reconnection attempts",
    ["exchange"],
)

# ── Balances ──────────────────────────────────────────────────────────────────

equity_usd = Gauge(
    "cex_equity_usd",
    "Total account equity in USD",
    ["exchange"],
)

balance_available = Gauge(
    "cex_balance_available",
    "Available (unreserved) wallet balance",
    ["exchange", "currency"],
)
