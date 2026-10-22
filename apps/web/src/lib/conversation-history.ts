import type { Message } from "@langchain/langgraph-sdk";

export type HistoryRow = {
  source_message_id: string;
  role: "human" | "assistant";
  content: Message["content"];
  status: string;
};

// The stream owns the current branch and tool pairing. History fills an older
// prefix (or an empty stream); never append a stale regenerated branch tail.
export function mergeConversationHistory(history: HistoryRow[], live: Message[]): Message[] {
  const saved: Message[] = history.map((row) => ({
    id: row.source_message_id,
    type: row.role === "human" ? "human" : "ai",
    content: row.content,
  }));
  if (!live.length) return saved;
  const liveIds = new Set(live.map((message) => message.id).filter(Boolean));
  const anchor = saved.findIndex((message) => liveIds.has(message.id));
  const prefix = anchor < 0 ? saved : saved.slice(0, anchor);
  return [...prefix.filter((message) => !liveIds.has(message.id)), ...live];
}
