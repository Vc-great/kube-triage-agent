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
  const review = assistantId === "deep_diagnosis_review";
  const notes = assistantId === "deep_diagnosis_offload";
  const skills = assistantId === "deep_diagnosis_skills";
  const switchGraph = () => {
    // A full navigation unmounts the old stream and its Todo/artifact state.
    const target = new URL(window.location.href);
    target.searchParams.set("assistantId", notes ? "deep_diagnosis_offload" : review ? "deep_diagnosis_review" : skills ? "deep_diagnosis_skills"
      : planning ? "deep_diagnosis" : "deep_diagnosis_planning");
    target.searchParams.delete("threadId");
    window.location.assign(target);
  };

  return (
    <section aria-label="Deep Agents Demo" className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/50 px-4 py-2 text-sm">
      <div>
        <p className="font-semibold">{notes ? "Virtual Filesystem Demo · FakeModel + Mock Reader" : review ? "Reviewer Demo · FakeModel + Mock Reader" : skills ? "FakeModel + Mock Reader · 原生 Skills" : "Mock Reader + Real LLM · gpt-6-luna"}</p>
        <p className="text-muted-foreground">{notes ? "/notes/ 工作笔记 · 原生写读与搜索 · 非集群证据 · 自动 Offloading 关闭" : review ? "deep_diagnosis_review · 原生 task 第二意见仅供咨询 · 仅新完成轮次" : skills
          ? "三份内置技能 · 正文按需 read_file · 仅新 Thread，不兼容旧 pin 中途恢复"
          : `合成 Kubernetes 数据 · Planning ${planning ? "ON" : "OFF"} · 切换会新建 Thread`}</p>
      </div>
      <Button variant="outline" disabled={stream.isLoading} onClick={switchGraph}>
        {notes ? "新 Notes Thread" : review ? "新 Reviewer Thread" : skills ? "新 Skills Thread" : `新 Thread · Planning ${planning ? "OFF" : "ON"}`}
      </Button>
    </section>
  );
}
