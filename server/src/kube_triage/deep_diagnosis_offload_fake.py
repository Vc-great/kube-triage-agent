"""合成笔记协议 Fake：实际发送 SDK Tool Call，成功与否由 ToolMessage 决定。"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from kube_triage.deep_diagnosis_planning_fake import PlanningProtocolFakeModel

NOTE = "/notes/diagnosis.md"


class NotesProtocolFakeModel(PlanningProtocolFakeModel):
    model_name: str = "issue69-notes-protocol-fake"

    def _get_ls_params(self, stop=None, **kwargs):
        return {"ls_provider": "notes_fake", "ls_model_name": self.model_name}

    def _reply(self, messages):
        turn = []
        for message in reversed(messages):
            turn.append(message)
            if isinstance(message, HumanMessage):
                break
        turn.reverse()
        user = next((m.text for m in turn if isinstance(m, HumanMessage)), "")
        replies = [m for m in turn if isinstance(m, ToolMessage)]
        if user.strip().startswith("你好"):
            return AIMessage(content="你好，这是合成虚拟笔记 Demo；真实集群状态 UNKNOWN。")
        read_only = "读取" in user or "刷新" in user
        missing = "不存在" in user
        denied = "越界" in user
        if missing or denied:
            steps = [("read_file", {"file_path": "/notes/missing.md" if missing else "/etc/passwd"})]
        elif read_only:
            steps = [("read_file", {"file_path": NOTE}), ("ls", {"path": "/notes/"}),
                     ("grep", {"pattern": "合成", "path": "/notes/", "output_mode": "content"})]
        else:
            todo = {"content": "读取合成事件并保存工作笔记", "status": "in_progress"}
            event = next((m.content for m in replies if m.name == "events_list"), "UNKNOWN")
            steps = [
                ("write_todos", {"todos": [todo]}),
                ("events_list", {"namespace": "kube-triage-demo"}),
                ("write_file", {"file_path": NOTE, "content":
                    "# 合成调查笔记\n来源：本轮 Mock events_list，非真实集群。\n" + event +
                    "\n推断：尚不能确认根因。未知：真实集群状态 UNKNOWN。"}),
                ("read_file", {"file_path": NOTE}), ("ls", {"path": "/notes/"}),
                ("grep", {"pattern": "合成", "path": "/notes/", "output_mode": "content"}),
                ("write_todos", {"todos": [{**todo, "status": "completed"}]}),
            ]
        if replies and replies[-1].status == "error":
            return AIMessage(content=f"观察：{replies[-1].name} 失败：{replies[-1].content}\n"
                             "推断：笔记操作未完成；未知：真实状态 UNKNOWN。")
        if len(replies) < len(steps):
            name, args = steps[len(replies)]
            turn_number = sum(isinstance(m, HumanMessage) for m in messages)
            return AIMessage(content="", tool_calls=[{
                "name": name, "args": args, "id": f"notes-{turn_number}-{len(replies)}",
            }])
        read = next((m.content for m in replies if m.name == "read_file"), "UNKNOWN")
        return AIMessage(content="观察：已通过原生文件工具读取 /notes/diagnosis.md：\n" + read +
                         "\n推断：这是模型工作笔记；未知：真实集群状态 UNKNOWN，未执行 Repair。")
