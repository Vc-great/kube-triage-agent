#!/usr/bin/env python3
"""前台运行独立 FakeModel/Mock Skills Demo；Ctrl-C 仅清理本次资源。"""

import argparse
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "pgvector/pgvector:0.8.7-pg18-bookworm"


def environments(api_port, db_port, *, persistence=False):
    # Do not inherit real model keys, tracing, database URLs or proxy settings.
    host = {key: value for key, value in os.environ.items() if key in {
        "PATH", "HOME", "TMPDIR", "USER", "LANG", "PNPM_HOME", "UV_CACHE_DIR",
    }}
    common = {**host, "TRIAGE_ENV": "test", "TRIAGE_MOCK_DATASET": "memory-web",
              "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false",
              "OTEL_SDK_DISABLED": "true", "OTEL_TARGETS": "", "OTEL_CONSOLE_EXPORT": "false"}
    api = {**common, "DEEP_DIAGNOSIS_FAKE_MODEL": "true", "DEEP_DIAGNOSIS_ENABLE_PROVIDER": "false",
           "DEMO_API_TOKEN": "skills-demo-local-only", "AUTH_TYPE": "custom",
           "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": str(db_port),
           "POSTGRES_USER": "skills", "POSTGRES_PASSWORD": "skills-demo-local-only",
           "POSTGRES_DB": "skills", "MCP_SERVER_URL": "http://127.0.0.1:8000/mcp",
           "REDIS_BROKER_ENABLED": "false", "AEGRA_CONFIG": "aegra.phase-skills.json",
           "APP_HISTORY_ENABLED": "false", "APP_EVIDENCE_ENABLED": "false",
           "INCIDENT_MEMORY_ENABLED": "false", "REPAIR_ENABLED": "false",
           "SERVER_URL": f"http://127.0.0.1:{api_port}"}
    web = {**host, "NEXT_PUBLIC_API_URL": f"http://127.0.0.1:{api_port}",
           "NEXT_PUBLIC_ASSISTANT_ID": "deep_diagnosis_skills", "NEXT_TELEMETRY_DISABLED": "1",
           "NEXT_PUBLIC_DEEP_DEMO": "true", "NEXT_PUBLIC_APP_HISTORY_ENABLED": "false"}
    if persistence:
        api.update(APP_HISTORY_ENABLED="true", APP_EVIDENCE_ENABLED="true")
        web["NEXT_PUBLIC_APP_HISTORY_ENABLED"] = "true"
    return common, api, web


def preflight(ports, *, web):
    paths = [ROOT / "server" / ".env"]
    paths += [ROOT / "apps/web" / name for name in
              (".env", ".env.local", ".env.development", ".env.development.local")]
    if any(path.exists() or path.is_symlink() for path in paths):
        raise RuntimeError("请用无 server/Web dotenv 的独立工作树，避免自动加载真实配置")
    for port in ports:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))  # Reject active listeners, allow TIME_WAIT.
            except OSError as exc:
                raise RuntimeError(f"本机端口 {port} 被占用；不停止其他服务") from exc
    if not (ROOT / "server/.venv/bin/aegra").exists():
        raise RuntimeError("先在 server 执行 uv sync --frozen --python 3.13")
    if web and not (ROOT / "apps/web/node_modules").exists():
        raise RuntimeError("先在 apps/web 执行 pnpm install --frozen-lockfile")
    subprocess.run(["docker", "image", "inspect", IMAGE], check=True, stdout=subprocess.DEVNULL)


