import { RISK_LEVEL_LABELS } from "@/types";

const COLORS: Record<number, string> = {
  0: "bg-emerald-900 text-emerald-300 border-emerald-700",
  1: "bg-amber-900 text-amber-300 border-amber-700",
  2: "bg-orange-900 text-orange-300 border-orange-700",
  3: "bg-red-900 text-red-300 border-red-700 animate-pulse",
};

export function RiskBadge({ level }: { level: number }) {
  const cls = COLORS[level] ?? COLORS[0];
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-semibold ${cls}`}>
      {RISK_LEVEL_LABELS[level] ?? "UNKNOWN"}
    </span>
  );
}
