"""只从既有 .env 白名单派生 Phase 3-4 的本机隔离配置。"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import secrets
import socket
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
PRIVATE = ROOT / ".local/phase34"
ARMS = {"A": ("false", "false"), "B": ("true", "false"),
        "C": ("false", "true"), "D": ("true", "true")}


def source_model(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key in {"LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY"}:
            values[key] = value.strip().strip("\"'")
    if set(values) != {"LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY"} or not all(values.values()):
        raise ValueError("既有 .env 缺少三项模型白名单配置")
    parsed = urlsplit(values["LLM_BASE_URL"])
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ValueError("模型端点 URL 无效")
    addresses = [ipaddress.ip_address(result[4][0]) for result in socket.getaddrinfo(
        parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))]
    if parsed.scheme == "http" and any(not (address.is_private or address.is_loopback)
                                       for address in addresses):
        raise ValueError("明文 HTTP 解析到公网地址，停止")
    return values


def write_env(path: Path, values: dict[str, str]) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError("环境变量含换行")
            output.write(f"{key}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-env", type=Path, required=True)
    parser.add_argument("--db-port", type=int, default=15447)
    parser.add_argument("--budget", type=int, default=9000)
    args = parser.parse_args()
    if not 1024 <= args.db_port <= 65535:
        raise ValueError("数据库端口无效")
    if not 2048 < args.budget <= 16384:
        raise ValueError("估算预算必须位于 2049..16384")
    if PRIVATE.exists() and any(path.name.startswith("env-") or path.name == "compose.json"
                                for path in PRIVATE.iterdir()):
        raise SystemExit("本阶段隔离环境已有内容；拒绝覆盖")
    model = source_model(args.source_env)
    old_umask = os.umask(0o077)
    try:
        PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        common = {**model, "TRIAGE_ENV": "test", "EVAL_LUNA_RESPONSES_HIGH": "false",
                  "EVAL_PROMPT_VARIANT": "A", "REPAIR_ENABLED": "false",
                  "REPAIR_SIMULATED": "false", "REPAIR_MCP_SERVER_URL": "",
                  "MCP_SERVER_URL": "http://mock-mcp:8000/mcp",
                  "INCIDENT_MEMORY_ENABLED": "true", "INCIDENT_MEMORY_WRITE_ENABLED": "true",
                  "INCIDENT_MEMORY_MAX_HITS": "2", "INCIDENT_MEMORY_MAX_CANDIDATES": "20",
                  "CONTEXT_WINDOW_ENABLED": "true",
                  "CONTEXT_ESTIMATED_TOTAL_BUDGET": str(args.budget),
                  "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": str(args.db_port),
                  "POSTGRES_USER": "phase34", "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
                  "PHASE34_CASES_PATH": str(ROOT / "scripts/eval_incident_memory_cases/phase34-targeted-v1.json"),
                  "PHASE34_THREAD_MAP": str(PRIVATE / "thread-map.json")}
        (PRIVATE / "thread-map.json").write_text("{}\n")
        for arm, (summary, read) in ARMS.items():
            values = {**common, "POSTGRES_DB": "phase34_" + arm.lower(),
                      "PHASE34_AUDIT_PATH": str(PRIVATE / f"audit-{arm}.jsonl"),
                      "CONTEXT_SUMMARY_ENABLED": summary,
                      "INCIDENT_MEMORY_READ_ENABLED": read,
                      "INCIDENT_MEMORY_PROVENANCE_SECRET": secrets.token_urlsafe(48),
                      "DEMO_API_TOKEN": secrets.token_urlsafe(32)}
            write_env(PRIVATE / f"env-{arm}", values)
        compose = {"services": {"postgres": {
            "image": "pgvector/pgvector:0.8.7-pg18-bookworm",
            "environment": {"POSTGRES_USER": "phase34",
                            "POSTGRES_PASSWORD": common["POSTGRES_PASSWORD"],
                            "POSTGRES_DB": "phase34_a"},
            "ports": [f"127.0.0.1:{args.db_port}:5432"],
            "volumes": ["phase34_pg_data:/var/lib/postgresql"],
            "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U phase34 -d phase34_a"],
                            "interval": "2s", "timeout": "2s", "retries": 30}}},
            "volumes": {"phase34_pg_data": {}}}
        write_env(PRIVATE / "compose.env", {})
        (PRIVATE / "compose.json").write_text(json.dumps(compose, indent=2) + "\n")
        fingerprint = {"model": model["LLM_MODEL"],
                       "endpoint_sha256": hashlib.sha256(model["LLM_BASE_URL"].encode()).hexdigest(),
                       "mode": "Chat Completions by product configuration",
                       "reasoning_effort": "UNKNOWN", "temperature": "UNKNOWN", "seed": "UNKNOWN"}
        (PRIVATE / "model-fingerprint.json").write_text(json.dumps(fingerprint, indent=2) + "\n")
    finally:
        os.umask(old_umask)
    print(json.dumps({"status": "prepared", "model": fingerprint["model"],
                      "endpoint_sha256": fingerprint["endpoint_sha256"]}))


if __name__ == "__main__":
    main()
