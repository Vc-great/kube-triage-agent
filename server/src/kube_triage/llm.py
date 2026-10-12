"""Small ChatOpenAI configuration boundary, created only for enabled runs."""

import os

from langchain_openai import ChatOpenAI


def enabled() -> bool:
    value = os.getenv("LLM_ENABLED", "false").lower()
    if value not in {"true", "false"}:
        raise ValueError("LLM_ENABLED 必须为 true 或 false")
    return value == "true"


def chat_model():
    model = os.getenv("LLM_MODEL", "").strip()
    key = os.getenv("LLM_API_KEY", "").strip()
    if not model or not key:
        raise ValueError("LLM 配置错误：LLM_MODEL 和 LLM_API_KEY 均必须设置")
    base_url = os.getenv("LLM_BASE_URL", "").strip() or None
    return ChatOpenAI(model=model, api_key=key, base_url=base_url,
                      timeout=30, max_retries=1)
