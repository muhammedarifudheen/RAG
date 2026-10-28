import type { Metadata } from "next";

import { RepoAnalyzer } from "@/components/RepoAnalyzer";

export const metadata: Metadata = { title: "Analyse · Atlas" };

export default function AnalyzePage() {
  return <RepoAnalyzer />;
}
