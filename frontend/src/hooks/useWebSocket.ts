"use client";

import { useEffect, useRef } from "react";
import { useTerminalStore, type TerminalStore } from "@/store/terminalStore";
import type { WsMessage, BasisRow, FundingRow, FillRow, WorkerRow } from "@/types";

const RECONNECT_MS = 3_000;

export function useWebSocket(url: string) {
  const store = useTerminalStore();
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let alive = true;

    function connect() {
      if (!alive) return;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => store.setConnected(true);

      ws.onclose = () => {
        store.setConnected(false);
        if (alive) timerRef.current = setTimeout(connect, RECONNECT_MS);
      };

      ws.onerror = () => ws.close();

      ws.onmessage = (e: MessageEvent<string>) => {
        try {
          const msg = JSON.parse(e.data) as WsMessage;
          dispatch(msg, store);
        } catch {
          // ignore malformed messages
        }
      };
    }

    connect();

    return () => {
      alive = false;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [url]); // eslint-disable-line react-hooks/exhaustive-deps
}

function dispatch(msg: WsMessage, store: TerminalStore) {
  const d = msg.data;

  switch (msg.type) {
    case "basis":
      if (msg.symbol) store.updateBasis(msg.symbol, d as Partial<BasisRow>);
      break;

    case "funding":
      if (msg.symbol) store.updateFunding(msg.symbol, d as Partial<FundingRow>);
      break;

    case "risk_alert":
      store.updateRisk({ level: (d.level as number) ?? 0 });
      break;

    case "risk_snapshot":
      store.updateRisk({
        drawdown_pct: d.drawdown_pct as number,
        total_exposure_usd: d.total_exposure_usd as number,
        max_delta_usd: d.max_symbol_delta_usd as number,
      });
      break;

    case "fill":
      if (msg.symbol) store.addFill({ symbol: msg.symbol, ...d } as FillRow);
      break;

    case "workers": {
      const workers = (Array.isArray(d) ? d : []) as Partial<WorkerRow>[];
      for (const w of workers) {
        if (w.symbol) store.updateWorker(w.symbol, w);
      }
      break;
    }

    case "balance":
      if (d.currency === "USDT") store.setBalance(d.available as number);
      break;

    case "equity":
      store.setEquity(d.total_equity as number);
      break;
  }
}
