import { create } from "zustand";
import type {
  BasisRow, FundingRow, PositionRow, RiskState,
  WorkerRow, FillRow,
} from "@/types";

const MAX_FILLS = 200;

interface TerminalStore {
  connected: boolean;
  exchange: string;
  basis: Record<string, BasisRow>;
  funding: Record<string, FundingRow>;
  positions: Record<string, PositionRow>;
  risk: RiskState;
  workers: Record<string, WorkerRow>;
  fills: FillRow[];
  balance_usdt: number;
  equity: number;

  // Actions
  setConnected: (v: boolean) => void;
  setExchange: (v: string) => void;
  updateBasis: (symbol: string, data: Partial<BasisRow>) => void;
  updateFunding: (symbol: string, data: Partial<FundingRow>) => void;
  updatePosition: (symbol: string, data: Partial<PositionRow>) => void;
  updateRisk: (data: Partial<RiskState>) => void;
  updateWorker: (symbol: string, data: Partial<WorkerRow>) => void;
  addFill: (fill: FillRow) => void;
  setBalance: (usdt: number) => void;
  setEquity: (equity: number) => void;
}

export const useTerminalStore = create<TerminalStore>((set) => ({
  connected: false,
  exchange: "BYBIT",
  basis: {},
  funding: {},
  positions: {},
  risk: { level: 0, drawdown_pct: 0, total_exposure_usd: 0, max_delta_usd: 0 },
  workers: {},
  fills: [],
  balance_usdt: 0,
  equity: 0,

  setConnected: (v) => set({ connected: v }),
  setExchange: (v) => set({ exchange: v }),

  updateBasis: (symbol, data) =>
    set((s) => ({
      basis: { ...s.basis, [symbol]: { ...s.basis[symbol], symbol, ...data } as BasisRow },
    })),

  updateFunding: (symbol, data) =>
    set((s) => ({
      funding: { ...s.funding, [symbol]: { ...s.funding[symbol], symbol, ...data } as FundingRow },
    })),

  updatePosition: (symbol, data) =>
    set((s) => ({
      positions: { ...s.positions, [symbol]: { ...s.positions[symbol], symbol, ...data } as PositionRow },
    })),

  updateRisk: (data) =>
    set((s) => ({ risk: { ...s.risk, ...data } })),

  updateWorker: (symbol, data) =>
    set((s) => ({
      workers: { ...s.workers, [symbol]: { ...s.workers[symbol], symbol, ...data } as WorkerRow },
    })),

  addFill: (fill) =>
    set((s) => ({
      fills: [fill, ...s.fills].slice(0, MAX_FILLS),
    })),

  setBalance: (usdt) => set({ balance_usdt: usdt }),
  setEquity: (equity) => set({ equity }),
}));
