"""仅供 TRIAGE_ENV=test 的隔离协议 Smoke；没有 Provider 客户端。"""

import asyncio
import json
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class ProtocolFakeModel(BaseChatModel):
    model_name: str = "phase-a-protocol-fake"

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
        if any(isinstance(message, ToolMessage) for message in current):
            return AIMessage(content="观察：仅有合成 Mock 回执；推断：未判断；未知：真实集群状态。")
        return AIMessage(content="", tool_calls=[{
            "name": "events_list", "args": {"namespace": "kube-triage-demo"},
            "id": "phase-a-events-1",
        }])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(_test_delay())
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(_test_delay())
        reply = self._reply(messages)
        if reply.tool_calls:
            call = reply.tool_calls[0]
            chunk = AIMessageChunk(content="", tool_call_chunks=[{
                "name": call["name"], "args": json.dumps(call["args"]),
                "id": call["id"], "index": 0,
            }])
        else:
            chunk = AIMessageChunk(content=reply.content)
        yield ChatGenerationChunk(message=chunk)


def _test_delay() -> float:
    """Bounded test-only delay for observing Aegra cancellation."""
    raw = os.getenv("DEEP_DIAGNOSIS_FAKE_DELAY_SECONDS", "0")
    try:
        delay = float(raw)
    except ValueError as exc:
        raise ValueError("Fake delay must be between 0 and 10 seconds") from exc
    if not 0 <= delay <= 10:
        raise ValueError("Fake delay must be between 0 and 10 seconds")
    return delay
