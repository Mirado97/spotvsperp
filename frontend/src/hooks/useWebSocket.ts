"use client";

import { useEffect, useRef } from "react";
import { useTerminalStore, type TerminalStore } from "@/store/terminalStore";
import type { WsMessage } from "@/types";

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
  switch (msg.type) {
    case "basis":
      if (msg.symbol) store.updateBasis(msg.symbol, msg.data as never);
      break;

    case "funding":
      if (msg.symbol) store.updateFunding(msg.symbol, msg.data as never);
      break;

    case "risk_alert":
      store.updateRisk({ level: (msg.data as { level: number }).level });
      break;

    case "risk_snapshot": {
      const d = msg.data as {
        drawdown_pct: number;
        total_exposure_usd: number;
        max_symbol_delta_usd: number;
      };
      store.updateRisk({
        drawdown_pct: d.drawdown_pct,
        total_exposure_usd: d.total_exposure_usd,
        max_delta_usd: d.max_symbol_delta_usd,
      });
      break;
    }

    case "fill":
      if (msg.symbol) store.addFill({ symbol: msg.symbol, ...(msg.data as never) });
      break;

    case "workers": {
      const workers = msg.data as { symbol: string }[];
      for (const w of workers) store.updateWorker(w.symbol, w as never);
      break;
    }

    case "balance": {
      const d = msg.data as { currency: string; available: number };
      if (d.currency === "USDT") store.setBalance(d.available);
      break;
    }

    case "equity": {
      const d = msg.data as { total_equity: number };
      store.setEquity(d.total_equity);
      break;
    }
  }
}
