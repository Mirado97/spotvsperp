"use client";

import { useTerminalStore } from "@/store/terminalStore";
import { ValueCell, fmtNum, fmtPct, fmtTs } from "@/components/ui/ValueCell";
import { ColTh } from "@/components/ui/Tooltip";

export function BasisPanel() {
  const rows = Object.values(useTerminalStore((s) => s.basis)).sort(
    (a, b) => {
      const sa = (b.funding_yield_ann ?? 0) + (b.annualized_basis ?? 0);
      const sb = (a.funding_yield_ann ?? 0) + (a.annualized_basis ?? 0);
      return sa - sb;
    },
  );

  if (rows.length === 0) {
    return <Empty label="No basis data — waiting for feed..." />;
  }

  return (
    <div className="flex-1 overflow-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <Tr header>
            <ColTh label="SYMBOL"       tip="Торговая пара (например BTCUSDT)" />
            <ColTh label="SPOT"         tip="Средняя цена на спот-рынке (bid+ask)/2" right />
            <ColTh label="PERP"         tip="Средняя цена бессрочного фьючерса (bid+ask)/2" right />
            <ColTh label="PREMIUM"      tip="Разница в долларах: фьючерс − спот. Положительная = фьючерс дороже спота" right />
            <ColTh label="BASIS BPS"    tip="Базис в базисных пунктах. 1 BPS = 0.01%. Положительный = фьючерс дороже спота" right />
            <ColTh label="ANN BASIS"    tip="Аннуализированный базис — какую доходность даёт текущий спред за год, если удерживать позицию" right />
            <ColTh label="FUNDING 8H"   tip="Текущая ставка финансирования за 8 часов. Положительная = лонги платят шортам (доход для кэрри)" right />
            <ColTh label="CARRY SCORE"  tip="Привлекательность кэрри-трейда = ставка финансирования + аннуализированный базис. Чем выше — тем интереснее открыть позицию" right />
            <ColTh label="UPDATED"      tip="Время последнего обновления данных с биржи" right />
          </Tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const carryScore = (r.funding_yield_ann ?? 0) + (r.annualized_basis ?? 0);
            return (
              <Tr key={r.symbol}>
                <Td><span className="text-cyan-300 font-semibold">{r.symbol}</span></Td>
                <Td right>{fmtNum(r.spot_mid, 1)}</Td>
                <Td right>{fmtNum(r.perp_mid, 1)}</Td>
                <Td right><ValueCell value={r.perp_premium} decimals={2} /></Td>
                <Td right><ValueCell value={r.basis_bps} decimals={2} /></Td>
                <Td right><ValueCell value={r.annualized_basis * 100} decimals={2} suffix="%" /></Td>
                <Td right><ValueCell value={r.funding_rate * 100} decimals={4} suffix="%" /></Td>
                <Td right>
                  <span className={carryScore >= 0.05 ? "text-emerald-400 font-semibold" : "text-zinc-300"}>
                    {fmtPct(carryScore)}
                  </span>
                </Td>
                <Td right className="text-zinc-500">{fmtTs(r.ts_ms)}</Td>
              </Tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Tr({ children, header }: { children: React.ReactNode; header?: boolean }) {
  return (
    <tr className={header ? "border-b border-zinc-800 bg-zinc-900" : "border-b border-zinc-800/50 tbl-row"}>
      {children}
    </tr>
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
  return <div className="flex items-center justify-center h-32 text-zinc-600">{label}</div>;
}
