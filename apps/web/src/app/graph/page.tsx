import type { Metadata } from "next";

import { GraphTabs } from "@/components/GraphTabs";

export const metadata: Metadata = { title: "Graph · Atlas" };

export default function GraphPage() {
  return <GraphTabs />;
}
