"use client";

import { useTerminalStore } from "@/store/terminalStore";
import { ValueCell, fmtNum } from "@/components/ui/ValueCell";
import { ColTh } from "@/components/ui/Tooltip";

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
            <ColTh label="SYMBOL"       tip="Торговая пара" />
            <ColTh label="SPOT QTY"     tip="Количество базового актива на споте. Положительное = длинная позиция" right />
            <ColTh label="PERP QTY"     tip="Количество базового актива на бессрочном фьючерсе. Положительное = лонг" right />
            <ColTh label="SPOT AVG"     tip="Средняя цена входа в спот-позицию" right />
            <ColTh label="PERP AVG"     tip="Средняя цена входа во фьючерсную позицию" right />
            <ColTh label="MARK"         tip="Текущая рыночная цена фьючерса (mid-price)" right />
            <ColTh label="NET DELTA USD" tip="Суммарный долларовый риск направления: спот + фьючерс. В кэрри-стратегии близко к нулю" right />
            <ColTh label="UNREAL PnL"   tip="Нереализованная прибыль/убыток по открытым позициям в USDT" right />
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

function Td({ children, right, className = "" }: {
  children: React.ReactNode; right?: boolean; className?: string;
}) {
  return (
    <td className={`px-3 py-1.5 font-mono tabular-nums whitespace-nowrap ${right ? "text-right" : ""} ${className}`}>
      {children}
    </td>
  );
}
