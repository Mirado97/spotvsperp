"use client";

import { useTerminalStore } from "@/store/terminalStore";

function latencyColor(ms: number): string {
  if (ms === 0) return "text-zinc-500";
  if (ms < 50)  return "text-emerald-400";
  if (ms < 150) return "text-yellow-400";
  return "text-red-400";
}

function LatencyRow({ label, ms, description }: { label: string; ms: number; description: string }) {
  const color = latencyColor(ms);
  return (
    <div className="flex items-start justify-between py-4 border-b border-zinc-800">
      <div>
        <div className="text-sm font-semibold text-zinc-200">{label}</div>
        <div className="text-xs text-zinc-500 mt-0.5">{description}</div>
      </div>
      <div className={`text-2xl font-mono font-bold tabular-nums ${color}`}>
        {ms === 0 ? "—" : `${ms} ms`}
      </div>
    </div>
  );
}

export function LatencyPanel() {
  const { latency } = useTerminalStore();
  const { rest_rtt_ms, server_to_browser_ms, updated_at } = latency;

  const total = rest_rtt_ms > 0 && server_to_browser_ms > 0
    ? rest_rtt_ms + server_to_browser_ms
    : 0;

  const age = updated_at > 0
    ? `Обновлено ${((Date.now() - updated_at) / 1000).toFixed(0)}с назад`
    : "Ожидание данных…";

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="max-w-xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-sm font-semibold tracking-widest text-zinc-400 uppercase">
            Latency Monitor
          </h2>
          <span className="text-xs text-zinc-600">{age}</span>
        </div>

        <div className="bg-zinc-900 rounded-lg border border-zinc-800 px-6">
          <LatencyRow
            label="Server → Browser"
            ms={server_to_browser_ms}
            description="Время от публикации на сервере до получения в браузере (WS + сеть)"
          />
          <LatencyRow
            label="REST API RTT"
            ms={rest_rtt_ms}
            description="Round-trip до api-demo.bybit.com (запрос перп-тикера каждые 2с)"
          />
          <LatencyRow
            label="Total Pipeline"
            ms={total}
            description="REST RTT + Server→Browser: полный путь данных"
          />
        </div>

        <div className="mt-4 flex gap-4 text-xs text-zinc-600">
          <span className="text-emerald-400">● &lt;50ms отлично</span>
          <span className="text-yellow-400">● &lt;150ms норма</span>
          <span className="text-red-400">● &gt;150ms высокая</span>
        </div>
      </div>
    </div>
  );
}
