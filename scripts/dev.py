#!/usr/bin/env python3
"""Mac 原生开发入口；只管理自己创建的进程，不操作 Docker 或远端应用。"""

import argparse
import fcntl
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / ".local" / "dev"
STATE = DIRECTORY / "state.json"
ENV_FILE = ROOT / ".local" / "dev.env"
SCRIPT = Path(__file__).resolve()
PORTS = (13000, 12026, 15432, 16379, 18080)
STOP_REQUESTED = False


def read_env():
    if not ENV_FILE.is_file():
        raise RuntimeError("缺少 .local/dev.env；按 .env.development.example 配置。")
    if ENV_FILE.stat().st_mode & 0o077:
        raise RuntimeError("请先 chmod 600 .local/dev.env。")
    values = {}
    for line in ENV_FILE.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def alive(state):
    """Verify command + random identity before signaling a potentially reused PID."""
    if not state or not isinstance(state.get("pid"), int) or not state.get("token"):
        return False
    result = subprocess.run(["ps", "-p", str(state["pid"]), "-o", "args="],
                            capture_output=True, text=True, check=False)
    args = result.stdout.split()
    return str(SCRIPT) in args and "supervise" in args and state["token"] in args


def state_read():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return None


def state_write(state):
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state))
    temporary.chmod(0o600)
    temporary.replace(STATE)


def occupied(port):
    with socket.socket() as connection:
        connection.settimeout(0.3)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def wait_for(check, children, timeout=120):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if STOP_REQUESTED:
            raise InterruptedError("开发服务停止。")
        if any(child.poll() is not None for child in children):
            raise RuntimeError("开发子进程退出；检查 .local/dev/ 中的私有日志。")
        try:
            if check():
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError("开发服务就绪超时；检查 .local/dev/ 中的私有日志。")


def http_ready(url):
    with urllib.request.urlopen(url, timeout=2) as response:
        return response.status == 200


