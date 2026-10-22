"""Test-only formal Graph entrypoint, using FakeModel + the real Mock MCP transport."""

import asyncio
import os

if os.getenv("TRIAGE_ENV") != "test":
    raise RuntimeError("Issue #78 FakeModel profile requires TRIAGE_ENV=test")

from langchain_core.messages import HumanMessage

from kube_triage import graph as agent
from kube_triage.config import ConfigurationError
from kube_triage.deep_diagnosis_fake import ProtocolFakeModel


class HistoryFakeModel(ProtocolFakeModel):
    def _reply(self, messages):
        human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        if human.content == "/fake-fail":
            raise ConfigurationError("synthetic model failure")
        return super()._reply(messages)

    async def _agenerate(self, messages, **kwargs):
        human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        if human.content == "/fake-slow":
            await asyncio.sleep(3)
        return await super()._agenerate(messages, **kwargs)

    async def _astream(self, messages, **kwargs):
        human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        if human.content == "/fake-slow":
            await asyncio.sleep(3)
        async for chunk in super()._astream(messages, **kwargs):
            yield chunk

agent.chat_model = lambda: HistoryFakeModel()
graph = agent.graph
