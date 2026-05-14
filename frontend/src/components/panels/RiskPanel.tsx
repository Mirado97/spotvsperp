"use client";

import { useTerminalStore } from "@/store/terminalStore";
import { RiskBadge } from "@/components/ui/RiskBadge";
import { fmtUsd, fmtNum } from "@/components/ui/ValueCell";
import { WORKER_STATE_LABELS } from "@/types";

const STATE_COLORS: Record<number, string> = {
  0: "text-zinc-500",
  1: "text-cyan-400",
  2: "text-amber-400",
  3: "text-emerald-400",
  4: "text-amber-400",
  5: "text-zinc-600",
  6: "text-red-500",
};

export function RiskPanel() {
  const { risk, workers } = useTerminalStore();
  const workerRows = Object.values(workers).sort((a, b) =>
    a.symbol.localeCompare(b.symbol),
  );

  return (
    <div className="flex-1 overflow-auto p-4 space-y-6">

      {/* Risk summary cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card label="RISK LEVEL">
          <RiskBadge level={risk.level} />
        </Card>
        <Card label="DRAWDOWN">
          <span className={risk.drawdown_pct > 0.03 ? "text-red-400" : "text-zinc-200"}>
            {(risk.drawdown_pct * 100).toFixed(2)}%
          </span>
        </Card>
        <Card label="TOTAL EXPOSURE">
          <span className="text-zinc-200">{fmtUsd(risk.total_exposure_usd)}</span>
        </Card>
        <Card label="MAX DELTA">
          <span className={risk.max_delta_usd > 3_000 ? "text-amber-400" : "text-zinc-200"}>
            {fmtUsd(risk.max_delta_usd)}
          </span>
        </Card>
      </div>

      {/* Workers table */}
      <section>
        <h2 className="text-zinc-500 text-xs font-semibold mb-2 tracking-wider">WORKER STATES</h2>
        {workerRows.length === 0 ? (
          <p className="text-zinc-600 text-xs">No workers registered</p>
        ) : (
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-zinc-800 bg-zinc-900">
                <Th>SYMBOL</Th>
                <Th>STATE</Th>
                <Th right>PERIODS HELD</Th>
                <Th right>TOTAL TRADES</Th>
                <Th right>RESTARTS</Th>
              </tr>
            </thead>
            <tbody>
              {workerRows.map((w) => (
                <tr key={w.symbol} className="border-b border-zinc-800/50 tbl-row">
                  <Td><span className="text-cyan-300">{w.symbol}</span></Td>
                  <Td>
                    <span className={`font-semibold ${STATE_COLORS[w.state] ?? "text-zinc-300"}`}>
                      {WORKER_STATE_LABELS[w.state] ?? w.state}
                    </span>
                  </Td>
                  <Td right className="text-zinc-300">{w.periods_held}</Td>
                  <Td right className="text-zinc-300">{w.total_trades}</Td>
                  <Td right>
                    <span className={w.restart_count > 0 ? "text-amber-400" : "text-zinc-600"}>
                      {w.restart_count}
                    </span>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function Card({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded p-3 space-y-1">
      <div className="text-zinc-500 text-xs tracking-wider">{label}</div>
      <div className="text-sm font-semibold">{children}</div>
    </div>
  );
}

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return (
    <th className={`px-3 py-2 text-zinc-500 font-medium ${right ? "text-right" : "text-left"}`}>
      {children}
    </th>
  );
}

function Td({ children, right, className = "" }: {
  children: React.ReactNode; right?: boolean; className?: string;
}) {
  return (
    <td className={`px-3 py-1.5 ${right ? "text-right" : ""} ${className}`}>
      {children}
    </td>
  );
}
