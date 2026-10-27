"""Issue #91 Phase A: isolated real-model Aegra + synthetic MCP + Cloud reads."""

import argparse
import base64
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import dev
from eval_issue12 import inspect as inspect_evidence
from eval_phase3a import api, message_type, private_directory, write_private
from obs_lab_verify import history_matches, verify_cloud

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "server/.venv/bin/python"
CASES = {"S01": "sample-e", "S02": "sample-a", "S03": "sample-c"}
# Same explicit Provider boundary as the existing native deep-demo profile.
APPROVED_PROVIDER_URL = "http://192.168.31.110:8317/v1"


def utc():
    return datetime.now(UTC).isoformat()


def validate_provider(url):
    if url.rstrip("/") != APPROVED_PROVIDER_URL:
        raise RuntimeError("BLOCKED: Provider 不匹配项目已授权 endpoint；拒绝出站")


def configuration(path):
    dev.ENV_FILE = path
    values = dev.read_env()
    cloud = dev.read_langfuse_env(path)
    if any(not values.get(k) for k in ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL")):
        raise RuntimeError("BLOCKED: 缺少真实模型配置")
    validate_provider(values["LLM_BASE_URL"])
    if not PYTHON.is_file() or (ROOT / "server/.env").exists():
        raise RuntimeError("BLOCKED: 需要锁定的 server/.venv 且不能有 server/.env")
    return values, cloud


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def run_deadline(seconds):
    """Bound the whole SSE operation, including a server that only sends keepalives."""
    def expired(_signum, _frame):
        raise RuntimeError("STOP: Run 总时间预算耗尽")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def environments(values, cloud, ports, batch, tracing=True):
    common = dev.safe_host_env(api=True)
    environment = {**common, "TRIAGE_ENV": "test", "REPAIR_ENABLED": "false",
                   "REPAIR_SIMULATED": "false", "LLM_ENABLED": "true",
                   **{key: values[key] for key in ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL")},
                   "OBS_LAB_ENTRY": "true", "AUTH_TYPE": "custom", "DEMO_API_TOKEN": secrets.token_hex(32),
                   "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": str(ports["pg"]),
                   "POSTGRES_USER": "obs_lab", "POSTGRES_DB": "obs_lab",
                   "POSTGRES_PASSWORD": secrets.token_hex(24),
                   "REDIS_BROKER_ENABLED": "true",
                   "REDIS_URL": f"redis://127.0.0.1:{ports['redis']}/0",
                   "WORKER_QUEUE_KEY": f"{batch}:jobs", "REDIS_CHANNEL_PREFIX": f"{batch}:run:",
                   "BG_JOB_MAX_RETRIES": "0", "BG_JOB_TIMEOUT_SECS": "180",
                   "MCP_SERVER_URL": "http://127.0.0.1:8000/mcp",
                   "TRIAGE_MOCK_DATASET": "issue12-blind-v1", "AEGRA_CONFIG": "aegra.json",
                   "CONTEXT_WINDOW_ENABLED": "false", "CONTEXT_SUMMARY_ENABLED": "false",
                   "INCIDENT_MEMORY_ENABLED": "false", "INCIDENT_MEMORY_READ_ENABLED": "false",
                   "INCIDENT_MEMORY_WRITE_ENABLED": "false", "APP_HISTORY_ENABLED": "false",
                   "APP_EVIDENCE_ENABLED": "false", "EVAL_PROMPT_VARIANT": "A",
                   "EVAL_LUNA_RESPONSES_HIGH": "false", "OTEL_CONSOLE_EXPORT": "false",
                   "OTEL_TARGETS": "LANGFUSE" if tracing else "",
                   "OTEL_SERVICE_NAME": "kube-triage-obs-lab",
                   "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false",
                   "HTTP_PROXY": "http://127.0.0.1:33210",
                   "HTTPS_PROXY": "http://127.0.0.1:33210",
                   "NO_PROXY": "localhost,127.0.0.1,::1,192.168.31.110",
                   "no_proxy": "localhost,127.0.0.1,::1,192.168.31.110",
                   "SERVER_URL": f"http://127.0.0.1:{ports['api']}"}
    if tracing:
        environment.update(cloud)
    mock = {**dev.safe_host_env(), "TRIAGE_ENV": "test", "TRIAGE_MOCK_DATASET": "issue12-blind-v1",
            "MOCK_MCP_HOST": "127.0.0.1"}
    return environment, mock


def wait_ready(check, children, timeout=120):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if any(child.poll() is not None for child in children):
            raise RuntimeError("BLOCKED: 隔离子进程退出；检查私有日志")
        try:
            if check():
                return
        except (OSError, ValueError):
            time.sleep(0.1)
        time.sleep(0.5)
    raise RuntimeError("BLOCKED: 隔离服务就绪超时")


@contextmanager
def isolated_processes(values, cloud, out, tracing=True, fault_endpoint=None):
    if dev.occupied(8000):
        raise RuntimeError("BLOCKED: Mock 专用端口 8000 已被占用，不操作既有服务")
    ports = {name: free_port() for name in ("pg", "redis", "api")}
    env, mock = environments(values, cloud, ports, out.name, tracing)
    if fault_endpoint:
        env.update(LANGFUSE_BASE_URL=fault_endpoint, LANGFUSE_PUBLIC_KEY="pk-lf-lab-only",
                   LANGFUSE_SECRET_KEY="sk-lf-lab-only")
    children, containers = [], []
    session = os.environ.get("AO_SESSION_ID")
    if not session:
        raise RuntimeError("BLOCKED: 需要 AO_SESSION_ID 资源归属")

    def docker(*args):
        result = subprocess.run(["docker", *args], env={**dev.safe_host_env(),
                                "POSTGRES_PASSWORD": env["POSTGRES_PASSWORD"]},
                                capture_output=True, text=True, timeout=30, check=False)
        if result.returncode:
            raise RuntimeError("BLOCKED: Docker 操作失败；未输出敏感诊断")
        return result.stdout.strip()

    def launch(name, args, environment):
        with open(out / f"{name}.log", "w") as log:
            children.append(subprocess.Popen(args, cwd=ROOT / "server", env=environment,
                            stdout=log, stderr=subprocess.STDOUT, start_new_session=True))

    try:
        for name, image, internal, extra in (
            ("pg", "pgvector/pgvector:0.8.7-pg18-bookworm", 5432,
             ["--tmpfs", "/var/lib/postgresql", "-e", "POSTGRES_USER=obs_lab",
              "-e", "POSTGRES_DB=obs_lab", "-e", "POSTGRES_PASSWORD"]),
            ("redis", "redis:8.4.7-alpine", 6379, []),
        ):
            identifier = docker("run", "--pull=never", "--rm", "-d",
                                "--label", f"ao.session={session}",
                                "--label", f"obs-lab.batch={out.name}",
                                "-p", f"127.0.0.1:{ports[name]}:{internal}", *extra, image)
            containers.append(identifier)
        wait_ready(lambda: subprocess.run(["docker", "exec", containers[0], "pg_isready",
                   "-U", "obs_lab"], capture_output=True, check=False).returncode == 0, children)
        launch("mock", [str(PYTHON), "-m", "kube_triage.mock_mcp"], mock)
        wait_ready(lambda: dev.occupied(8000), children, 20)
        launch("api", [str(PYTHON), str(ROOT / "scripts/obs_lab_api.py"), str(ports["api"])], env)
        base = f"http://127.0.0.1:{ports['api']}"
        wait_ready(lambda: bool(api(base, env["DEMO_API_TOKEN"], "/assistants/search",
                                   "POST", {"limit": 10})), children)
        write_private(out / "isolation.json", {"ports": ports, "containers": containers,
                      "session": session, "repair": False, "memory": False,
                      "reader": "isolated-mock", "tracing": tracing})
        yield base, env["DEMO_API_TOKEN"]
    finally:
        for child in reversed(children):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        for identifier in reversed(containers):
            docker("rm", "-f", identifier)



@contextmanager
def rejecting_exporter(out):
    counts = {"requests": 0, "http_status": 403}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 8 * 1024 * 1024:
                self.close_connection = True
                self.send_error(413)
                return
            self.rfile.read(length)  # Discard synthetic Span data; never record headers/body.
            counts["requests"] += 1
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"Synthetic lab export refusal")

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        write_private(out / "export-fault.json", counts)


@contextmanager
def isolated(values, cloud, out, export_mode="cloud"):
    if export_mode == "failure":
        with (rejecting_exporter(out) as endpoint,
              isolated_processes(values, cloud, out, fault_endpoint=endpoint) as connection):
            yield connection
    else:
        with isolated_processes(values, cloud, out, tracing=export_mode == "cloud") as connection:
            yield connection


def lifecycle_result(out):
    path = out / "api.log"
    for line in reversed(path.read_text().splitlines() if path.exists() else []):
        if line.startswith('{"event": "obs_lab_otel_flush"'):
            return json.loads(line)
    return {"completed": False, "reason": "flush_record_missing"}


def inspect_run(state, runs, events):
    messages = state.get("values", {}).get("messages", [])
    calls = [call for msg in messages if message_type(msg) in {"ai", "assistant"}
             for call in msg.get("tool_calls", [])]
    tools = [msg for msg in messages if message_type(msg) == "tool"]
    models = [msg.get("response_metadata", {}).get("model_name") or
              msg.get("response_metadata", {}).get("model") for msg in messages
              if message_type(msg) in {"ai", "assistant"}]
    models = [model for model in models if model]
    paired = (bool(calls) and all(call.get("id") for call in calls)
              and Counter(call["id"] for call in calls)
              == Counter(msg.get("tool_call_id") for msg in tools)
              and len({call["id"] for call in calls}) == len(calls))
    last = runs[0] if len(runs) == 1 else {}
    return {"run_id": last.get("run_id"), "protocol_status": last.get("status", "unknown"),
            "models_observed": models, "tool_calls": calls, "tool_pairs_valid": paired,
            "model_decisions": len(models), "tool_count": len(calls),
            "sse_error": any(event.get("event") == "error" for event in events)}


def execute(base, token, scenario, batch, timeout, row, evidence_path):
    thread = api(base, token, "/threads", "POST", {})["thread_id"]
    row["thread_id"] = thread
    raw_evidence = {"thread_id": thread}
    write_private(evidence_path, raw_evidence)
    payload = {"assistant_id": "agent", "stream_mode": ["values"],
               "metadata": {"environment": "obs-lab", "batch_id": batch,
                            "scenario_id": scenario, "case_version": "issue12-blind-v1-phase-a2"},
               "input": {"messages": [{"role": "human", "content":
                   f"请只读诊断 kube-triage-demo 中 {CASES[scenario]}，先获取当前证据再回答，"
                   "说明证据支持的结论和不确定性。不要执行修复。"}]}}
    request = urllib.request.Request(base + f"/threads/{thread}/runs/stream",
        data=json.dumps(payload).encode(), headers={"X-Api-Key": token,
        "Content-Type": "application/json", "Accept": "text/event-stream"})
    events = []
    start = time.monotonic()
    try:
        with run_deadline(timeout), urllib.request.urlopen(request, timeout=timeout) as response:
            kind, lines = "", []
            for raw in response:
                if time.monotonic() - start > timeout:
                    raise RuntimeError("STOP: Run 总时间预算耗尽")
                line = raw.decode().rstrip("\r\n")
                if line.startswith("event:"):
                    kind = line[6:].strip()
                elif line.startswith("data:"):
                    lines.append(line[5:].strip())
                elif not line and (kind or lines):
                    events.append({"event": kind, "data": "\n".join(lines)})
                    kind, lines = "", []
    finally:
        raw_evidence["events"] = events
        for key in ("state", "history", "runs"):
            try:
                raw_evidence[key] = api(base, token, f"/threads/{thread}/{key}")
            except (OSError, ValueError):
                raw_evidence[key] = None
        write_private(evidence_path, raw_evidence)
        row.update(inspect_run(raw_evidence.get("state") or {},
                               raw_evidence.get("runs") or [], events))
        row["history_tool_pairs_valid"] = history_matches(
            raw_evidence.get("state") or {}, raw_evidence.get("history"))
        cases = json.loads((ROOT / "eval/issue12/blind-v1.json").read_text())["cases"]
        case = next(c for c in cases if c["target_pod"] == CASES[scenario])
        details = inspect_evidence((raw_evidence.get("state") or {}).get("values", {}).get("messages", []), case)
        row["reader_evidence"] = {k: details[k] for k in (
            "evidence_sufficient", "evidence_keys", "tool_selection_compliant",
            "tool_failure_count", "event_uid_mismatch", "budget_exhausted",
            "model_execution_failure", "final_answer_present")}
    return row


class Cloud:
    def __init__(self, credentials):
        self.credentials = credentials

    def get(self, path, query=None):
        auth = base64.b64encode((self.credentials["LANGFUSE_PUBLIC_KEY"] + ":" +
                                 self.credentials["LANGFUSE_SECRET_KEY"]).encode()).decode()
        url = "https://jp.cloud.langfuse.com/api/public/" + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
        # No redirects: credentials must never leave the approved Cloud origin.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({}))
        remaining = getattr(self, "deadline", None)
        timeout = min(20, remaining - time.monotonic()) if remaining else 20
        if timeout <= 0:
            raise TimeoutError("Cloud read budget exhausted")
        with opener.open(request, timeout=timeout) as response:
            return json.load(response)

    def observations(self, row, start, end, trace_id=None):
        query = {**({"traceId": trace_id} if trace_id else {"sessionId": row["thread_id"]}), "fromStartTime": start,
                 "toStartTime": end, "limit": 100,
                 "fields": "core,basic,metadata,model,time,trace_context,io"}
        rows = []
        for _ in range(20):
            result = self.get("v2/observations", query)
            rows.extend(result.get("data", []))
            cursor = result.get("meta", {}).get("cursor")
            if not cursor:
                return rows
            query["cursor"] = cursor
        raise RuntimeError("STOP: Cloud 分页预算耗尽")



def export_failures(out):
    """Only expose error counts/status codes, never response bodies or headers."""
    import re

    path = out / "api.log"
    lines = path.read_text().splitlines() if path.exists() else []
    failures = [line for line in lines if "Failed to export" in line
                or "Exception while exporting" in line]
    codes = [match.group(1) for line in failures
             if (match := re.search(r"(?:code|status)[=: ]+(\d{3})", line, re.IGNORECASE))]
    return {"failure_count": len(failures), "http_statuses": codes}


def refresh_cloud(cloud, manifest, out):
    """Read existing evidence only, including after a partial batch STOP."""
    ready = True
    for row in manifest["runs"]:
        if not row.get("thread_id") or not row.get("run_id"):
            row["cloud"] = {"status": "unknown", "reason": "missing_runtime_identity"}
        else:
            start = (datetime.fromisoformat(row["start"]) - timedelta(seconds=2)).isoformat()
            end = (datetime.fromisoformat(row["end"]) + timedelta(seconds=2)).isoformat()
            observations = cloud.observations(row, start, end)
            preliminary = verify_cloud(observations, row, manifest["project_id"])
            if preliminary["trace_verified"]:
                observations = cloud.observations(row, start, end, trace_id=preliminary["trace_id"])
            write_private(out / f"{row['scenario_id']}-{row['repeat']}-cloud.json", observations)
            row["cloud"] = verify_cloud(observations, row, manifest["project_id"])
        ready &= row["cloud"].get("chain_verified", False)
    return ready


def wait_for_chain(cloud, manifest, out, timeout, now=time.monotonic, sleep=time.sleep):
    until = now() + timeout
    cloud.deadline = until
    while now() < until:
        try:
            ready = refresh_cloud(cloud, manifest, out)
        except TimeoutError:
            return False
        write_private(out / "manifest.json", manifest)
        if ready:
            return True
        sleep(min(15, max(0, until - now())))
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-mode", choices=("cloud", "off", "failure"), default="cloud")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--scenarios", nargs="+", choices=CASES, default=["S01"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-runs", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=150)
    parser.add_argument("--cloud-wait", type=int, default=120)
    args = parser.parse_args()
    count = len(args.scenarios) * args.repeats
    if not (1 <= count <= args.max_runs <= 6 and 30 <= args.timeout <= 180
            and 0 <= args.cloud_wait <= 960):
        parser.error("需要 1..6 个有界 Run、30..180 秒超时、0..960 秒 Cloud 等待")
    os.umask(0o077)

    def interrupted(_signum, _frame):
        raise RuntimeError("STOP: 用户取消，剩余 Run NOT RUN")

    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    values, credentials = configuration(args.env_file)
    batch = "issue91-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    out = ROOT / ".local/observability-lab" / batch
    private_directory(out)
    cloud = Cloud(credentials)
    manifest = {"batch_id": batch, "start": utc(), "max_runs": args.max_runs,
                "concurrency": 1, "max_model_decisions": 4, "max_tool_calls": 6,
                "model_sdk_max_retries": 1, "export_mode": args.export_mode, "runs": []}
    write_private(out / "manifest.json", manifest)
    print(f"计划 {count} Run，最大 {args.max_runs}，并发 1；私有结果：{out}", flush=True)
    try:
        projects = cloud.get("projects").get("data", []) if args.export_mode == "cloud" else [{"id": None}]
        if len(projects) != 1 or (args.export_mode == "cloud" and not projects[0].get("id")):
            raise RuntimeError("STOP: Cloud 项目身份不唯一")
        manifest["project_id"] = projects[0]["id"]
        with isolated(values, credentials, out, args.export_mode) as (base, token):
            for scenario in args.scenarios:
                for repeat in range(args.repeats):
                    row = {"scenario_id": scenario, "repeat": repeat + 1,
                           "protocol_status": "unknown", "start": utc()}
                    manifest["runs"].append(row)
                    write_private(out / "manifest.json", manifest)
                    try:
                        execute(base, token, scenario, batch, args.timeout, row,
                                out / f"{scenario}-{repeat + 1}-private.json")
                    finally:
                        row["end"] = utc()
                        write_private(out / "manifest.json", manifest)
                    write_private(out / "manifest.json", manifest)
                    if (row["protocol_status"] != "success" or row["sse_error"]
                            or not row["models_observed"] or row["model_decisions"] > 4
                            or row["tool_count"] > 6):
                        raise RuntimeError("STOP: 模型/协议失败或预算超限，后续 Run NOT RUN")
                    evidence = row["reader_evidence"]
                    if (not row["tool_pairs_valid"] or not row["history_tool_pairs_valid"]
                            or not evidence["tool_selection_compliant"]
                            or not evidence["evidence_sufficient"] or evidence["tool_failure_count"]
                            or evidence["event_uid_mismatch"] or evidence["budget_exhausted"]
                            or evidence["model_execution_failure"] or not evidence["final_answer_present"]):
                        raise RuntimeError("STOP: Reader/State/History 证据或诊断执行失败")
                    failures = export_failures(out)
                    if failures["failure_count"] and args.export_mode == "cloud":
                        raise RuntimeError("STOP: Cloud exporter 失败，不继续模型 Run")
        manifest["end"] = utc()
        manifest["lifecycle"] = lifecycle_result(out)
        manifest["exporter"] = export_failures(out)
        if args.export_mode != "cloud":
            fault = json.loads((out / "export-fault.json").read_text()) if args.export_mode == "failure" else {}
            for row in manifest["runs"]:
                row["cloud"] = {"status": "unknown", "reason": "negative_control_no_cloud_export",
                                "trace_verified": False, "chain_verified": False, "chain_status": "NOT RUN"}
            manifest["negative_control_passed"] = (
                manifest["exporter"]["failure_count"] == 0 if args.export_mode == "off" else
                manifest["exporter"]["failure_count"] > 0 and fault.get("requests", 0) > 0)
            write_private(out / "manifest.json", manifest)
            if not manifest["negative_control_passed"]:
                raise RuntimeError("STOP: OTel 负测注入未证实")
            print(json.dumps({"export_mode": args.export_mode, "negative_control_passed": True}))
            return
        ready = wait_for_chain(cloud, manifest, out, args.cloud_wait)
        print(json.dumps([{k: row.get(k) for k in ("scenario_id", "run_id", "cloud")}
                          for row in manifest["runs"]], ensure_ascii=False), flush=True)
        if not ready:
            raise RuntimeError("STOP: Cloud 完整调用链未证实，A3 BLOCKED，禁止 Phase B")
    except Exception as exc:
        manifest["end"] = utc()
        manifest["lifecycle"] = lifecycle_result(out)
        manifest["stop"] = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        manifest["exporter"] = export_failures(out)
        # A bounded read of already-created Runs never replays model requests.
        if manifest.get("project_id") and manifest["runs"] and not getattr(cloud, "deadline", None):
            try:
                cloud.deadline = time.monotonic() + min(20, args.cloud_wait)
                refresh_cloud(cloud, manifest, out)
            except (OSError, ValueError, RuntimeError) as cloud_error:
                manifest["cloud_recovery_error"] = type(cloud_error).__name__
        write_private(out / "manifest.json", manifest)
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - do not echo credential-bearing exceptions
        print(str(error) if isinstance(error, RuntimeError) else type(error).__name__,
              file=sys.stderr)
        sys.exit(1)
