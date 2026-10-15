"""Phase 3-2 flag and HTTP guard regression tests without external services."""

import importlib

import pytest

from kube_triage.config import (
    ConfigurationError,
    incident_memory_http_write_blocked,
    incident_memory_max_candidates,
    incident_memory_max_hits,
    incident_memory_read_enabled,
    incident_memory_write_enabled,
    validate_service,
)


@pytest.mark.parametrize("read,write,blocked", [
    ("false", "false", False),
    ("false", "true", True),
    ("true", "false", True),
    ("true", "true", True),
])
def test_memory_flags(monkeypatch, read, write, blocked):
    monkeypatch.setenv("INCIDENT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_READ_ENABLED", read)
    monkeypatch.setenv("INCIDENT_MEMORY_WRITE_ENABLED", write)
    assert incident_memory_read_enabled() is (read == "true")
    assert incident_memory_write_enabled() is (write == "true")
    assert incident_memory_http_write_blocked() is blocked


def test_read_requires_master_and_strict_values(monkeypatch):
    monkeypatch.setenv("INCIDENT_MEMORY_ENABLED", "false")
    monkeypatch.setenv("INCIDENT_MEMORY_READ_ENABLED", "true")
    with pytest.raises(ConfigurationError):
        incident_memory_read_enabled()
    monkeypatch.setenv("INCIDENT_MEMORY_READ_ENABLED", "TRUE")
    with pytest.raises(ConfigurationError):
        incident_memory_http_write_blocked()
    monkeypatch.setenv("INCIDENT_MEMORY_READ_ENABLED", "false")
    monkeypatch.setenv("INCIDENT_MEMORY_WRITE_ENABLED", "TRUE")
    with pytest.raises(ConfigurationError):
        incident_memory_write_enabled()


def test_bounded_limits(monkeypatch):
    assert incident_memory_max_hits() == 2
    assert incident_memory_max_candidates() == 20
    for key, invalid, reader in [
        ("INCIDENT_MEMORY_MAX_HITS", "0", incident_memory_max_hits),
        ("INCIDENT_MEMORY_MAX_HITS", "4", incident_memory_max_hits),
        ("INCIDENT_MEMORY_MAX_CANDIDATES", "101", incident_memory_max_candidates),
    ]:
        monkeypatch.setenv(key, invalid)
        with pytest.raises(ConfigurationError):
            reader()
        monkeypatch.delenv(key)


def test_http_guard_read_only_and_key_required(monkeypatch):
    monkeypatch.setenv("DEMO_API_TOKEN", "synthetic-demo-token")
    monkeypatch.setenv("INCIDENT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_READ_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_WRITE_ENABLED", "false")
    monkeypatch.setenv("INCIDENT_MEMORY_PROVENANCE_SECRET", "synthetic-provenance-secret-32chars-32")
    from kube_triage import auth as auth_module
    importlib.reload(auth_module)
    assert auth_module.MEMORY_HTTP_WRITE_BLOCKED is True


def test_read_only_service_requires_server_hmac(monkeypatch):
    monkeypatch.setenv("INCIDENT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_READ_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_WRITE_ENABLED", "false")
    monkeypatch.delenv("INCIDENT_MEMORY_PROVENANCE_SECRET", raising=False)
    with pytest.raises(ConfigurationError, match="PROVENANCE_SECRET"):
        validate_service()
