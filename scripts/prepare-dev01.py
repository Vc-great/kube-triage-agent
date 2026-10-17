#!/usr/bin/env python3
"""生成新部署/开发凭据，复用已授权的模型配置；不打印秘密，不覆盖私有文件。"""

import argparse
import os
import secrets
from pathlib import Path

from eval_phase3a import read_env

ROOT = Path(__file__).resolve().parents[1]


def private_env(path, values):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        for key, value in values.items():
            if any(char in value for char in ("\n", "\r", "'", "\\")):
                raise ValueError("配置值含不支持的字符；私下检查源配置。")
            # Compose treats single-quoted values literally, including $ in secrets.
            output.write(f"{key}='{value}'\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-env", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    directory = ROOT / ".local"
    directory.mkdir(mode=0o700, exist_ok=True)
    remote = directory / "dev01.env"
    local = ROOT / ".env"
    if remote.exists() or local.exists():
        raise SystemExit("私有配置已存在；为避免替换数据库密码，本脚本不覆盖。")
    source = read_env(args.source_env)
    if not source.get("LLM_MODEL") or not source.get("LLM_API_KEY"):
        raise SystemExit("源配置缺少真实模型配置。")
    deployment = read_env(ROOT / ".env.dev01.example")
    development = read_env(ROOT / ".env.example")
    for target in (deployment, development):
        for key in ("LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY"):
            target[key] = source.get(key, "")
    deployment["POSTGRES_PASSWORD"] = secrets.token_urlsafe(32)
    deployment["POSTGRES_DEV_PASSWORD"] = secrets.token_urlsafe(32)
    deployment["DEMO_API_TOKEN"] = secrets.token_urlsafe(32)
    development["POSTGRES_PASSWORD"] = deployment["POSTGRES_DEV_PASSWORD"]
    development["DEMO_API_TOKEN"] = secrets.token_urlsafe(32)
    development["INCIDENT_MEMORY_PROVENANCE_SECRET"] = secrets.token_urlsafe(48)
    # Validate before writing either file.
    for target in (deployment, development):
        if any(any(char in value for char in ("\n", "\r", "'", "\\"))
               for value in target.values()):
            raise SystemExit("配置值含不支持的字符；私下检查源配置。")
    private_env(remote, deployment)
    private_env(local, development)
    print("已生成 .local/dev01.env 与 .env（0600），未输出凭据。")


if __name__ == "__main__":
    main()
