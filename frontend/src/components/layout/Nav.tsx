"use client";

const TABS = ["BASIS", "FUNDING", "POSITIONS", "RISK", "EXECUTION", "PnL"] as const;
export type Tab = (typeof TABS)[number];

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
            "px-4 py-2 text-xs font-semibold tracking-wider transition-colors",
            "border-b-2 -mb-px",
            active === tab
              ? "border-cyan-400 text-cyan-400"
              : "border-transparent text-zinc-500 hover:text-zinc-300",
          ].join(" ")}
        >
          {tab}
        </button>
      ))}
    </nav>
  );
}

export { TABS };
