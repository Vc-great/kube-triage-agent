"""双 FakeModel：真实执行原生 task，仅检验合成协议，不衡量模型质量。"""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from kube_triage.deep_diagnosis_planning_fake import PlanningProtocolFakeModel


class ReviewProtocolFakeModel(PlanningProtocolFakeModel):
    model_name: str = "review-parent-protocol-fake"
    review_enabled: bool = True

    def _reply(self, messages):
        turn = []
        for message in reversed(messages):
            turn.append(message)
            if isinstance(message, HumanMessage):
                break
        turn.reverse()
        user = turn[0].text
        if user in {"你好", "hi", "hello"}:
            return AIMessage(content="你好")
        ids = {m.tool_call_id for m in turn if isinstance(m, ToolMessage)}
        pod = ("imagepull-pod" if "ImagePull" in user else
               "oom-pod" if "OOM" in user else "crashloop-pod")
        if "错误证据" in user:
            pod = "malformed-pod"
        elif "403" in user:
            pod = "forbidden-pod"
        elif "timeout" in user:
            pod = "timeout-pod"
        ns = {"namespace": "kube-triage-demo"}
        steps = [
            ("write_todos", {"todos": [{"content": "只读取证并委派第二意见", "status": "in_progress"}]}, "todo"),
            ("pods_list_in_namespace", ns, "list"),
            ("pods_get", {**ns, "name": pod}, "pod"),
            ("events_list", ns, "events"),
            ("pods_log", {**ns, "name": pod, "tail": 20}, "log"),
        ]
        if "缺证据" in user:
            return AIMessage(content="没有足够证据")
        for name, args, stage in steps:
            if "review-" + stage not in ids:
                return self._call(name, args, stage)
        if self.review_enabled and "Reviewer OFF" not in user and "review-task" not in ids:
            return self._call("task", {"subagent_type": "evidence-reviewer",
                "description": ("模拟 Reviewer 失败" if "Reviewer失败" in user else
                    "错误引用候选" if "错误引用" in user else
                    "矛盾候选" if "矛盾" in user else f"Pod {pod} 存在异常状态线索")}, "task")
        return AIMessage(content="观察/推断/未知由 Host 校验并呈现。")

    @staticmethod
    def _call(name, args, stage):
        return AIMessage(content="", tool_calls=[{"name": name, "args": args,
                                                  "id": "review-" + stage}])


class ReviewerProtocolFakeModel(PlanningProtocolFakeModel):
    model_name: str = "reviewer-protocol-fake"

    def bind_tools(self, tools, **kwargs):
        if tools:
            raise ValueError("Reviewer 不允许执行工具")
        return self

    def _reply(self, messages):
        manifest = json.loads(next(m.text for m in reversed(messages) if isinstance(m, HumanMessage)))
        candidate = manifest["candidate_claim"]["text"]
        if "模拟 Reviewer 失败" in candidate:
            raise RuntimeError("Synthetic reviewer failure")
        usable = [e["source_tool_call_id"] for e in manifest["evidence"]
                  if e["usable_for_diagnosis"]]
        good = usable and not manifest["incomplete"] and all(
            e["status"] == "success" for e in manifest["evidence"])
        verdict = ("CONTRADICTS" if "矛盾" in candidate else "SUPPORTS") if good else "INSUFFICIENT"
        refs = usable if good else [e["source_tool_call_id"] for e in manifest["evidence"]][:1]
        if "错误引用" in candidate:
            refs = ["nonexistent-receipt"]
        return AIMessage(content=json.dumps({"verdict": verdict,
            "supported_claims": [candidate] if verdict == "SUPPORTS" else [],
            "contradictions": ["候选与合成材料不一致"] if verdict == "CONTRADICTS" else [],
            "evidence_refs": refs, "unknowns": ["真实根因未核验"],
            "recommended_next_read": "需要更多只读证据", "reason": "固定合成协议第二意见"}, ensure_ascii=False))
