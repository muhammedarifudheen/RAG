import type { Metadata } from "next";

import { FileGraphView } from "@/components/FileGraphView";

export const metadata: Metadata = { title: "Graph · Atlas" };

export default function GraphPage() {
  return <FileGraphView />;
}
