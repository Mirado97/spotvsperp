"use client";

import { Tooltip } from "@/components/ui/Tooltip";

const TABS = ["BASIS", "FUNDING", "POSITIONS", "RISK", "EXECUTION", "PnL", "LATENCY"] as const;
export type Tab = (typeof TABS)[number];

const TAB_TIPS: Record<Tab, string> = {
  BASIS:      "Анализ базиса — разница цен спот и фьючерс. Основной экран для поиска кэрри-возможностей",
  FUNDING:    "Ставки финансирования — плата за удержание бессрочных фьючерс-позиций. Ключевой источник дохода в кэрри-стратегии",
  POSITIONS:  "Открытые позиции по всем парам: размер, средняя цена, дельта-риск",
  RISK:       "Риск-менеджмент: просадка, суммарная экспозиция, лимиты и состояние алгоритмов",
  EXECUTION:  "История ордеров и сделок: заявки, исполнение, комиссии",
  PnL:        "Прибыль и убыток по стратегии: реализованный и нереализованный P&L",
  LATENCY:    "Задержки соединения: скорость получения данных с биржи и до браузера",
};

interface Props {
  active: Tab;
  onChange: (tab: Tab) => void;
}

export function Nav({ active, onChange }: Props) {
  return (
    <nav className="flex items-center gap-0 border-b border-zinc-800 bg-zinc-900 shrink-0 px-2">
      {TABS.map((tab) => (
        <button
          key={tab}
          onClick={() => onChange(tab)}
          className={[
            "flex items-center px-4 py-2 text-xs font-semibold tracking-wider transition-colors",
            "border-b-2 -mb-px",
            active === tab
              ? "border-cyan-400 text-cyan-400"
              : "border-transparent text-zinc-500 hover:text-zinc-300",
          ].join(" ")}
        >
          {tab}
          <Tooltip text={TAB_TIPS[tab]} below />
        </button>
      ))}
    </nav>
  );
}

export { TABS };
