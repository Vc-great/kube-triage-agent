import { useQueryState } from "nuqs";
import { Button } from "@/components/ui/button";
import { useStreamContext } from "@/providers/Stream";

export function DeepDemoControls() {
  const [assistantId] = useQueryState("assistantId", {
    defaultValue: process.env.NEXT_PUBLIC_ASSISTANT_ID || "",
  });
  const stream = useStreamContext();
  if (process.env.NEXT_PUBLIC_DEEP_DEMO !== "true") return null;

  const planning = assistantId === "deep_diagnosis_planning";
  const switchGraph = () => {
    // A full navigation unmounts the old stream and its Todo/artifact state.
    const target = new URL(window.location.href);
    target.searchParams.set("assistantId", planning ? "deep_diagnosis" : "deep_diagnosis_planning");
    target.searchParams.delete("threadId");
    window.location.assign(target);
  };

  return (
    <section aria-label="Deep Agents Demo" className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/50 px-4 py-2 text-sm">
      <div>
        <p className="font-semibold">Mock Reader + Real LLM · gpt-6-luna</p>
        <p className="text-muted-foreground">合成 Kubernetes 数据 · Planning {planning ? "ON" : "OFF"} · 切换会新建 Thread</p>
      </div>
      <Button variant="outline" disabled={stream.isLoading} onClick={switchGraph}>
        新 Thread · Planning {planning ? "OFF" : "ON"}
      </Button>
    </section>
  );
}
