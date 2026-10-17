"""Langfuse export stays in the API process for every local profile."""

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
spec = importlib.util.spec_from_file_location("dev_langfuse", ROOT / "scripts/dev.py")
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)
FAKE_VALUES = {"POSTGRES_PASSWORD": "db-fake", "DEMO_API_TOKEN": "demo-fake",
               "LLM_MODEL": "fake-model", "LLM_API_KEY": "model-fake"}
HOST_ENV = {"PATH": "/usr/bin", "LANGFUSE_SECRET_KEY": "host-secret",
            "OTEL_TARGETS": "LANGFUSE"}


def source_file(tmp_path, content=None):
    source = tmp_path / "private.env"
    source.write_text(content or (
        'LANGFUSE_SECRET_KEY="sk-fake"\nLANGFUSE_PUBLIC_KEY="pk-fake"\n'
        'LANGFUSE_BASE_URL="https://jp.cloud.langfuse.com/"\nOTHER_VALUE=ignored\n'
    ))
    source.chmod(0o600)
    return source


@pytest.mark.parametrize("mode", list(dev.PROFILES))
def test_valid_keys_auto_enable_every_local_profile_only_in_api(tmp_path, monkeypatch, mode):
    source = source_file(tmp_path)
    monkeypatch.setattr(dev, "ENV_FILE", source)
    values = {**FAKE_VALUES, "INCIDENT_MEMORY_PROVENANCE_SECRET": "hmac-fake"}
    children = dev.child_environments(mode, values, HOST_ENV)
    assert children["api"]["OTEL_TARGETS"] == "LANGFUSE"
    assert children["api"]["OTEL_SERVICE_NAME"] == f"kube-triage-agent-{mode}"
    assert children["api"]["OTEL_CONSOLE_EXPORT"] == "false"
    assert children["api"]["LANGFUSE_BASE_URL"] == "https://jp.cloud.langfuse.com"
    assert {key for key in children["api"] if key.startswith("LANGFUSE_")} == dev.LANGFUSE_KEYS
    preflight = dev.preflight_environment(children["api"])
    assert preflight["OTEL_TARGETS"] == ""
    assert not any(key.startswith("LANGFUSE_") for key in preflight)
    for name, environment in children.items():
        if name == "api":
            continue
        assert not any(key.startswith("LANGFUSE_") for key in environment)
        assert "OTEL_TARGETS" not in environment


def test_web_only_mode_delegates_to_remote_api_without_local_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(dev, "ENV_FILE", tmp_path / "absent.env")
    children = dev.child_environments("web", FAKE_VALUES, HOST_ENV)
    assert set(children) == {"web"}
    for child in children.values():
        assert "host-secret" not in child.values()


@pytest.mark.parametrize("mode", ["mock", "real", "memory"])
def test_missing_keys_default_off_and_do_not_inherit_host_keys(monkeypatch, tmp_path, mode):
    monkeypatch.setattr(dev, "ENV_FILE", source_file(tmp_path, "OTHER_VALUE=ignored\n"))
    values = {**FAKE_VALUES, "INCIDENT_MEMORY_PROVENANCE_SECRET": "hmac-fake"}
    children = dev.child_environments(mode, values, HOST_ENV)
    assert children["api"]["OTEL_TARGETS"] == ""
    assert children["api"]["OTEL_CONSOLE_EXPORT"] == "false"
    assert not any(key.startswith("LANGFUSE_") for child in children.values() for key in child)


