-- ── trades: one row per completed hedge trade ────────────────────────────────
CREATE TABLE IF NOT EXISTS trades (
    id               BIGSERIAL PRIMARY KEY,
    strategy_id      TEXT NOT NULL,
    exchange         TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,          -- "long_carry" | "short_carry"
    qty              DOUBLE PRECISION NOT NULL,
    spot_entry       DOUBLE PRECISION NOT NULL,
    perp_entry       DOUBLE PRECISION NOT NULL,
    entry_basis      DOUBLE PRECISION NOT NULL,
    opened_at        TIMESTAMPTZ NOT NULL,
    closed_at        TIMESTAMPTZ,
    spot_exit        DOUBLE PRECISION,
    perp_exit        DOUBLE PRECISION,
    exit_basis       DOUBLE PRECISION,
    realized_pnl     DOUBLE PRECISION,
    realized_basis   DOUBLE PRECISION,
    status           TEXT NOT NULL DEFAULT 'open'   -- "open" | "closed"
);

-- ── fills: raw order fills ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fills (
    id                BIGSERIAL PRIMARY KEY,
    strategy_id       TEXT,
    exchange          TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    client_order_id   TEXT NOT NULL,
    exchange_order_id TEXT,
    side              TEXT NOT NULL,
    instrument_type   TEXT NOT NULL,   -- "spot" | "perpetual"
    qty               DOUBLE PRECISION NOT NULL,
    price             DOUBLE PRECISION NOT NULL,
    fee               DOUBLE PRECISION NOT NULL DEFAULT 0,
    fee_currency      TEXT NOT NULL DEFAULT 'USDT',
    ts_ms             BIGINT NOT NULL,
    ts                TIMESTAMPTZ GENERATED ALWAYS AS (to_timestamp(ts_ms / 1000.0)) STORED
);

-- ── positions: current open positions per exchange+symbol ─────────────────────
CREATE TABLE IF NOT EXISTS positions (
    exchange        TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    spot_qty        DOUBLE PRECISION NOT NULL DEFAULT 0,
    perp_qty        DOUBLE PRECISION NOT NULL DEFAULT 0,
    spot_avg_price  DOUBLE PRECISION NOT NULL DEFAULT 0,
    perp_avg_price  DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_delta_usd   DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, symbol)
);

-- ── funding: funding rate history ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS funding (
    id          BIGSERIAL PRIMARY KEY,
    exchange    TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    rate        DOUBLE PRECISION NOT NULL,
    predicted   DOUBLE PRECISION NOT NULL,
    regime      TEXT NOT NULL,
    is_extreme  BOOLEAN NOT NULL DEFAULT FALSE,
    ts_ms       BIGINT NOT NULL,
    ts          TIMESTAMPTZ GENERATED ALWAYS AS (to_timestamp(ts_ms / 1000.0)) STORED
);

-- ── basis_history: historical basis snapshots ─────────────────────────────────
CREATE TABLE IF NOT EXISTS basis_history (
    id               BIGSERIAL PRIMARY KEY,
    exchange         TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    spot_mid         DOUBLE PRECISION NOT NULL,
    perp_mid         DOUBLE PRECISION NOT NULL,
    basis            DOUBLE PRECISION NOT NULL,
    basis_bps        DOUBLE PRECISION NOT NULL,
    annualized_basis DOUBLE PRECISION NOT NULL,
    funding_rate     DOUBLE PRECISION NOT NULL,
    carry_score      DOUBLE PRECISION NOT NULL,
    ts_ms            BIGINT NOT NULL,
    ts               TIMESTAMPTZ GENERATED ALWAYS AS (to_timestamp(ts_ms / 1000.0)) STORED
);

-- ── carry_metrics: derived carry analytics ────────────────────────────────────
CREATE TABLE IF NOT EXISTS carry_metrics (
    id                 BIGSERIAL PRIMARY KEY,
    exchange           TEXT NOT NULL,
    symbol             TEXT NOT NULL,
    gross_carry_ann    DOUBLE PRECISION NOT NULL,
    net_carry_ann      DOUBLE PRECISION NOT NULL,
    estimated_cost_ann DOUBLE PRECISION NOT NULL,
    ts_ms              BIGINT NOT NULL,
    ts                 TIMESTAMPTZ GENERATED ALWAYS AS (to_timestamp(ts_ms / 1000.0)) STORED
);

-- ── liquidation_events: raw liquidation feed data ────────────────────────────
CREATE TABLE IF NOT EXISTS liquidation_events (
    id        BIGSERIAL PRIMARY KEY,
    exchange  TEXT NOT NULL,
    symbol    TEXT NOT NULL,
    side      TEXT NOT NULL,   -- "long" | "short"
    qty       DOUBLE PRECISION NOT NULL,
    price     DOUBLE PRECISION NOT NULL,
    value_usd DOUBLE PRECISION NOT NULL,
    ts_ms     BIGINT NOT NULL,
    ts        TIMESTAMPTZ GENERATED ALWAYS AS (to_timestamp(ts_ms / 1000.0)) STORED
);

-- ── spreads: bid-ask spread snapshots ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS spreads (
    id         BIGSERIAL PRIMARY KEY,
    exchange   TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    instrument TEXT NOT NULL,   -- "spot" | "perp"
    bid        DOUBLE PRECISION NOT NULL,
    ask        DOUBLE PRECISION NOT NULL,
    spread_bps DOUBLE PRECISION NOT NULL,
    ts_ms      BIGINT NOT NULL,
    ts         TIMESTAMPTZ GENERATED ALWAYS AS (to_timestamp(ts_ms / 1000.0)) STORED
);

-- ── balances: exchange wallet balances ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS balances (
    exchange   TEXT NOT NULL,
    currency   TEXT NOT NULL,
    available  DOUBLE PRECISION NOT NULL DEFAULT 0,
    total      DOUBLE PRECISION NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, currency)
);

-- ── pnl_history: periodic equity / PnL snapshots ─────────────────────────────
CREATE TABLE IF NOT EXISTS pnl_history (
    id             BIGSERIAL PRIMARY KEY,
    exchange       TEXT NOT NULL,
    total_equity   DOUBLE PRECISION NOT NULL,
    unrealized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
    realized_pnl   DOUBLE PRECISION NOT NULL DEFAULT 0,
    total_fees     DOUBLE PRECISION NOT NULL DEFAULT 0,
    drawdown_pct   DOUBLE PRECISION NOT NULL DEFAULT 0,
    ts             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── latency_metrics: execution latency tracking ──────────────────────────────
CREATE TABLE IF NOT EXISTS latency_metrics (
    id          BIGSERIAL PRIMARY KEY,
    operation   TEXT NOT NULL,   -- "place_order" | "hedge_execute" | "ws_message"
    exchange    TEXT NOT NULL,
    symbol      TEXT,
    latency_ms  DOUBLE PRECISION NOT NULL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── indexes ───────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_fills_symbol_ts       ON fills             (exchange, symbol, ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_trades_symbol         ON trades            (exchange, symbol);
CREATE INDEX IF NOT EXISTS idx_basis_symbol_ts       ON basis_history     (exchange, symbol, ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_funding_symbol_ts     ON funding           (exchange, symbol, ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_liq_symbol_ts         ON liquidation_events(exchange, symbol, ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_latency_operation_ts  ON latency_metrics   (operation, ts DESC);
