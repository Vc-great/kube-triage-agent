"""把 Pilot 凭据和种子归档，给修复后正式批次派生新库与新密钥。"""

import argparse
import os
import secrets
import shutil
from pathlib import Path

PRIVATE = Path(".local/phase34")


def write_env(path: Path, values: dict[str, str]) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError("环境变量含换行")
            output.write(f"{key}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", choices=["formal-v1", "formal-v2"], required=True)
    args = parser.parse_args()
    archive = PRIVATE / ("config-pilot-v2" if args.batch == "formal-v1"
                         else "config-formal-v1-invalid")
    if archive.exists():
        raise SystemExit("Pilot 配置已归档，拒绝二次轮换")
    archive.mkdir(mode=0o700)
    for arm in "ABCD":
        path = PRIVATE / f"env-{arm}"
        values = dict(line.split("=", 1) for line in path.read_text().splitlines()
                      if "=" in line)
        shutil.move(path, archive / path.name)
        seed = PRIVATE / f"env-{arm}-seed"
        if seed.exists():
            shutil.move(seed, archive / seed.name)
        manifest = PRIVATE / f"memory-seed-{arm}.json"
        if manifest.exists():
            shutil.move(manifest, archive / manifest.name)
        database_prefix = "phase34_formal" if args.batch == "formal-v1" else "phase34_formal2"
        values.update(POSTGRES_DB=f"{database_prefix}_{arm.lower()}",
                      DEMO_API_TOKEN=secrets.token_urlsafe(32),
                      INCIDENT_MEMORY_PROVENANCE_SECRET=secrets.token_urlsafe(48))
        write_env(path, values)
        seed_values = {**values, "CONTEXT_SUMMARY_ENABLED": "false",
                       "INCIDENT_MEMORY_READ_ENABLED": "false"}
        write_env(seed, seed_values)
    print(f"{args.batch} 四组新数据库/密钥配置已派生；上一批配置已私有归档")


if __name__ == "__main__":
    main()
