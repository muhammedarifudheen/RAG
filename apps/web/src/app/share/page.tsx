import type { Metadata } from "next";

import { SharedChatView } from "@/components/SharedChatView";

export const metadata: Metadata = { title: "Shared chat · Atlas" };

export default function SharePage() {
  return <SharedChatView />;
}
