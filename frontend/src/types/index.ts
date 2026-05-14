export interface BasisRow {
  symbol: string;
  basis_bps: number;
  carry_score: number;
  spot_mid: number;
  perp_mid: number;
  funding_rate: number;
  funding_yield_ann: number;
  annualized_basis: number;
  perp_premium: number;
  ts_ms: number;
}

export interface FundingRow {
  symbol: string;
  current_rate: number;
  predicted_rate: number;
  ewma_rate: number;
  regime: string;
  is_extreme: boolean;
  extreme_streak: number;
  annualized_carry: number;
  z_score: number;
  ts_ms: number;
}

export interface PositionRow {
  symbol: string;
  spot_qty: number;
  perp_qty: number;
  spot_avg_price: number;
  perp_avg_price: number;
  net_delta_usd: number;
  updated_at?: string;
}

export interface RiskState {
  level: number;             // 0=OK 1=WARNING 2=CRITICAL 3=EMERGENCY
  drawdown_pct: number;
  total_exposure_usd: number;
  max_delta_usd: number;
}

export interface WorkerRow {
  symbol: string;
  state: number;             // WorkerState int
  periods_held: number;
  total_trades: number;
  heartbeat: number;
  restart_count: number;
}

export interface FillRow {
  symbol: string;
  side: number;              // OrderSide int
  qty: number;
  price: number;
  fee: number;
  fee_currency: string;
  instrument_type: number;
  ts_ms: number;
}

export interface LiqAlertRow {
  symbol: string;
  long_value_usd: number;
  short_value_usd: number;
  net_pressure: number;
  is_long_squeeze: boolean;
  is_short_squeeze: boolean;
  ts_ms: number;
}

// WebSocket message envelope
export interface WsMessage {
  type: "basis" | "funding" | "risk_alert" | "risk_snapshot" | "fill"
      | "liq_alert" | "workers" | "balance" | "equity";
  exchange: string;
  symbol?: string;
  data: Record<string, unknown>;
}

// Named constants
export const WORKER_STATE_LABELS: Record<number, string> = {
  0: "IDLE", 1: "SEARCHING", 2: "EXECUTING",
  3: "HOLDING", 4: "CLOSING", 5: "STOPPED", 6: "FAILED",
};

export const RISK_LEVEL_LABELS: Record<number, string> = {
  0: "OK", 1: "WARNING", 2: "CRITICAL", 3: "EMERGENCY",
};
