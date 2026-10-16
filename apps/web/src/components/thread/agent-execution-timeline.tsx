import { type AgentProgressEvent } from "@/lib/agent-progress";

const stageName = { context: "上下文", model: "模型", tool: "只读工具", answer: "答复" };
const statusName = {
  started: "进行中", completed: "完成", failed: "失败", fallback: "已回退",
  cache_hit: "缓存命中", skipped: "已跳过",
};
const icon = { context: "◫", model: "◇", tool: "▣", answer: "✓" };

function compact(events: AgentProgressEvent[]): AgentProgressEvent[] {
  const rows: AgentProgressEvent[] = [];
  for (const event of events) {
    const previous = rows.findLastIndex((row) => row.status === "started" &&
      row.stage === event.stage && row.context_operation === event.context_operation &&
      row.tool_call_id === event.tool_call_id);
    if (event.status !== "started" && previous >= 0) rows[previous] = event;
    else rows.push(event);
  }
  return rows;
}

export function AgentExecutionTimeline({ events, running }: {
  events: AgentProgressEvent[];
  running: boolean;
}) {
  if (!events.length) return null;
  return <TimelineContent events={events} running={running} />;
}

function TimelineContent({ events, running }: {
  events: AgentProgressEvent[];
  running: boolean;
}) {
  const rows = compact(events);
  const current = running && events.at(-1)?.status === "started" ? events.at(-1) : undefined;
  return (
    <details className="rounded-lg border bg-slate-50 p-3 text-sm">
      <summary className="cursor-pointer font-medium" aria-label="Agent 执行过程">
        Agent 执行过程 · {rows.length} 项{current ? ` · ${current.label}` : ""}
      </summary>
      <ol className="mt-3 space-y-2" aria-live="polite">
        {rows.map((event) => (
          <li key={event.event_id} className="flex items-start gap-2 text-slate-700">
            <span aria-hidden="true">{icon[event.stage]}</span>
            <span className="min-w-0 flex-1">
              <span className="font-medium">{stageName[event.stage]}</span>
              {event.tool_name ? <span className="ml-1 font-mono text-xs">{event.tool_name}</span> : null}
              <span className="ml-2">{event.label}</span>
            </span>
            <span className="shrink-0 text-xs">{statusName[event.status]}</span>
          </li>
        ))}
      </ol>
      <p className="mt-3 text-xs text-slate-500">工具详情仍在 Tool Call 卡中；本次进度刷新后不保留。</p>
    </details>
  );
}
