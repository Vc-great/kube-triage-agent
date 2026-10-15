"""Fail-closed boundary for the formal service and explicit offline tests."""

import os


class ConfigurationError(ValueError):
    """Invalid configuration must fail startup or the diagnosis Run."""


def incident_memory_write_enabled() -> bool:
    """Two explicit opt-ins; malformed values fail startup and never grant writes."""
    values = []
    for name in ("INCIDENT_MEMORY_ENABLED", "INCIDENT_MEMORY_WRITE_ENABLED"):
        value = os.getenv(name, "false")
        if value not in {"true", "false"}:
            raise ConfigurationError(f"{name} 必须为 true 或 false")
        values.append(value == "true")
    return all(values)


def incident_memory_provenance_key() -> bytes:
    """Separate server-only HMAC key; the public Demo API key must not sign evidence."""
    value = os.getenv("INCIDENT_MEMORY_PROVENANCE_SECRET", "")
    if (len(value) < 32 or len(value) > 256 or not value.isascii()
            or value == os.getenv("DEMO_API_TOKEN", "")):
        raise ConfigurationError("INCIDENT_MEMORY_PROVENANCE_SECRET 必须是 32–256 字符的服务端密钥")
    return value.encode("ascii")


def test_mode() -> bool:
    mode = os.getenv("TRIAGE_ENV", "production")
    if mode not in {"production", "development", "test"}:
        raise ConfigurationError("TRIAGE_ENV 必须为 production、development 或 test")
    simulated = os.getenv("REPAIR_SIMULATED", "false").lower()
    if simulated not in {"true", "false"}:
        raise ConfigurationError("REPAIR_SIMULATED 必须为 true 或 false")
    if simulated == "true" and mode != "test":
        raise ConfigurationError("正式环境禁止 REPAIR_SIMULATED=true")
    return mode == "test"


def validate_llm() -> tuple[str, str]:
    test_mode()
    if os.getenv("LLM_ENABLED", "true").lower() != "true":
        raise ConfigurationError("LLM_ENABLED=false 已移除；诊断必须使用真实 LLM")
    model = os.getenv("LLM_MODEL", "").strip()
    key = os.getenv("LLM_API_KEY", "").strip()
    if not model or not key:
        raise ConfigurationError("LLM 配置错误：LLM_MODEL 和 LLM_API_KEY 均必须设置")
    return model, key


def reader_url() -> str:
    testing = test_mode()
    url = os.getenv("MCP_SERVER_URL", "").strip()
    expected = "http://mock-mcp:8000/mcp" if testing else "http://k8s-mcp:8080/mcp"
    if os.getenv("TRIAGE_ENV") == "development":
        expected = "http://127.0.0.1:18080/mcp"
    if url != expected:
        raise ConfigurationError("Reader 配置错误：必须使用当前环境的项目内部 MCP endpoint")
    return url


def validate_service() -> None:
    if incident_memory_write_enabled():
        incident_memory_provenance_key()
    validate_llm()
    reader_url()
    from kube_triage.context import load_context_config, load_summary_enabled
    context_config = load_context_config()
    load_summary_enabled(context_config.enabled)


if __name__ == "__main__":
    try:
        validate_service()
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from None
