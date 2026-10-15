"""Deterministic, conservative view of checkpoint messages for one LLM call.

The estimate is deliberately not a provider token count. No input message is mutated.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from kube_triage.config import ConfigurationError

OUTPUT_RESERVE = 2048
OMISSION_WARNING = ("部分历史轮次已省略；不要将历史当作当前事实，"
                    "当前状态必须重新使用只读工具核验。")


@dataclass(frozen=True)
class ContextConfig:
    enabled: bool
    total_budget: int

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigurationError("CONTEXT_WINDOW_ENABLED 必须为 true 或 false")
        if (isinstance(self.total_budget, bool) or not isinstance(self.total_budget, int)
                or self.total_budget <= OUTPUT_RESERVE):
            raise ConfigurationError("CONTEXT_ESTIMATED_TOTAL_BUDGET 必须为大于 2048 的整数")


@dataclass(frozen=True)
class ContextPlan:
    ok: bool
    messages: tuple[BaseMessage, ...]
    status: str
    estimated_tokens: int | None
    omitted_rounds: int
    error_code: str | None = None


def load_context_config() -> ContextConfig:
    enabled = os.getenv("CONTEXT_WINDOW_ENABLED", "false").lower()
    if enabled not in {"true", "false"}:
        raise ConfigurationError("CONTEXT_WINDOW_ENABLED 必须为 true 或 false")
    raw_budget = os.getenv("CONTEXT_ESTIMATED_TOTAL_BUDGET", "16384")
    if not raw_budget.isdecimal():
        raise ConfigurationError("CONTEXT_ESTIMATED_TOTAL_BUDGET 必须为大于 2048 的整数")
    return ContextConfig(enabled == "true", int(raw_budget))


def _json_bytes(value: object) -> int:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("context input cannot be estimated") from None
    return len(encoded.encode("utf-8"))


def estimate_context(prompt: str, schemas: Sequence[dict],
                     messages: Sequence[BaseMessage]) -> int:
    """ceil((serialized UTF-8 bytes/2 + 8 per message)*1.2) + output reserve."""
    if not isinstance(prompt, str):
        raise TypeError("context prompt cannot be estimated")
    try:
        serialized = [SystemMessage(content=prompt), *messages]
        byte_count = _json_bytes(list(schemas))
        for message in serialized:
            if not isinstance(message, BaseMessage):
                raise TypeError("context message cannot be estimated")
            byte_count += _json_bytes(message.model_dump(mode="json"))
    except Exception:  # noqa: BLE001 - arbitrary message payloads must fail closed
        raise ValueError("context input cannot be estimated") from None
    return math.ceil((byte_count / 2 + 8 * len(serialized)) * 1.2) + OUTPUT_RESERVE


def _safe_round(messages: Sequence[BaseMessage], *, complete: bool,
                used_ids: set[str]) -> bool:
    if not messages or not isinstance(messages[0], HumanMessage):
        return False
    pending: set[str] = set()
    for message in messages[1:]:
        if isinstance(message, AIMessage):
            if pending or message.invalid_tool_calls:
                return False
            for call in message.tool_calls:
                ident = call.get("id")
                if not isinstance(ident, str) or not ident or ident in used_ids:
                    return False
                used_ids.add(ident)
                pending.add(ident)
        elif isinstance(message, ToolMessage):
            if message.tool_call_id not in pending:
                return False
            pending.remove(message.tool_call_id)
        else:
            return False
    if pending:
        return False
    return not complete or isinstance(messages[-1], AIMessage)


def _split_safe_rounds(messages: Sequence[BaseMessage]) -> list[tuple[BaseMessage, ...]] | None:
    starts = [index for index, message in enumerate(messages)
              if isinstance(message, HumanMessage)]
    if not starts or starts[0] != 0:
        return None
    rounds = [tuple(messages[start:end]) for start, end in zip(starts, [*starts[1:], len(messages)])]
    used_ids: set[str] = set()
    for index, turn in enumerate(rounds):
        if not _safe_round(turn, complete=index < len(rounds) - 1, used_ids=used_ids):
            return None
    return rounds


def build_context_view(prompt: str, schemas: Sequence[dict],
                       messages: Sequence[BaseMessage], config: ContextConfig) -> ContextPlan:
    """Return a temporary model input or a fail-closed, data-free decision."""
    if not config.enabled:
        return ContextPlan(True, (SystemMessage(content=prompt), *messages),
                           "disabled", None, 0)
    try:
        full_estimate = estimate_context(prompt, schemas, messages)
    except ValueError:
        return ContextPlan(False, (), "rejected", None, 0, "unestimable_input")
    if full_estimate <= config.total_budget:
        return ContextPlan(True, (SystemMessage(content=prompt), *messages),
                           "fits", full_estimate, 0)
    rounds = _split_safe_rounds(messages)
    if rounds is None:
        return ContextPlan(False, (), "rejected", full_estimate, 0, "unsafe_history")
    if len(rounds) == 1:
        return ContextPlan(False, (), "rejected", full_estimate, 0, "over_budget")
    for omitted in range(1, len(rounds)):
        retained = tuple(message for turn in rounds[omitted:] for message in turn)
        warned_prompt = f"{prompt}\n{OMISSION_WARNING}"
        try:
            estimate = estimate_context(warned_prompt, schemas, retained)
        except ValueError:
            return ContextPlan(False, (), "rejected", None, 0, "unestimable_input")
        if estimate <= config.total_budget:
            return ContextPlan(True, (SystemMessage(content=warned_prompt), *retained),
                               "trimmed", estimate, omitted)
    return ContextPlan(False, (), "rejected", full_estimate, 0, "over_budget")