def main(*, reviewer=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-port", type=int, default=12072 if reviewer else 12075)
    parser.add_argument("--web-port", type=int, default=13072 if reviewer else 13075)
    parser.add_argument("--db-port", type=int, default=15472 if reviewer else 15475)
    parser.add_argument("--no-web", action="store_true")
    parser.add_argument("--persistence", action="store_true",
                        help="显式迁移隔离 PG 并打开现有 History/Evidence 路由与 Web 开关")
    args = parser.parse_args()
    ports = [8000, args.api_port, args.db_port] + ([] if args.no_web else [args.web_port])
    if len(set(ports)) != len(ports) or any(not 1024 <= p <= 65535 for p in ports):
        parser.error("端口须互异且在 1024..65535")
    preflight(ports, web=not args.no_web)
    common, api, web = environments(args.api_port, args.db_port, persistence=args.persistence)
    if reviewer:
        api["AEGRA_CONFIG"] = "aegra.phase-review.json"
        common["TRIAGE_MOCK_DATASET"] = api["TRIAGE_MOCK_DATASET"] = "review-web"
        web["NEXT_PUBLIC_ASSISTANT_ID"] = "deep_diagnosis_review"
    name = "kta-review-" if reviewer else "kta-skills-"
    name = name + uuid4().hex[:12]
    processes = []
    logs = Path(tempfile.mkdtemp(prefix="kta-skills-logs-"))
    handles = []

    def launch(label, command, cwd, env):
        handle = (logs / f"{label}.log").open("w")
        handles.append(handle)
        processes.append(subprocess.Popen(command, cwd=cwd, env=env,
                                          stdout=handle, stderr=subprocess.STDOUT,
                                          start_new_session=True))

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        subprocess.run(["docker", "run", "--detach", "--rm", "--pull=never", "--name", name,
            "--label", "ao.session=" + os.getenv("AO_SESSION_ID", name),
            "-p", f"127.0.0.1:{args.db_port}:5432", "-e", "POSTGRES_USER=skills",
            "-e", "POSTGRES_PASSWORD=skills-demo-local-only", "-e", "POSTGRES_DB=skills", IMAGE],
            check=True, stdout=subprocess.DEVNULL)
        for _ in range(60):
            # The image's temporary init server accepts Unix sockets before
            # the final TCP server is ready for the Host migration/API.
            ready = subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1",
                                    "-U", "skills"],
                                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ready.returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError("独立 PostgreSQL 启动超时")
        python = str(ROOT / "server/.venv/bin/python")
        if args.persistence:
            subprocess.run([python, "-m", "kube_triage.app_storage"], cwd=ROOT / "server",
                           env=api, check=True)
        launch("mock", [python, "-m", "kube_triage.mock_mcp"], ROOT / "server",
               {**common, "MOCK_MCP_HOST": "127.0.0.1"})
        launch("api", [str(ROOT / "server/.venv/bin/aegra"), "serve", "--config",
               api["AEGRA_CONFIG"], "--host", "127.0.0.1", "--port", str(args.api_port)],
               ROOT / "server", api)
        for _ in range(120):
            if any(p.poll() is not None for p in processes):
                raise RuntimeError(f"服务提前退出，日志：{logs}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.api_port}/health", timeout=1):
                    break
            except OSError:
                time.sleep(.5)
        else:
            raise RuntimeError(f"API 启动超时，日志：{logs}")
        if not args.no_web:
            launch("web", ["pnpm", "dev", "--hostname", "127.0.0.1", "--port", str(args.web_port)],
                   ROOT / "apps/web", web)
        print(f"{'Reviewer' if reviewer else 'Skills'} Fake/Mock API: http://127.0.0.1:{args.api_port}", flush=True)
        if not args.no_web:
            print(f"Web: http://127.0.0.1:{args.web_port}；API Key: skills-demo-local-only", flush=True)
        print(f"仅新实验 Thread；不导入旧 pin checkpoint。日志：{logs}；Ctrl-C 清理本次资源。", flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(1)
        raise RuntimeError(f"子进程退出，日志：{logs}")
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
        for handle in handles:
            handle.close()
        # A unique name belongs only to this invocation; no shared volumes/services.
        subprocess.run(["docker", "rm", "-f", "-v", name], check=False, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
