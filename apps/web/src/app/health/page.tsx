import type { Metadata } from "next";

import { HealthDashboard } from "@/components/HealthDashboard";
import { SourceHealthPanel } from "@/components/SourceHealthPanel";

export const metadata: Metadata = { title: "Health · Atlas" };

export default function HealthPage() {
  return (
    <>
      {/* The knowledge base's live health and its actions, then the code's health. */}
      <SourceHealthPanel />
      <HealthDashboard />
    </>
  );
}
