import { test, expect } from "@playwright/test";
import { mergeConversationHistory, type HistoryRow } from "../src/lib/conversation-history";
import type { Message } from "@langchain/langgraph-sdk";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { buildSync } from "esbuild";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";

// Playwright's TSX transform targets component tests. Compile the real UI for
// React SSR instead, using the project's existing bundler and dependencies.
const compiled = buildSync({
  entryPoints: [resolve("src/components/thread/messages/shared.tsx")],
  bundle: true, write: false, platform: "node", format: "cjs", jsx: "automatic",
  packages: "external", alias: { "@": resolve("src") },
}).outputFiles[0].text;
const ui = { exports: {} as typeof import("../src/components/thread/messages/shared") };
runInNewContext(compiled, { require: createRequire(import.meta.url), module: ui, exports: ui.exports });
const { CommandBar } = ui.exports;

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

test("history-only Assistant keeps copy without an executable regenerate action", () => {
  const saved = renderToStaticMarkup(createElement(CommandBar, {
    content: "已保存回复", isAiMessage: true, isLoading: false,
  }));
  expect(saved).toContain("Copy content");
  expect(saved).not.toContain("Refresh");
  const live = renderToStaticMarkup(createElement(CommandBar, {
    content: "SDK回复", isAiMessage: true, isLoading: false, handleRegenerate: () => {},
  }));
  expect(live).toContain("Refresh");
});

test("history-only Human keeps copy without editing a different execution state", () => {
  const saved = renderToStaticMarkup(createElement(CommandBar, {
    content: "已保存问题", isHumanMessage: true, isLoading: false,
    isEditing: false, setIsEditing: () => {}, handleSubmitEdit: () => {}, disableEdit: true,
  }));
  expect(saved).toContain("Copy content");
  expect(saved).not.toContain(">Edit<");
});
