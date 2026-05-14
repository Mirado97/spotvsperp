"use client";

import { useTerminalStore } from "@/store/terminalStore";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { fmtUsd } from "@/components/ui/ValueCell";

export function StatusBar() {
  const { connected, exchange, equity, balance_usdt, risk } = useTerminalStore();

  return (
    <header className="flex items-center justify-between px-4 h-9 bg-zinc-900 border-b border-zinc-800 text-xs shrink-0">
      {/* Left: branding */}
      <div className="flex items-center gap-3">
        <span className="text-cyan-400 font-semibold tracking-widest">CEXvsCEX</span>
        <span className="text-zinc-500">|</span>
        <span className="text-zinc-400">{exchange} TESTNET</span>
      </div>

      {/* Centre: key stats */}
      <div className="flex items-center gap-6 text-zinc-300">
        <Stat label="EQUITY"  value={fmtUsd(equity)} />
        <Stat label="BALANCE" value={`${fmtUsd(balance_usdt)} USDT`} />
        <Stat label="DRAWDOWN" value={(risk.drawdown_pct * 100).toFixed(2) + "%"}
              className={risk.drawdown_pct > 0.03 ? "text-red-400" : "text-zinc-300"} />
        <RiskBadge level={risk.level} />
      </div>

      {/* Right: connection status */}
      <div className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${connected ? "bg-emerald-400" : "bg-red-500"}`} />
        <span className={connected ? "text-emerald-400" : "text-red-400"}>
          {connected ? "CONNECTED" : "DISCONNECTED"}
        </span>
      </div>
    </header>
  );
}

function Stat({ label, value, className = "text-zinc-300" }: {
  label: string; value: string; className?: string;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-zinc-500">{label}</span>
      <span className={className}>{value}</span>
    </span>
  );
}
