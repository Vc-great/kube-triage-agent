"""无 Provider 的 B1 Aegra 协议 Fake；仅使用固定合成 Reader 回执。"""

import asyncio
import json
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class PlanningProtocolFakeModel(BaseChatModel):
    model_name: str = "phase-b1-protocol-fake"

    @property
    def _llm_type(self) -> str:
        return "protocol_fake"

    def _get_ls_params(self, stop=None, **kwargs):
        return {"ls_provider": "protocol_fake", "ls_model_name": self.model_name}

    def bind_tools(self, tools, **kwargs):
        return self

    def _reply(self, messages):
        current = []
        for message in reversed(messages):
            current.append(message)
            if isinstance(message, HumanMessage):
                break
        user = next((message.content for message in current if isinstance(message, HumanMessage)), "")
        if isinstance(user, str) and user.strip().startswith("你好"):
            return AIMessage(content="你好，我可以协助进行只读诊断。")
        tool_ids = {message.tool_call_id for message in current if isinstance(message, ToolMessage)}
        if "b1-todo-update" in tool_ids:
            return AIMessage(content="观察：仅有合成 Mock Event；推断：未知；真实集群状态未测。")
        if "b1-reader-events" in tool_ids:
            return AIMessage(content="", tool_calls=[{
                "name": "write_todos", "args": {"todos": [
                    {"content": "读取合成事件", "status": "completed"},
                    {"content": "汇总证据并说明未知", "status": "completed"},
                ]}, "id": "b1-todo-update",
            }])
        if "b1-todo-plan" in tool_ids:
            return AIMessage(content="", tool_calls=[{
                "name": "events_list", "args": {"namespace": "kube-triage-demo"},
                "id": "b1-reader-events",
            }])
        return AIMessage(content="", tool_calls=[{
            "name": "write_todos", "args": {"todos": [
                {"content": "读取合成事件", "status": "in_progress"},
                {"content": "汇总证据并说明未知", "status": "pending"},
            ]}, "id": "b1-todo-plan",
        }])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(_test_delay())
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(_test_delay())
        reply = self._reply(messages)
        chunks = [{"name": call["name"], "args": json.dumps(call["args"]),
                   "id": call["id"], "index": index}
                  for index, call in enumerate(reply.tool_calls)]
        yield ChatGenerationChunk(message=AIMessageChunk(content=reply.content,
                                                         tool_call_chunks=chunks))


def _test_delay() -> float:
    raw = os.getenv("DEEP_DIAGNOSIS_FAKE_DELAY_SECONDS", "0")
    try:
        delay = float(raw)
    except ValueError as exc:
        raise ValueError("Fake delay must be between 0 and 10 seconds") from exc
    if not 0 <= delay <= 10:
        raise ValueError("Fake delay must be between 0 and 10 seconds")
    return delay
