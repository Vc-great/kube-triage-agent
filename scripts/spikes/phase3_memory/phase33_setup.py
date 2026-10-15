"""准备仅本机使用的 Phase 3-3 隔离配置；不启动服务或打印密钥。"""

import argparse
import json
import os
import secrets
from pathlib import Path


def source_model(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        if key in {"LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY"}:
            values[key] = value.strip().strip("\"'")
    if not all(values.get(key) for key in ("LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY")):
        raise SystemExit("既有 .env 缺少真实模型配置")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-env", type=Path, required=True)
    parser.add_argument("--db-port", type=int, default=15443)
    args = parser.parse_args()
    if not 1024 <= args.db_port <= 65535:
        raise SystemExit("无效端口")
    directory = Path(".local/phase33").resolve()
    if directory.exists() and any(directory.iterdir()):
        raise SystemExit("Phase 3-3 私有目录已存在内容，拒绝覆盖")
    old_umask = os.umask(0o077)
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        cases = (Path.cwd() / "scripts/eval_incident_memory_cases/phase33-main-v1.json").resolve()
        model = source_model(args.source_env)
        common = {
            **model,
            "TRIAGE_ENV": "test", "EVAL_LUNA_RESPONSES_HIGH": "false",
            "EVAL_PROMPT_VARIANT": "A", "REPAIR_ENABLED": "false",
            "REPAIR_SIMULATED": "false", "REPAIR_MCP_SERVER_URL": "",
            "MCP_SERVER_URL": "http://mock-mcp:8000/mcp",
            "INCIDENT_MEMORY_ENABLED": "true",
            "INCIDENT_MEMORY_WRITE_ENABLED": "false",
            "INCIDENT_MEMORY_PROVENANCE_SECRET": secrets.token_urlsafe(48),
            "DEMO_API_TOKEN": secrets.token_urlsafe(32),
            "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": str(args.db_port),
            "POSTGRES_USER": "phase33", "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
            "PHASE33_CASES_PATH": str(cases),
            "PHASE33_THREAD_MAP": str(directory / "thread-map.json"),
        }
        (directory / "thread-map.json").write_text("{}\n", encoding="utf-8")
        for arm in "ABC":
            values = {**common, "POSTGRES_DB": "phase33_" + arm.lower(),
                      "INCIDENT_MEMORY_READ_ENABLED": "false" if arm == "A" else "true"}
            path = directory / ("env-" + arm)
            with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as out:
                for key, value in values.items():
                    if "\n" in value:
                        raise SystemExit("配置含换行")
                    out.write(f"{key}={value}\n")
        compose = {"services": {"postgres": {
            "image": "pgvector/pgvector:0.8.7-pg18-bookworm",
            "environment": {"POSTGRES_USER": "phase33",
                            "POSTGRES_PASSWORD": common["POSTGRES_PASSWORD"],
                            "POSTGRES_DB": "phase33_a"},
            "ports": [f"127.0.0.1:{args.db_port}:5432"],
            "volumes": ["phase33_pg_data:/var/lib/postgresql"],
            "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U phase33 -d phase33_a"],
                            "interval": "2s", "timeout": "2s", "retries": 30}}},
            "volumes": {"phase33_pg_data": {}}}
        (directory / "compose.json").write_text(json.dumps(compose, indent=2) + "\n")
    finally:
        os.umask(old_umask)
    print("Phase 3-3 隔离配置已准备（密钥未输出）")


if __name__ == "__main__":
    main()