def test_root_env_filters_compose_fields_and_late_loads_keys(monkeypatch, tmp_path):
    config = tmp_path / ".env"
    config.write_text(
        "POSTGRES_PASSWORD=db-fake\nDEMO_API_TOKEN=demo-fake\n"
        "LLM_MODEL=fake-model\nLLM_API_KEY=model-fake\n"
        "WEB_PORT=13000\nREPAIR_ENABLED=false\n"
        "LANGFUSE_SECRET_KEY=sk-fake\nLANGFUSE_PUBLIC_KEY=pk-fake\n"
        "LANGFUSE_BASE_URL=https://jp.cloud.langfuse.com\n"
    )
    config.chmod(0o600)
    monkeypatch.setattr(dev, "ENV_FILE", config)
    values = dev.read_env()
    assert values == FAKE_VALUES
    children = dev.child_environments("mock", values, HOST_ENV)
    assert children["api"]["LANGFUSE_SECRET_KEY"] == "sk-fake"
    assert "LANGFUSE_SECRET_KEY" not in dev.preflight_environment(children["api"])
    config.write_text("LANGFUSE_SECRET_KEY=one\nLANGFUSE_SECRET_KEY=two\n")
    assert dev.read_env() == {}
    with pytest.raises(RuntimeError, match="LANGFUSE_SOURCE_DUPLICATE"):
        dev.child_environments("mock", FAKE_VALUES)
    config.write_text("TRIAGE_ENV=test\n")
    with pytest.raises(RuntimeError, match="不允许配置 TRIAGE_ENV"):
        dev.read_env()
    config.write_text("LANGFUSE_SECRET_KEY sk-fake=bad\n")
    assert dev.read_env() == {}
    with pytest.raises(RuntimeError, match="LANGFUSE_SOURCE_FORMAT_INVALID") as error:
        dev.child_environments("mock", FAKE_VALUES)
    assert "sk-fake" not in str(error.value)
    monkeypatch.setattr(dev.os, "getuid", lambda: -1)
    with pytest.raises(RuntimeError, match="当前用户持有"):
        dev.read_env()


def test_legacy_switch_does_not_block_key_auto_enable(tmp_path, monkeypatch):
    monkeypatch.setattr(dev, "ENV_FILE", source_file(tmp_path))
    children = dev.child_environments(
        "mock", {**FAKE_VALUES, "LANGFUSE_TRACING_ENABLED": "false"}, HOST_ENV)
    assert children["api"]["OTEL_TARGETS"] == "LANGFUSE"


def test_optional_source_rejects_partial_keys(tmp_path):
    source = source_file(tmp_path, "LANGFUSE_SECRET_KEY=sk-fake\n")
    with pytest.raises(RuntimeError, match="LANGFUSE_SOURCE_KEYS_MISSING"):
        dev.read_langfuse_env(source, optional=True)


@pytest.mark.parametrize("stack", ["formal", "dev01", "test"])
def test_compose_auto_overlay_and_host_key_isolation(tmp_path, monkeypatch, stack):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import compose_with_langfuse as compose

    source = source_file(tmp_path)
    monkeypatch.setattr(compose, "ENV_FILE", source)
    command, environment = compose.compose_invocation(
        stack, "isolated-project", ["config", "--quiet"], HOST_ENV)
    assert command.count("infra/langfuse.compose.yaml") == 1
    expected_file = "infra/test.compose.yaml" if stack == "test" else "infra/compose.yaml"
    assert expected_file in command
    assert environment["LANGFUSE_SECRET_KEY"] == "sk-fake"
    assert environment["LANGFUSE_PUBLIC_KEY"] == "pk-fake"
    source.write_text("OTHER_VALUE=ignored\n")
    command, environment = compose.compose_invocation(
        stack, "isolated-project", ["config", "--quiet"], HOST_ENV)
    assert "infra/langfuse.compose.yaml" not in command
    assert "LANGFUSE_SECRET_KEY" not in environment