def api_ready(env):
    request = urllib.request.Request(
        "http://127.0.0.1:12026/assistants/search", data=b'{"limit":1}',
        headers={"X-Api-Key": env["DEMO_API_TOKEN"], "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=2) as response:
        return response.status == 200


def supervise(mode, token):
    children = []
    state = {"pid": os.getpid(), "token": token, "mode": mode, "status": "starting"}
    published = False

    def stop_signal(_number, _frame):
        global STOP_REQUESTED
        STOP_REQUESTED = True

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)

    def launch(name, command, cwd, env):
        with open(DIRECTORY / f"{name}.log", "w") as log:
            os.chmod(log.name, 0o600)
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        children.append(process)
        return process

    try:
        with open(DIRECTORY / "lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            old = state_read()
            if alive(old):
                raise RuntimeError("已有开发进程；先执行 make dev-stop。")
            state_write(state)
            published = True
            env = read_env()
            required_ports = PORTS if mode == "full" else (13000,)
            busy = [str(port) for port in required_ports if occupied(port)]
            if busy:
                raise RuntimeError("端口已被其他进程占用：" + ", ".join(busy))
            # Do not leak model/database keys into the frontend environment.
            base_env = {k: v for k, v in os.environ.items()
                        if not k.startswith(("LLM_", "POSTGRES_", "REDIS_", "NEXT_PUBLIC_"))
                        and k not in {"DATABASE_URL", "DEMO_API_TOKEN", "LANGSMITH_API_KEY"}}
            if mode == "full":
                required = ("POSTGRES_PASSWORD", "DEMO_API_TOKEN", "LLM_MODEL", "LLM_API_KEY")
                if any(not env.get(key) for key in required):
                    raise RuntimeError("开发数据库、API Token 和真实模型配置必须齐全。")
                if (env.get("POSTGRES_DB") != "kube_triage_agent_dev"
                        or env.get("POSTGRES_USER") != "kube_triage_agent_dev"):
                    raise RuntimeError("开发入口只能使用 kube_triage_agent_dev 数据库和账号。")
                host = env.get("DEV_SSH_HOST", "dev01")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", host):
                    raise RuntimeError("DEV_SSH_HOST 必须为 SSH host alias。")
                launch("tunnel", ["ssh", "-N", "-o", "BatchMode=yes", "-o",
                       "StrictHostKeyChecking=yes", "-o", "ExitOnForwardFailure=yes", "-o",
                       "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o",
                       "ServerAliveCountMax=3", "-L", "127.0.0.1:15432:127.0.0.1:15432",
                       "-L", "127.0.0.1:16379:127.0.0.1:16379", "-L",
                       "127.0.0.1:18080:127.0.0.1:18080", host], ROOT, base_env)
                wait_for(lambda: all(occupied(p) for p in (15432, 16379, 18080)), children, 20)
                api_env = {**base_env, **env, "AUTH_TYPE": "custom",
                           "TRIAGE_ENV": "development", "REPAIR_ENABLED": "false",
                           "REPAIR_SIMULATED": "false", "LLM_ENABLED": "true",
                           "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "15432",
                           "REDIS_BROKER_ENABLED": "true", "REDIS_URL": "redis://127.0.0.1:16379/0",
                           "MCP_SERVER_URL": "http://127.0.0.1:18080/mcp",
                           "SERVER_URL": "http://localhost:12026", "AEGRA_CONFIG": "aegra.json"}
                preflight = (
                    "import asyncio,os,psycopg,redis; "
                    "from kube_triage.config import validate_service; "
                    "from kube_triage.mcp_client import _allowed_tools; validate_service(); "
                    "c=psycopg.connect(host=os.environ['POSTGRES_HOST'],port=15432,"
                    "dbname=os.environ['POSTGRES_DB'],user=os.environ['POSTGRES_USER'],"
                    "password=os.environ['POSTGRES_PASSWORD'],connect_timeout=5); "
                    "c.execute('SELECT 1'); c.close(); "
                    "assert redis.Redis.from_url(os.environ['REDIS_URL'],"
                    "socket_connect_timeout=5,socket_timeout=5).ping(); "
                    "asyncio.run(asyncio.wait_for(_allowed_tools(),8))"
                )
                with open(DIRECTORY / "preflight.log", "w") as log:
                    subprocess.run(["uv", "run", "--frozen", "--offline", "--no-sync", "python",
                                    "-c", preflight], cwd=ROOT / "server", env=api_env,
                                   check=True, stdout=log, stderr=log)
                launch("api", ["uv", "run", "--frozen", "--offline", "--no-sync", "aegra",
                       "serve", "--host", "127.0.0.1", "--port", "12026"], ROOT / "server", api_env)
                wait_for(lambda: api_ready(api_env), children)
                target = "http://localhost:12026"
            else:
                target = env.get("DEV_REMOTE_API_URL", "http://192.168.31.110:12026")
                if target != "http://192.168.31.110:12026":
                    raise RuntimeError("dev-web 目标必须为 dev01 API。")
                wait_for(lambda: http_ready(target + "/health"), children, 15)
            web_env = {**base_env, "NEXT_PUBLIC_API_URL": target,
                       "NEXT_PUBLIC_ASSISTANT_ID": "agent", "NEXT_TELEMETRY_DISABLED": "1"}
            launch("web", ["pnpm", "dev", "--hostname", "127.0.0.1", "--port", "13000"],
                   ROOT / "apps" / "web", web_env)
            wait_for(lambda: http_ready("http://127.0.0.1:13000"), children)
            state.update(status="ready", api_url=target)
            state_write(state)
            while not STOP_REQUESTED:
                if any(child.poll() is not None for child in children):
                    raise RuntimeError("开发进程或 SSH 隧道退出；服务已停止，无 Mock 回退。")
                time.sleep(0.5)
    except InterruptedError:
        state.update(status="stopped")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        # Only our own actionable messages; subprocess exceptions must not echo environments.
        state.update(status="failed", error=str(exc) if isinstance(exc, RuntimeError)
                     else f"开发启动失败（{type(exc).__name__}）；检查私有日志。")
        if published:
            state_write(state)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        if published and state.get("status") != "failed":
            state.update(status="stopped")
            state_write(state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status", "supervise"))
    parser.add_argument("mode", nargs="?", choices=("web", "full"))
    parser.add_argument("token", nargs="?")
    args = parser.parse_args()
    os.umask(0o077)
    DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    DIRECTORY.chmod(0o700)
    if args.action == "supervise":
        if not args.mode or not args.token:
            parser.error("supervise requires mode and identity")
        supervise(args.mode, args.token)
        return
    state = state_read()
    if args.action == "status":
        print(json.dumps({"running": alive(state), "mode": (state or {}).get("mode"),
                          "status": (state or {}).get("status"),
                          "api_url": (state or {}).get("api_url")}, ensure_ascii=False))
    elif args.action == "stop":
        if alive(state):
            os.kill(state["pid"], signal.SIGTERM)
            for _ in range(80):
                if not alive(state):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("停止超时；检查私有日志，不会强杀未确认的进程。")
        print("本入口的开发服务已停止；dev01 不受影响。")
    else:
        if not args.mode:
            parser.error("start requires web or full")
        if alive(state):
            raise RuntimeError("开发服务已运行；切换前先执行 make dev-stop。")
        token = secrets.token_hex(16)
        with open(DIRECTORY / "supervisor.log", "w") as log:
            process = subprocess.Popen([sys.executable, str(SCRIPT), "supervise", args.mode, token],
                                       cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
        for _ in range(300):
            state = state_read()
            if state and state.get("token") == token:
                if state["status"] == "ready":
                    print(f"Web: http://localhost:13000/?apiUrl={state['api_url']}")
                    print(f"API: {state['api_url']}；日志: .local/dev/；停止: make dev-stop")
                    return
                if state["status"] == "failed":
                    raise RuntimeError(state["error"])
            if process.poll() is not None:
                raise RuntimeError("开发 supervisor 退出；检查 .local/dev/supervisor.log。")
            time.sleep(0.5)
        if alive(state):
            os.kill(process.pid, signal.SIGTERM)
        raise RuntimeError("启动超时，已请求清理本次开发进程。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
