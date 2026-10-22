"use client";

import { useEffect, useState } from "react";
import { type Message } from "@langchain/langgraph-sdk";
import { type HistoryRow, mergeConversationHistory } from "@/lib/conversation-history";

type HistoryState = {
  threadId: string;
  rows: HistoryRow[];
  status: "synced" | "partial" | "legacy" | "error";
};

export function useConversationHistory({ apiUrl, apiKey, authScheme, threadId, isLoading, messages }: {
  apiUrl: string;
  apiKey: string | null;
  authScheme?: string;
  threadId: string | null;
  isLoading: boolean;
  messages: Message[];
}) {
  const enabled = process.env.NEXT_PUBLIC_APP_HISTORY_ENABLED === "true";
  const [history, setHistory] = useState<HistoryState | null>(null);

  useEffect(() => {
    if (!enabled || !threadId || isLoading) return;
    const controller = new AbortController();
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]);
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (apiKey) headers["X-Api-Key"] = apiKey;
    if (authScheme) headers["X-Auth-Scheme"] = authScheme;
    const base = apiUrl.replace(/\/$/, "");

    async function load() {
      try {
        // Aegra may mark the Run finished just after the SSE connection closes.
        let sync: Response | undefined;
        for (let attempt = 0; attempt < 6; attempt++) {
          sync = await fetch(`${base}/app/history/sync`, {
            method: "POST", headers, signal, body: JSON.stringify({ thread_id: threadId }),
          });
          if (sync.status !== 409) break;
          await new Promise((resolve) => setTimeout(resolve, 250));
        }
        if (!sync?.ok) throw new Error("history sync unavailable");
        const rows: HistoryRow[] = [];
        let cursor: number | null = 0;
        let checkpoint: string | undefined;
        let status = "legacy";
        while (cursor !== null) {
          const query = new URLSearchParams({ limit: "200", cursor: String(cursor) });
          if (checkpoint) query.set("checkpoint", checkpoint);
          const response = await fetch(
            `${base}/app/history/threads/${encodeURIComponent(threadId!)}/messages?${query}`,
            { headers, signal, cache: "no-store" },
          );
          if (!response.ok) throw new Error("history read unavailable");
          const page = await response.json();
          rows.push(...page.messages);
          cursor = page.next_cursor;
          checkpoint = page.checkpoint_id;
          status = page.status;
        }
        if (!signal.aborted) setHistory({ threadId: threadId!, rows,
          status: status === "legacy" ? "legacy" : status === "completed" ? "synced" : "partial" });
      } catch {
        if (!controller.signal.aborted) setHistory({ threadId: threadId!, rows: [], status: "error" });
      }
    }
    void load();
    return () => controller.abort();
  }, [enabled, apiUrl, apiKey, authScheme, threadId, isLoading]);

  const current = enabled && history?.threadId === threadId ? history : null;
  const historyStatus: HistoryState["status"] | "syncing" | null =
    !enabled ? null : current?.status ?? (threadId ? "syncing" : null);
  return {
    displayMessages: current && current.status !== "error"
      ? mergeConversationHistory(current.rows, messages) : messages,
    historyStatus,
  };
}
