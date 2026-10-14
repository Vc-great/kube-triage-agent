"""Small ChatOpenAI configuration boundary, required for every diagnosis."""

import os

from langchain_openai import ChatOpenAI

from kube_triage.config import ConfigurationError, validate_llm


def chat_model():
    model, key = validate_llm()
    base_url = os.getenv("LLM_BASE_URL", "").strip() or None
    options = {"model": model, "api_key": key, "base_url": base_url,
               "timeout": 30, "max_retries": 1}
    if os.getenv("TRIAGE_ENV") == "test":
        switch = os.getenv("EVAL_LUNA_RESPONSES_HIGH", "false")
        if switch not in {"true", "false"} or (switch == "true" and model != "gpt-6-luna"):
            raise ConfigurationError("test Luna High 配置与模型不匹配")
    luna_high = (os.getenv("TRIAGE_ENV") == "development" or
                 (os.getenv("TRIAGE_ENV") == "test" and
                  os.getenv("EVAL_LUNA_RESPONSES_HIGH") == "true"))
    if luna_high and model == "gpt-6-luna":
        options.update(use_responses_api=True, reasoning={"effort": "high"})
    return ChatOpenAI(**options)
