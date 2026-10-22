import { test, expect } from "@playwright/test";
import { mergeConversationHistory, type HistoryRow } from "../src/lib/conversation-history";
import type { Message } from "@langchain/langgraph-sdk";

const history: HistoryRow[] = [
  { source_message_id: "h1", role: "human", content: "重复", status: "completed" },
  { source_message_id: "a1", role: "assistant", content: "原回复", status: "completed" },
  { source_message_id: "h2", role: "human", content: "重复", status: "completed" },
  { source_message_id: "a2", role: "assistant", content: "旧分支", status: "completed" },
];

test("empty stream restores both identical questions from History", () => {
  expect(mergeConversationHistory(history, []).map((m) => m.id)).toEqual(["h1", "a1", "h2", "a2"]);
});

test("stream branch replaces the saved tail and preserves tool pairing", () => {
  const live: Message[] = [
    { type: "human", id: "h2", content: "重复" },
    { type: "ai", id: "call", content: "", tool_calls: [{ name: "events_list", args: {}, id: "tool" }] },
    { type: "tool", id: "result", content: "合成", tool_call_id: "tool" },
    { type: "ai", id: "a2", content: "新分支" },
  ];
  const merged = mergeConversationHistory(history, live);
  expect(merged.map((m) => m.id)).toEqual(["h1", "a1", "h2", "call", "result", "a2"]);
  expect(merged.at(-1)?.content).toBe("新分支");
});

test("a complete stream has no duplicate history bubbles", () => {
  const live = mergeConversationHistory(history, []);
  expect(mergeConversationHistory(history, live)).toEqual(live);
});
