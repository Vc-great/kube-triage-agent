export type AgentProgressEvent = {
  version: 1;
  type: "agent_progress";
  event_id: string;
  stage: "context" | "model" | "tool" | "answer";
  status: "started" | "completed" | "failed" | "fallback" | "cache_hit" | "skipped";
  label: string;
  thread_id: string;
  context_operation?: "trim" | "summary";
  tool_name?: "pods_list_in_namespace" | "pods_get" | "events_list" | "pods_log";
  tool_call_id?: string;
};

export const MAX_PROGRESS_EVENTS = 64;
const id = /^[A-Za-z0-9_-]{1,128}$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const labels: Record<string, string> = {
  "context:trim:completed": "历史上下文已安全裁剪",
  "context:trim:failed": "上下文预算不足，诊断未完成",
  "context:summary:started": "正在整理历史参考",
  "context:summary:completed": "历史参考已采纳",
  "context:summary:cache_hit": "沿用已校验的历史参考",
  "context:summary:fallback": "摘要失败，已回退到安全裁剪",
  "context:summary:skipped": "沿用安全裁剪，未重试失败的摘要",
  "model::started": "正在请求模型",
  "model::completed": "模型已返回",
  "model::failed": "模型请求或准备失败",
  "tool::started": "正在执行只读工具",
  "tool::completed": "只读工具已完成",
  "tool::failed": "只读工具执行失败",
  "tool::skipped": "只读工具调用已跳过",
  "answer::completed": "答复已生成",
};
const tools = new Set(["pods_list_in_namespace", "pods_get", "events_list", "pods_log"]);

export function isAgentProgressEvent(value: unknown): value is AgentProgressEvent {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const event = value as Record<string, unknown>;
  const keys = Object.keys(event);
  if (keys.some((key) => !["version", "type", "event_id", "stage", "status", "label", "thread_id", "context_operation", "tool_name", "tool_call_id"].includes(key))) return false;
  if (event.version !== 1 || event.type !== "agent_progress" ||
      typeof event.event_id !== "string" || !uuid.test(event.event_id) ||
      typeof event.stage !== "string" || typeof event.status !== "string") return false;
  const stage = event.stage as AgentProgressEvent["stage"];
  if (stage === "context") {
    if (event.context_operation !== "trim" && event.context_operation !== "summary") return false;
  } else if (event.context_operation !== undefined) return false;
  const expected = labels[`${stage}:${event.context_operation ?? ""}:${event.status}`];
  if (!expected || event.label !== expected) return false;
  if (typeof event.thread_id !== "string" || !id.test(event.thread_id)) return false;
  if (stage === "tool") {
    if (event.tool_name !== undefined && (typeof event.tool_name !== "string" || !tools.has(event.tool_name))) return false;
    if (event.tool_call_id !== undefined && (typeof event.tool_call_id !== "string" || !id.test(event.tool_call_id))) return false;
  } else if (event.tool_name !== undefined || event.tool_call_id !== undefined) return false;
  return true;
}

export function appendProgress(previous: AgentProgressEvent[], event: AgentProgressEvent,
                               threadId: string): AgentProgressEvent[] {
  if (event.thread_id !== threadId) return previous;
  if (previous.some((item) => item.event_id === event.event_id) ||
      previous.length >= MAX_PROGRESS_EVENTS) return previous;
  return [...previous, event];
}
