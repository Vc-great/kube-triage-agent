import assert from "node:assert/strict";
import { test } from "node:test";
import { appendProgress, isAgentProgressEvent, MAX_PROGRESS_EVENTS } from "./agent-progress.ts";

const event = {
  version: 1, type: "agent_progress", event_id: "3f568ba4-cbec-4f02-b44f-576576094a5f",
  stage: "tool", status: "started", label: "正在执行只读工具", tool_name: "pods_get",
  tool_call_id: "call_1", thread_id: "bab2e2cd-9752-49f1-8153-0c33c9bf1f3d",
};

test("accepts a bounded allowlisted tool event and rejects injected fields", () => {
  assert.equal(isAgentProgressEvent(event), true);
  assert.equal(isAgentProgressEvent({ ...event, label: "raw pod log" }), false);
  assert.equal(isAgentProgressEvent({ ...event, tool_name: "resources_scale" }), false);
  assert.equal(isAgentProgressEvent({ ...event, tool_call_id: "<script>" }), false);
  assert.equal(isAgentProgressEvent({ ...event, result: "secret" }), false);
  assert.equal(isAgentProgressEvent({ ...event, thread_id: undefined }), false);
});

test("replayed IDs are idempotent and event memory is bounded", () => {
  const first = appendProgress([], event, event.thread_id);
  assert.equal(appendProgress(first, event, event.thread_id), first);
  assert.equal(appendProgress(first, { ...event, event_id: "00000000-0000-0000-0000-000000000001" }, "other-thread"), first);
  const full = Array.from({ length: MAX_PROGRESS_EVENTS }, (_, index) => ({
    ...event, event_id: `00000000-0000-0000-0000-${String(index).padStart(12, "0")}`,
  }));
  assert.equal(appendProgress(full, event, event.thread_id), full);
});