def test_compose_partial_key_fails_before_docker(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    import compose_with_langfuse as compose

    monkeypatch.setattr(compose, "ENV_FILE", source_file(tmp_path, "LANGFUSE_PUBLIC_KEY=pk-fake\n"))
    with pytest.raises(RuntimeError, match="LANGFUSE_SOURCE_KEYS_MISSING"):
        compose.compose_invocation("dev01", "isolated-project", ["config"], HOST_ENV)


@pytest.mark.parametrize("content,code", [
    ('LANGFUSE_SECRET_KEY="sk-fake"\nLANGFUSE_SECRET_KEY="again"\n',
     "LANGFUSE_SOURCE_DUPLICATE"),
    ('LANGFUSE_SECRET_KEY "sk-fake"\n', "LANGFUSE_SOURCE_FORMAT_INVALID"),
    ('LANGFUSE_SECRET_KEY="sk-fake\n', "LANGFUSE_SOURCE_FORMAT_INVALID"),
    ('LANGFUSE_SECRET_KEY=sk-fake\nLANGFUSE_PUBLIC_KEY=pk-fake\n',
     "LANGFUSE_SOURCE_KEYS_MISSING"),
    (('LANGFUSE_SECRET_KEY=sk-fake\nLANGFUSE_PUBLIC_KEY=pk-fake\n'
      'LANGFUSE_BASE_URL=http://jp.cloud.langfuse.com\n'), "LANGFUSE_URL_INVALID"),
    (('LANGFUSE_SECRET_KEY=sk-fake\nLANGFUSE_PUBLIC_KEY=pk-fake\n'
      'LANGFUSE_BASE_URL=https://jp.cloud.langfuse.com/api/public/otel/v1/traces\n'),
     "LANGFUSE_URL_INVALID"),
    (('LANGFUSE_SECRET_KEY=sk-fake\nLANGFUSE_PUBLIC_KEY=pk-fake\n'
      'LANGFUSE_BASE_URL=https://jp.cloud.langfuse.com?token=bad\n'),
     "LANGFUSE_URL_INVALID"),
    (('LANGFUSE_SECRET_KEY=sk-fake\nLANGFUSE_PUBLIC_KEY=pk-fake\n'
      'LANGFUSE_BASE_URL=https://someone@jp.cloud.langfuse.com\n'),
     "LANGFUSE_URL_INVALID"),
    (('LANGFUSE_SECRET_KEY=sk-fake\nLANGFUSE_PUBLIC_KEY=pk-fake\n'
      'LANGFUSE_BASE_URL=https://other.cloud.langfuse.com\n'),
     "LANGFUSE_URL_INVALID"),
])
def test_bad_source_fails_without_echo(tmp_path, content, code):
    source = source_file(tmp_path, content)
    with pytest.raises(RuntimeError, match=code) as error:
        dev.read_langfuse_env(source)
    assert "sk-fake" not in str(error.value)
    assert "pk-fake" not in str(error.value)


def test_symlink_mode_and_missing_file_are_rejected(tmp_path):
    source = source_file(tmp_path)
    link = tmp_path / "link.env"
    link.symlink_to(source)
    with pytest.raises(RuntimeError, match="LANGFUSE_SOURCE_UNAVAILABLE"):
        dev.read_langfuse_env(link)
    source.chmod(0o644)
    with pytest.raises(RuntimeError, match="LANGFUSE_SOURCE_MODE_INVALID"):
        dev.read_langfuse_env(source)
    with pytest.raises(RuntimeError, match="LANGFUSE_SOURCE_UNAVAILABLE"):
        dev.read_langfuse_env(tmp_path / "missing.env")
    with pytest.raises(RuntimeError, match="LANGFUSE_SOURCE_PATH_INVALID"):
        dev.read_langfuse_env(Path("relative.env"))


def test_non_regular_or_foreign_owner_is_rejected(tmp_path, monkeypatch):
    pipe = tmp_path / "pipe.env"
    os.mkfifo(pipe, mode=0o600)
    with pytest.raises(RuntimeError, match="LANGFUSE_SOURCE_OWNER_INVALID"):
        dev.read_langfuse_env(pipe)
    source = source_file(tmp_path)
    monkeypatch.setattr(dev.os, "getuid", lambda: -1)
    with pytest.raises(RuntimeError, match="LANGFUSE_SOURCE_OWNER_INVALID"):
        dev.read_langfuse_env(source)
