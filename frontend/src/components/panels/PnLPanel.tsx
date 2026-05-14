"use client";

import { useTerminalStore } from "@/store/terminalStore";
import { fmtUsd } from "@/components/ui/ValueCell";
import { ValueCell } from "@/components/ui/ValueCell";

export function PnLPanel() {
  const { equity, balance_usdt, risk, fills } = useTerminalStore();

  const realizedPnl = fills.reduce(
    (acc, f) => acc + (f.side === 2 ? f.qty * f.price - f.fee : -(f.qty * f.price + f.fee)),
    0,
  );
  const totalFees = fills.reduce((acc, f) => acc + f.fee, 0);

  return (
    <div className="flex-1 overflow-auto p-4 space-y-6">

      {/* Summary row */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card label="TOTAL EQUITY">
          <span className="text-zinc-200 text-base">{fmtUsd(equity)}</span>
        </Card>
        <Card label="AVAILABLE USDT">
          <span className="text-zinc-200 text-base">{fmtUsd(balance_usdt)}</span>
        </Card>
        <Card label="DRAWDOWN">
          <span className={`text-base font-semibold ${risk.drawdown_pct > 0.03 ? "text-red-400" : "text-zinc-200"}`}>
            {(risk.drawdown_pct * 100).toFixed(2)}%
          </span>
        </Card>
        <Card label="TOTAL FEES (SESSION)">
          <span className="text-amber-400 text-base">{fmtUsd(totalFees)}</span>
        </Card>
      </div>

      {/* Fill-derived PnL */}
      <section>
        <h2 className="text-zinc-500 text-xs font-semibold mb-3 tracking-wider">SESSION FILL SUMMARY</h2>
        <div className="grid grid-cols-3 gap-3">
          <Card label="FILLS">
            <span className="text-zinc-200">{fills.length}</span>
          </Card>
          <Card label="TOTAL VOLUME">
            <span className="text-zinc-200">
              {fmtUsd(fills.reduce((a, f) => a + f.qty * f.price, 0))}
            </span>
          </Card>
          <Card label="REALIZED PnL (EST)">
            <ValueCell value={realizedPnl} decimals={2} suffix=" USDT" />
          </Card>
        </div>
      </section>

      {/* Risk context */}
      <section>
        <h2 className="text-zinc-500 text-xs font-semibold mb-3 tracking-wider">RISK CONTEXT</h2>
        <div className="grid grid-cols-2 gap-3">
          <Card label="TOTAL EXPOSURE">
            <span className="text-zinc-200">{fmtUsd(risk.total_exposure_usd)}</span>
          </Card>
          <Card label="MAX DELTA">
            <span className={risk.max_delta_usd > 3_000 ? "text-amber-400" : "text-zinc-200"}>
              {fmtUsd(risk.max_delta_usd)}
            </span>
          </Card>
        </div>
      </section>
    </div>
  );
}

function Card({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded p-3 space-y-1">
      <div className="text-zinc-500 text-xs tracking-wider">{label}</div>
      <div className="font-semibold">{children}</div>
    </div>
  );
}
