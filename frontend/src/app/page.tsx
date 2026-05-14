"use client";

import { useState } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { StatusBar } from "@/components/layout/StatusBar";
import { Nav, type Tab } from "@/components/layout/Nav";
import { BasisPanel } from "@/components/panels/BasisPanel";
import { FundingPanel } from "@/components/panels/FundingPanel";
import { PositionsPanel } from "@/components/panels/PositionsPanel";
import { RiskPanel } from "@/components/panels/RiskPanel";
import { ExecutionPanel } from "@/components/panels/ExecutionPanel";
import { PnLPanel } from "@/components/panels/PnLPanel";

const WS_URL =
  typeof window !== "undefined"
    ? `ws://${window.location.host}/ws`
    : "ws://localhost:8080/ws";

export default function Terminal() {
  const [tab, setTab] = useState<Tab>("BASIS");
  useWebSocket(WS_URL);

  return (
    <div className="flex flex-col h-screen">
      <StatusBar />
      <Nav active={tab} onChange={setTab} />
      <main className="flex-1 overflow-hidden flex flex-col min-h-0">
        {tab === "BASIS"     && <BasisPanel />}
        {tab === "FUNDING"   && <FundingPanel />}
        {tab === "POSITIONS" && <PositionsPanel />}
        {tab === "RISK"      && <RiskPanel />}
        {tab === "EXECUTION" && <ExecutionPanel />}
        {tab === "PnL"       && <PnLPanel />}
      </main>
    </div>
  );
}
