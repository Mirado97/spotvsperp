"use client";

interface TooltipProps {
  text: string;
  below?: boolean;
}

export function Tooltip({ text, below }: TooltipProps) {
  return (
    <span className="relative group inline-flex items-center ml-1 cursor-help">
      <span className="w-3.5 h-3.5 rounded-full border border-zinc-600 text-zinc-500 text-[9px] flex items-center justify-center group-hover:border-cyan-500 group-hover:text-cyan-400 transition-colors select-none">
        ?
      </span>
      <span className={[
        "absolute left-1/2 -translate-x-1/2 hidden group-hover:block z-50",
        "w-60 bg-zinc-800 border border-zinc-600 rounded px-3 py-2",
        "text-zinc-200 text-[11px] leading-relaxed whitespace-normal",
        "pointer-events-none shadow-xl",
        below ? "top-full mt-2" : "bottom-full mb-2",
      ].join(" ")}>
        {text}
        <span className={[
          "absolute left-1/2 -translate-x-1/2 border-4 border-transparent",
          below ? "bottom-full border-b-zinc-600" : "top-full border-t-zinc-600",
        ].join(" ")} />
      </span>
    </span>
  );
}

interface ColThProps {
  label: string;
  tip: string;
  right?: boolean;
}

export function ColTh({ label, tip, right }: ColThProps) {
  return (
    <th className={`px-3 py-2 text-zinc-500 font-medium whitespace-nowrap ${right ? "text-right" : "text-left"}`}>
      <span className="inline-flex items-center gap-0.5">
        {label}
        <Tooltip text={tip} below />
      </span>
    </th>
  );
}
