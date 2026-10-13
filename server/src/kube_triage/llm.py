"""Small ChatOpenAI configuration boundary, required for every diagnosis."""

import os

from langchain_openai import ChatOpenAI

from kube_triage.config import validate_llm


def chat_model():
    model, key = validate_llm()
    base_url = os.getenv("LLM_BASE_URL", "").strip() or None
    options = {"model": model, "api_key": key, "base_url": base_url,
               "timeout": 30, "max_retries": 1}
    if os.getenv("TRIAGE_ENV") == "development" and model == "gpt-6-luna":
        options.update(use_responses_api=True, reasoning={"effort": "high"})
    return ChatOpenAI(**options)
