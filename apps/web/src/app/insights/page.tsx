import type { Metadata } from "next";

import { InsightsDashboard } from "@/components/InsightsDashboard";

export const metadata: Metadata = { title: "Insights · Atlas" };

export default function InsightsPage() {
  return <InsightsDashboard />;
}
