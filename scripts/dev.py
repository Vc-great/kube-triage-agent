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
import stat
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
STOP_REQUESTED = False
PRIVATE_KEYS = frozenset({"POSTGRES_PASSWORD", "DEMO_API_TOKEN", "LLM_MODEL",
                          "LLM_BASE_URL", "LLM_API_KEY",
                          "INCIDENT_MEMORY_PROVENANCE_SECRET", "DEV_SSH_HOST",
                          "DEV_REMOTE_API_URL"})
COMMON_HOST_KEYS = frozenset({"PATH", "HOME", "TMPDIR", "USER", "LOGNAME", "SHELL",
                              "LANG", "XDG_CACHE_HOME", "UV_CACHE_DIR",
                              "UV_PYTHON_INSTALL_DIR", "PNPM_HOME", "COREPACK_HOME"})
API_HOST_KEYS = frozenset({"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                           "http_proxy", "https_proxy", "all_proxy", "no_proxy",
                           "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"})
PROFILES = {
    "real": {"mock": False, "read": True, "write": True,
             "window": True, "summary": True},
    "mock": {"mock": True, "read": False, "write": False,
             "window": False, "summary": False},
    "memory-write": {"mock": True, "read": False, "write": True,
                     "window": False, "summary": False},
    "memory-read": {"mock": True, "read": True, "write": False,
                    "window": False, "summary": False},
    "memory": {"mock": True, "read": True, "write": True,
               "window": False, "summary": False},
    "mock-window": {"mock": True, "read": False, "write": False,
                    "window": True, "summary": False},
    "mock-summary": {"mock": True, "read": False, "write": False,
                     "window": True, "summary": True},
}


