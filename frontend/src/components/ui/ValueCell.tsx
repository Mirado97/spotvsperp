interface Props {
  value: number;
  decimals?: number;
  suffix?: string;
  invert?: boolean; // treat positive as bad (e.g. drawdown)
}

export function ValueCell({ value, decimals = 2, suffix = "", invert = false }: Props) {
  const positive = invert ? value < 0 : value > 0;
  const negative = invert ? value > 0 : value < 0;
  const cls = positive ? "text-emerald-400" : negative ? "text-red-400" : "text-zinc-300";
  const formatted = value.toFixed(decimals) + suffix;
  return <span className={cls}>{formatted}</span>;
}

export function fmtNum(v: number, d = 2): string {
  return v.toFixed(d);
}

export function fmtPct(v: number, d = 4): string {
  return (v * 100).toFixed(d) + "%";
}

export function fmtUsd(v: number): string {
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

export function fmtTs(ts_ms: number): string {
  return new Date(ts_ms).toISOString().slice(11, 19);
}
