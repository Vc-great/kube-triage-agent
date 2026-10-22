"""V2 演示协议 Fake；只验证渐进加载/工具协议，不代表真实模型质量。"""

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from kube_triage.deep_diagnosis_planning_fake import PlanningProtocolFakeModel

ROOT = "/skills/kubernetes/"


class SkillsProtocolFakeModel(PlanningProtocolFakeModel):
    model_name: str = "skills-v2-protocol-fake"

    def _reply(self, messages):
        turn = []
        for message in reversed(messages):
            turn.append(message)
            if isinstance(message, HumanMessage):
                break
        turn.reverse()
        user = next((m.text for m in turn if isinstance(m, HumanMessage)), "")
        replies = [m for m in turn if isinstance(m, ToolMessage)]
        lowered = user.lower()
        if user.strip().startswith("你好") or lowered.strip() in {"hello", "hi"}:
            return AIMessage(content="你好，我可以协助只读 Kubernetes 诊断；本次未加载技能正文。")
        if "上轮" in user:
            previous = [m for m in messages[:-len(turn)]
                        if isinstance(m, AIMessage) and not m.tool_calls]
            return AIMessage(content="上轮普通历史：" + (previous[-1].content if previous else "UNKNOWN"))
        selected = ("oom-diagnosis" if "oom" in lowered else
                    "imagepull-diagnosis" if "imagepull" in lowered or "镜像" in user else
                    "crashloop-diagnosis" if "crashloop" in lowered or "重启" in user else None)
        pod = ("oom-pod" if selected == "oom-diagnosis" else
               "imagepull-pod" if selected == "imagepull-diagnosis" else
               "healthy-pod" if "healthy" in lowered else "crashloop-pod")
        namespace = {"namespace": "kube-triage-demo"}
        # OFF evaluation has no Skills catalog, so the same protocol goes straight
        # to Reader. ON chooses from metadata and loads only the matching body.
        catalog = any("## 内置诊断 Skills" in str(m.content) for m in messages)
        if selected and catalog and not replies:
            return self._call("read_file", {"file_path": ROOT + selected + "/SKILL.md"}, "skill")
        readers = [m for m in replies if m.name != "read_file"]
        steps = [
            ("pods_list_in_namespace", namespace),
            ("pods_get", {**namespace, "name": pod}),
            ("events_list", namespace),
            ("pods_log", {**namespace, "name": pod, "tail": 20}),
        ]
        if len(readers) < len(steps):
            name, args = steps[len(readers)]
            return self._call(name, args, name)
        envelopes = []
        for reply in readers:
            try:
                data = json.loads(reply.content)
            except (TypeError, ValueError):
                data = {}
            if reply.status == "error" or data.get("ok") is not True:
                return AIMessage(content=f"观察：Reader {reply.tool_call_id} 失败；"
                                 "推断：UNKNOWN；未知：当前状态与根因未核验。")
            envelopes.append(data)
        try:
            detail = json.loads(envelopes[1]["result"])
            uid = detail["metadata"]["uid"]
            status = detail["status"]["containerStatuses"][0]
        except (KeyError, IndexError, TypeError, ValueError):
            return AIMessage(content="观察：合成 Reader 缺少有效 Pod 详情；推断：UNKNOWN；当前状态未核验。")
        return AIMessage(content=(
            f"观察（合成 Mock，非真实集群）：Pod {pod}，UID={uid}；"
            f"本轮 {readers[1].tool_call_id} 的 containerStatuses={json.dumps(status, ensure_ascii=False)}。"
            f"事件与有限日志见 {readers[2].tool_call_id}、{readers[3].tool_call_id}。\n"
            "推断：状态和最近终止仅提供调查线索，不能确认唯一根因。\n"
            "未知（UNKNOWN）：没有 previous 日志、Metrics、历史峰值或 Registry 探测；"
            "不确认内存泄漏、凭据或网络原因。未执行 Repair。"
        ))

    @staticmethod
    def _call(name, args, stage):
        return AIMessage(content="", tool_calls=[{
            "name": name, "args": args, "id": f"skills-{stage}",
        }])
