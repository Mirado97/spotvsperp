"use client";

import { useTerminalStore } from "@/store/terminalStore";
import { fmtNum, fmtTs } from "@/components/ui/ValueCell";

// OrderSide: BUY=1, SELL=2 (from src/models/orders.py)
const SIDE_LABELS: Record<number, string> = { 1: "BUY", 2: "SELL" };
const SIDE_COLORS: Record<number, string> = {
  1: "text-emerald-400",
  2: "text-red-400",
};
// InstrumentType: SPOT=1, PERPETUAL=2
const INST_LABELS: Record<number, string> = { 1: "SPOT", 2: "PERP" };

export function ExecutionPanel() {
  const fills = useTerminalStore((s) => s.fills);

  if (fills.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-zinc-600">
        No fills yet — execution log empty
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-900">
            <Th>TIME</Th>
            <Th>SYMBOL</Th>
            <Th>INST</Th>
            <Th>SIDE</Th>
            <Th right>QTY</Th>
            <Th right>PRICE</Th>
            <Th right>VALUE</Th>
            <Th right>FEE</Th>
          </tr>
        </thead>
        <tbody>
          {fills.map((f, i) => (
            <tr key={i} className="border-b border-zinc-800/50 tbl-row">
              <Td className="text-zinc-500">{fmtTs(f.ts_ms)}</Td>
              <Td><span className="text-cyan-300">{f.symbol}</span></Td>
              <Td className="text-zinc-400">{INST_LABELS[f.instrument_type] ?? "?"}</Td>
              <Td>
                <span className={SIDE_COLORS[f.side] ?? "text-zinc-300"}>
                  {SIDE_LABELS[f.side] ?? f.side}
                </span>
              </Td>
              <Td right>{fmtNum(f.qty, 4)}</Td>
              <Td right>{fmtNum(f.price, 2)}</Td>
              <Td right className="text-zinc-300">{fmtNum(f.qty * f.price, 2)}</Td>
              <Td right className="text-zinc-500">{fmtNum(f.fee, 4)} {f.fee_currency}</Td>
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