def read_env():
    if ENV_FILE.is_symlink() or not ENV_FILE.is_file():
        raise RuntimeError("缺少 .local/dev.env；按 .env.development.example 配置。")
    if stat.S_IMODE(ENV_FILE.stat().st_mode) != 0o600:
        raise RuntimeError("请先 chmod 600 .local/dev.env。")
    values = {}
    for number, line in enumerate(ENV_FILE.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError(f".local/dev.env 第 {number} 行格式错误。")
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in PRIVATE_KEYS:
            raise RuntimeError(f".local/dev.env 不允许配置 {key}；场景参数由启动命令决定。")
        if key in values:
            raise RuntimeError(f".local/dev.env 中 {key} 重复。")
        values[key] = value.strip().strip("\"'")
    return values


def safe_host_env(host_env=None, *, api=False, ssh=False):
    source = os.environ if host_env is None else host_env
    allowed = COMMON_HOST_KEYS | (API_HOST_KEYS if api else frozenset())
    if ssh:
        allowed |= {"SSH_AUTH_SOCK"}
    return {key: value for key, value in source.items()
            if key in allowed or key.startswith("LC_")}


def profile_summary(mode):
    if mode == "web":
        return {"reader": "dev01", "memory": "remote", "context": "remote",
                "repair": "remote"}
    profile = PROFILES[mode]
    memory = ("read-write" if profile["read"] and profile["write"] else
              "read" if profile["read"] else "write" if profile["write"] else "off")
    context = "summary" if profile["summary"] else "window" if profile["window"] else "off"
    return {"reader": "mock" if profile["mock"] else "real",
            "memory": memory, "context": context,
            "repair": "real" if mode == "real" else "off"}


def required_ports(mode):
    if mode == "web":
        return (13000,)
    reader_port = 8000 if PROFILES[mode]["mock"] else 18080
    return ((13000, 12026, 15432, 16379, reader_port, 18081) if mode == "real"
            else (13000, 12026, 15432, 16379, reader_port))


def child_environments(mode, values, host_env=None):
    """Build isolated process environments; the private file cannot choose a profile."""
    common = safe_host_env(host_env)
    web_target = (values.get("DEV_REMOTE_API_URL") or "http://192.168.31.110:12026")
    if mode != "web":
        web_target = "http://localhost:12026"
    web_env = {**common, "NEXT_PUBLIC_API_URL": web_target,
               "NEXT_PUBLIC_ASSISTANT_ID": "agent", "NEXT_TELEMETRY_DISABLED": "1"}
    if mode == "web":
        return {"web": web_env}
    profile = PROFILES[mode]
    required = ("POSTGRES_PASSWORD", "DEMO_API_TOKEN", "LLM_MODEL", "LLM_API_KEY")
    if any(not values.get(key) for key in required):
        raise RuntimeError("开发数据库、API Token 和真实模型配置必须齐全。")
    memory_on = profile["read"] or profile["write"]
    if memory_on and not values.get("INCIDENT_MEMORY_PROVENANCE_SECRET"):
        raise RuntimeError("Memory 场景缺少独立 HMAC 密钥。")
    api_env = {**safe_host_env(host_env, api=True),
               **{key: values[key] for key in required},
               "LLM_BASE_URL": values.get("LLM_BASE_URL", ""),
               "AUTH_TYPE": "custom", "TRIAGE_ENV": "test" if profile["mock"] else "development",
               "REPAIR_ENABLED": "true" if mode == "real" else "false",
               "REPAIR_SIMULATED": "false", "LLM_ENABLED": "true",
               "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "15432",
               "POSTGRES_USER": "kube_triage_agent_dev", "POSTGRES_DB": "kube_triage_agent_dev",
               "REDIS_BROKER_ENABLED": "true", "REDIS_URL": "redis://127.0.0.1:16379/0",
               "MCP_SERVER_URL": ("http://127.0.0.1:8000/mcp" if profile["mock"]
                                  else "http://127.0.0.1:18080/mcp"),
               "SERVER_URL": "http://localhost:12026", "AEGRA_CONFIG": "aegra.json",
               "INCIDENT_MEMORY_ENABLED": str(memory_on).lower(),
               "INCIDENT_MEMORY_READ_ENABLED": str(profile["read"]).lower(),
               "INCIDENT_MEMORY_WRITE_ENABLED": str(profile["write"]).lower(),
               "CONTEXT_WINDOW_ENABLED": str(profile["window"]).lower(),
               "CONTEXT_SUMMARY_ENABLED": str(profile["summary"]).lower(),
               "CONTEXT_ESTIMATED_TOTAL_BUDGET": "6500" if profile["window"] else "16384"}
    if memory_on:
        api_env["INCIDENT_MEMORY_PROVENANCE_SECRET"] = values[
            "INCIDENT_MEMORY_PROVENANCE_SECRET"]
    if mode == "real":
        api_env["REPAIR_MCP_SERVER_URL"] = "http://127.0.0.1:18081/mcp"
        api_env["REPAIR_KUBECONFIG"] = str(ROOT / ".local" / "repair-kubeconfig")
    result = {"web": web_env, "api": api_env,
              "tunnel": safe_host_env(host_env, ssh=True)}
    if profile["mock"]:
        api_env.update(TRIAGE_MOCK_DATASET="memory-web", EVAL_PROMPT_VARIANT="A",
                       EVAL_LUNA_RESPONSES_HIGH=("true" if values["LLM_MODEL"] == "gpt-6-luna"
                                                 else "false"))
        result["mock"] = {**common, "TRIAGE_ENV": "test",
                          "TRIAGE_MOCK_DATASET": "memory-web", "MOCK_MCP_HOST": "127.0.0.1"}
    return result


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
    state = {"pid": os.getpid(), "token": token, "mode": mode, "status": "starting",
             "scenario": profile_summary(mode)}
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
            processes = child_environments(mode, env)
            mock = mode != "web" and PROFILES[mode]["mock"]
            busy = [str(port) for port in required_ports(mode) if occupied(port)]
            if busy:
                raise RuntimeError("端口已被其他进程占用：" + ", ".join(busy))
            if mode != "web":
                host = env.get("DEV_SSH_HOST", "dev01")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", host):
                    raise RuntimeError("DEV_SSH_HOST 必须为 SSH host alias。")
                tunnel_command = ["ssh", "-N", "-o", "BatchMode=yes", "-o",
                       "StrictHostKeyChecking=yes", "-o", "ExitOnForwardFailure=yes", "-o",
                       "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o",
                       "ServerAliveCountMax=3", "-L", "127.0.0.1:15432:127.0.0.1:15432",
                       "-L", "127.0.0.1:16379:127.0.0.1:16379"]
                if not mock:
                    tunnel_command += ["-L", "127.0.0.1:18080:127.0.0.1:18080"]
                    tunnel_command += ["-L", "127.0.0.1:18081:127.0.0.1:18081"]
                launch("tunnel", tunnel_command + [host], ROOT, processes["tunnel"])
                tunnel_ports = (15432, 16379) if mock else (15432, 16379, 18080, 18081)
                wait_for(lambda: all(occupied(p) for p in tunnel_ports), children, 20)
                api_env = processes["api"]
                if mock:
                    launch("mock", ["uv", "run", "--frozen", "--offline", "--no-sync",
                                    "python", "-m", "kube_triage.mock_mcp"],
                           ROOT / "server", processes["mock"])
                    wait_for(lambda: occupied(8000), children, 20)
                with open(DIRECTORY / "preflight.log", "w") as log:
                    subprocess.run(["uv", "run", "--frozen", "--offline", "--no-sync", "python",
                                    str(ROOT / "scripts" / "dev_preflight.py"), mode],
                                   cwd=ROOT / "server", env=api_env,
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
            launch("web", ["pnpm", "dev", "--hostname", "127.0.0.1", "--port", "13000"],
                   ROOT / "apps" / "web", processes["web"])
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
    parser.add_argument("mode", nargs="?", choices=("web", *PROFILES))
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
                          "scenario": (state or {}).get("scenario") or (
                              profile_summary(state["mode"]) if state and state.get("mode") in
                              (*PROFILES, "web") else None),
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
            parser.error("start requires a scenario")
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
                    print(f"API: {state['api_url']}；场景: {args.mode} "
                          f"{json.dumps(state['scenario'], ensure_ascii=False)}；"
                          "日志: .local/dev/；停止: make dev-stop")
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
