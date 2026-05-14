"use client";

import { useTerminalStore } from "@/store/terminalStore";
import { fmtPct, fmtTs } from "@/components/ui/ValueCell";

export function FundingPanel() {
  const rows = Object.values(useTerminalStore((s) => s.funding)).sort(
    (a, b) => b.annualized_carry - a.annualized_carry,
  );

  if (rows.length === 0) {
    return <Empty label="No funding data — waiting for feed..." />;
  }

  return (
    <div className="flex-1 overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-900">
            <Th>SYMBOL</Th>
            <Th right>CURRENT 8H</Th>
            <Th right>PREDICTED</Th>
            <Th right>EWMA</Th>
            <Th right>ANN CARRY</Th>
            <Th right>Z-SCORE</Th>
            <Th>REGIME</Th>
            <Th right>EXTREME</Th>
            <Th right>STREAK</Th>
            <Th right>UPDATED</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} className="border-b border-zinc-800/50 tbl-row">
              <Td><span className="text-cyan-300 font-semibold">{r.symbol}</span></Td>
              <Td right>
                <span className={r.current_rate >= 0 ? "text-emerald-400" : "text-red-400"}>
                  {fmtPct(r.current_rate, 4)}
                </span>
              </Td>
              <Td right className="text-zinc-300">{fmtPct(r.predicted_rate, 4)}</Td>
              <Td right className="text-zinc-400">{fmtPct(r.ewma_rate, 4)}</Td>
              <Td right>
                <span className={r.annualized_carry >= 0.05 ? "text-emerald-400 font-semibold" : "text-zinc-300"}>
                  {fmtPct(r.annualized_carry)}
                </span>
              </Td>
              <Td right className="text-zinc-300">{r.z_score.toFixed(2)}</Td>
              <Td>
                <span className="text-zinc-400 capitalize">{r.regime.replace(/_/g, " ")}</span>
              </Td>
              <Td right>
                {r.is_extreme ? (
                  <span className="text-red-400 font-semibold">YES</span>
                ) : (
                  <span className="text-zinc-600">—</span>
                )}
              </Td>
              <Td right>
                <span className={r.extreme_streak >= 4 ? "text-amber-400" : "text-zinc-500"}>
                  {r.extreme_streak}
                </span>
              </Td>
              <Td right className="text-zinc-500">{fmtTs(r.ts_ms)}</Td>
            </tr>
          ))}
        </tbody>
      </table>
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

function Empty({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-32 text-zinc-600">{label}</div>
  );
}
