"use client";

import { useTerminalStore } from "@/store/terminalStore";
import { ValueCell, fmtNum, fmtUsd } from "@/components/ui/ValueCell";

export function PositionsPanel() {
  const { positions, basis } = useTerminalStore();
  const rows = Object.values(positions).filter(
    (p) => p.spot_qty !== 0 || p.perp_qty !== 0,
  );

  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-zinc-600">
        No open positions
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-zinc-800 bg-zinc-900">
            <Th>SYMBOL</Th>
            <Th right>SPOT QTY</Th>
            <Th right>PERP QTY</Th>
            <Th right>SPOT AVG</Th>
            <Th right>PERP AVG</Th>
            <Th right>MARK</Th>
            <Th right>NET DELTA USD</Th>
            <Th right>UNREAL PnL</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => {
            const mark = basis[p.symbol]?.perp_mid ?? p.perp_avg_price;
            const spotPnl = p.spot_qty * (mark - p.spot_avg_price);
            const perpPnl = -p.perp_qty * (mark - p.perp_avg_price);
            const unrealPnl = spotPnl + perpPnl;
            return (
              <tr key={p.symbol} className="border-b border-zinc-800/50 tbl-row">
                <Td><span className="text-cyan-300 font-semibold">{p.symbol}</span></Td>
                <Td right className="text-emerald-400">{fmtNum(p.spot_qty, 4)}</Td>
                <Td right className="text-red-400">{fmtNum(p.perp_qty, 4)}</Td>
                <Td right>{fmtNum(p.spot_avg_price, 2)}</Td>
                <Td right>{fmtNum(p.perp_avg_price, 2)}</Td>
                <Td right className="text-zinc-300">{fmtNum(mark, 2)}</Td>
                <Td right>
                  <ValueCell value={p.net_delta_usd} decimals={2} />
                </Td>
                <Td right>
                  <ValueCell value={unrealPnl} decimals={2} suffix=" USDT" />
                </Td>
              </tr>
            );
          })}
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
