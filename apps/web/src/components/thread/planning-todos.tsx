import { useQueryState } from "nuqs";
import { useStreamContext, type PlanningTodo } from "@/providers/Stream";

const LABELS: Record<PlanningTodo["status"], string> = {
  pending: "待处理",
  in_progress: "进行中",
  completed: "已完成",
};

function isPlanningTodo(value: unknown): value is PlanningTodo {
  if (!value || typeof value !== "object") return false;
  const todo = value as Record<string, unknown>;
  return typeof todo.content === "string" && todo.content.length > 0 && todo.content.length <= 160
    && (todo.status === "pending" || todo.status === "in_progress" || todo.status === "completed");
}

export function PlanningTodos() {
  const [assistantId] = useQueryState("assistantId", {
    defaultValue: process.env.NEXT_PUBLIC_ASSISTANT_ID || "",
  });
  const { values } = useStreamContext();
  if (!["deep_diagnosis_planning", "deep_diagnosis_skills"].includes(assistantId) || !Array.isArray(values.todos)
    || values.todos.length === 0 || values.todos.length > 6
    || !values.todos.every(isPlanningTodo)) return null;

  return (
    <section aria-label="诊断计划" className="mx-auto w-full max-w-3xl rounded-lg border bg-background p-4">
      <h2 className="mb-2 text-sm font-semibold">诊断计划</h2>
      <ol className="space-y-2 text-sm">
        {values.todos.map((todo, index) => (
          <li key={`${index}-${todo.content}`} className="flex items-start justify-between gap-4">
            <span>{todo.content}</span>
            <span className="shrink-0 text-muted-foreground">{LABELS[todo.status]}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
