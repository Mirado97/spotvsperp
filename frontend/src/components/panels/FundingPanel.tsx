"use client";

import { useTerminalStore } from "@/store/terminalStore";
import { fmtPct, fmtTs } from "@/components/ui/ValueCell";
import { ColTh } from "@/components/ui/Tooltip";

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
            <ColTh label="SYMBOL"      tip="Торговая пара (например BTCUSDT)" />
            <ColTh label="CURRENT 8H" tip="Текущая ставка финансирования за 8 часов. Положительная — лонги платят шортам" right />
            <ColTh label="PREDICTED"  tip="Прогнозируемая ставка следующего периода финансирования" right />
            <ColTh label="EWMA"       tip="Экспоненциально взвешенная средняя ставок финансирования — сглаженный тренд" right />
            <ColTh label="ANN CARRY"  tip="Аннуализированный доход от финансирования. >5% — интересная возможность" right />
            <ColTh label="Z-SCORE"    tip="Насколько текущая ставка отклоняется от исторической нормы (в стандартных отклонениях)" right />
            <ColTh label="REGIME"     tip="Режим рынка: backwardation / contango / neutral — направление ценового тренда на фьючерсах" />
            <ColTh label="EXTREME"    tip="Флаг аномально высокой или низкой ставки финансирования — возможный риск или возможность" right />
            <ColTh label="STREAK"     tip="Количество подряд идущих периодов с экстремальной ставкой финансирования" right />
            <ColTh label="UPDATED"    tip="Время последнего обновления данных" right />
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

function Td({ children, right, className = "" }: {
  children: React.ReactNode; right?: boolean; className?: string;
}) {
  return (
    <td className={`px-3 py-1.5 font-mono tabular-nums whitespace-nowrap ${right ? "text-right" : ""} ${className}`}>
      {children}
    </td>
  );
}

function Empty({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center h-32 text-zinc-600">{label}</div>
  );
}
