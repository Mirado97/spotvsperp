"use client";

import { useTerminalStore } from "@/store/terminalStore";
import { ValueCell, fmtNum, fmtPct, fmtUsd, fmtTs } from "@/components/ui/ValueCell";

export function BasisPanel() {
  const rows = Object.values(useTerminalStore((s) => s.basis)).sort(
    (a, b) => b.carry_score - a.carry_score,
  );

  if (rows.length === 0) {
    return <Empty label="No basis data — waiting for feed..." />;
  }

  return (
    <div className="flex-1 overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <Tr header>
            <Th>SYMBOL</Th>
            <Th right>SPOT</Th>
            <Th right>PERP</Th>
            <Th right>PREMIUM</Th>
            <Th right>BASIS BPS</Th>
            <Th right>ANN BASIS</Th>
            <Th right>FUNDING 8H</Th>
            <Th right>CARRY SCORE</Th>
            <Th right>UPDATED</Th>
          </Tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <Tr key={r.symbol}>
              <Td><span className="text-cyan-300 font-semibold">{r.symbol}</span></Td>
              <Td right>{fmtNum(r.spot_mid, 1)}</Td>
              <Td right>{fmtNum(r.perp_mid, 1)}</Td>
              <Td right>
                <ValueCell value={r.perp_premium} decimals={2} />
              </Td>
              <Td right>
                <ValueCell value={r.basis_bps} decimals={2} />
              </Td>
              <Td right>
                <ValueCell value={r.annualized_basis * 100} decimals={2} suffix="%" />
              </Td>
              <Td right>
                <ValueCell value={r.funding_rate * 100} decimals={4} suffix="%" />
              </Td>
              <Td right>
                <span className={r.carry_score >= 0.05 ? "text-emerald-400 font-semibold" : "text-zinc-300"}>
                  {fmtPct(r.carry_score)}
                </span>
              </Td>
              <Td right className="text-zinc-500">{fmtTs(r.ts_ms)}</Td>
            </Tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Table primitives ──────────────────────────────────────────────────────────

function Tr({ children, header }: { children: React.ReactNode; header?: boolean }) {
  const cls = header
    ? "border-b border-zinc-800 bg-zinc-900"
    : "border-b border-zinc-800/50 tbl-row";
  return <tr className={cls}>{children}</tr>;
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
    <div className="flex items-center justify-center h-32 text-zinc-600">
      {label}
    </div>
  );
}
