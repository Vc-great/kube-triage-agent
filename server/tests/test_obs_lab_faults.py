"""Phase B deterministic contracts; no paid model or Cloud calls."""

import asyncio
import json
import sys
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import obs_lab as lab
from obs_lab_faults import inspect_faults, model_429, outcome
from test_obs_lab import complete_evidence, observation


@pytest.mark.parametrize(("payload", "expected"), [
    ({"ok": False, "error_type": "timeout"}, "timeout"),
    ({"ok": False, "error_type": "forbidden"}, "permission_denied"),
    ({"ok": True, "result": '{"ok":false}'}, "business_error"),
    ({"ok": True, "result": '{"ok":true}'}, "success"),
    ({"ok": False, "error_type": "connection"}, "unknown"),
])
def test_business_outcome_is_separate_from_wrapper_success(payload, expected):
    assert outcome(payload) == expected


def test_duplicate_metric_uses_actual_calls_and_normalized_arguments():
    call = {"id": "a", "name": "pods_log", "args": {"namespace": "kube-triage-demo", "name": "sample-a"}}
    messages = [{"type": "ai", "tool_calls": [call]},
                {"type": "tool", "tool_call_id": "a", "content": '{"ok":true}'}]
    assert inspect_faults(messages, "S08")["duplicate_event"] == "NOT_TRIGGERED"
    other = deepcopy(call)
    other.update(id="b", args={**call["args"], "tail": 20})
    messages += [{"type": "ai", "tool_calls": [other]},
                 {"type": "tool", "tool_call_id": "b", "content": '{"ok":true}'}]
    result = inspect_faults(messages, "S08")
    assert result["duplicate_count"] == 1
    assert result["duplicate_event"] == "TRIGGERED"


def test_expected_fault_does_not_require_healthy_evidence_but_requires_actual_fault():
    row = {"scenario_id": "S04", "tool_pairs_valid": True, "history_tool_pairs_valid": True,
           "reader_evidence": {"tool_selection_compliant": True, "event_uid_mismatch": False,
                               "budget_exhausted": False, "model_execution_failure": False,
                               "final_answer_present": True, "evidence_sufficient": False,
                               "tool_failure_count": 1},
           "fault_evidence": {"fault_observed": True, "unexpected_outcomes": []}}
    assert lab.run_accepted(row)
    row["fault_evidence"]["fault_observed"] = False
    assert not lab.run_accepted(row)
    row["fault_evidence"].update(fault_observed=True, unexpected_outcomes=["unknown"])
    assert not lab.run_accepted(row)


@pytest.mark.parametrize("scenario", ["S04", "S05", "S06"])
def test_mock_faults_use_existing_legal_tools(monkeypatch, scenario):
    monkeypatch.setenv("TRIAGE_ENV", "test")
    monkeypatch.setenv("TRIAGE_MOCK_DATASET", "issue12-blind-v1")
    monkeypatch.setenv("OBS_LAB_SCENARIO", scenario)
    import importlib

    from kube_triage import mock_mcp
    mock = importlib.reload(mock_mcp)
    if scenario == "S05":
        with pytest.raises(ValueError, match="403 Forbidden"):
            mock.pods_get("kube-triage-demo", "sample-a")
    elif scenario == "S06":
        assert mock.pods_log("kube-triage-demo", "sample-a")["ok"] is False
    else:
        durations = []
        monkeypatch.setattr("time.sleep", durations.append)
        mock.pods_log("kube-triage-demo", "sample-a")
        assert durations == [8.2]
    with pytest.raises(ValueError, match="Namespace denied"):
        mock.pods_log("other", "sample-a")
    monkeypatch.setenv("TRIAGE_ENV", "production")
    with pytest.raises(ValueError, match="test-only"):
        mock.lab_fault()
    monkeypatch.delenv("OBS_LAB_SCENARIO")
    monkeypatch.setenv("TRIAGE_ENV", "test")
    monkeypatch.setenv("TRIAGE_MOCK_DATASET", "phase3a")
    importlib.reload(mock_mcp)


def test_real_reader_deadline_and_error_classification(monkeypatch):
    from kube_triage import mcp_client as reader
    assert reader.MCP_TIMEOUT_SECONDS == 8
    assert reader.MAX_RESULT_CHARS == 16 * 1024
    assert reader._error_type(TimeoutError())[0] == "timeout"
    assert reader._error_type(ValueError("Synthetic 403 Forbidden"))[0] == "forbidden"


@pytest.mark.parametrize("broken", [None, "missing", "wrong_id", "wrong_outcome", "wrong_parent"])
def test_cloud_business_outcome_must_match_real_tool_bridge(broken):
    row, rows = complete_evidence()
    row["scenario_id"] = "S06"
    record = {"tool_call_id": "call-1", "name": "pods_get", "outcome": "business_error", "wrapper_success": True}
    row["fault_evidence"] = {"records": [record]}
    span = observation("business", "CHAIN", "2", "5")
    span.update(name="reader_outcome", output={"tool_call_id": "call-1", "tool_name": "pods_get",
                                             "tool_outcome": "business_error", "wrapper_success": True})
    rows[2]["parentObservationId"] = "business"
    if broken == "wrong_id":
        span["output"]["tool_call_id"] = "wrong"
    elif broken == "wrong_outcome":
        span["output"]["tool_outcome"] = "success"
    elif broken == "wrong_parent":
        rows[2]["parentObservationId"] = "root"
    if broken != "missing":
        rows.append(span)
    assert lab.verify_cloud(rows, row, "project")["chain_verified"] is (broken is None)


def test_429_stub_injects_once_then_forwards_only_to_fixed_target(monkeypatch):
    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limit):
            return b'{"model":"synthetic-offline-provider"}'

    forwarded = []
    class Opener:
        def open(self, request, timeout):
            forwarded.append(request.full_url)
            assert timeout == 30
            return Response()

    real_build = urllib.request.build_opener
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    saved = []
    with model_429({"LLM_BASE_URL": lab.APPROVED_PROVIDER_URL, "LLM_API_KEY": "offline-secret"},
                   lab.validate_provider, lambda records: saved.append(deepcopy(records))) as endpoint:
        # Explicit local opener; no real Provider is contacted.
        local = real_build(urllib.request.ProxyHandler({}))
        def post(path="/chat/completions"):
            return local.open(urllib.request.Request(endpoint + path, data=b'{}'), timeout=2)
        with pytest.raises(urllib.error.HTTPError) as error:
            post()
        assert error.value.code == 429
        with post() as response:
            assert response.status == 200
        with pytest.raises(urllib.error.HTTPError) as error:
            post("/not-allowed")
        assert error.value.code == 404
    assert forwarded == [lab.APPROVED_PROVIDER_URL + "/chat/completions"]
    assert saved[-1] == [{"attempt": 1, "forwarded": False, "status": 429},
                         {"attempt": 2, "forwarded": True, "status": 200}]
    assert "offline-secret" not in json.dumps(saved)


@pytest.mark.parametrize("scenario,expected", [("S04", "timeout"), ("S05", "permission_denied"),
                                               ("S06", "business_error")])
def test_fault_through_real_mcp_transport_and_reader(monkeypatch, tmp_path, scenario, expected):
    import os
    import socket
    import subprocess
    import time

    from kube_triage import mcp_client as reader

    try:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 8000))
    except OSError:
        pytest.skip("Dedicated Mock port unavailable; do not touch existing service")
    finally:
        probe.close()
    environment = {key: value for key, value in os.environ.items()
                   if key in {"PATH", "SYSTEMROOT", "TMPDIR"}}
    environment.update(TRIAGE_ENV="test", TRIAGE_MOCK_DATASET="issue12-blind-v1",
                       OBS_LAB_SCENARIO=scenario, MOCK_MCP_HOST="127.0.0.1")
    monkeypatch.setenv("TRIAGE_ENV", "test")
    monkeypatch.setenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
    monkeypatch.setenv("APP_EVIDENCE_ENABLED", "false")
    monkeypatch.setattr(reader, "_tools", None)
    monkeypatch.setattr(reader, "_tools_url", None)
    monkeypatch.setattr(reader, "_client", None)
    with open(tmp_path / "mock.log", "w") as log:
        process = subprocess.Popen([sys.executable, "-m", "kube_triage.mock_mcp"],
                                   env=environment, stdout=log, stderr=log)
        try:
            for _ in range(100):
                assert process.poll() is None, "Mock exited before readiness"
                try:
                    with socket.create_connection(("127.0.0.1", 8000), timeout=.1):
                        break
                except OSError:
                    time.sleep(.05)
            else:
                pytest.fail("Mock readiness budget exhausted")
            name = "pods_get" if scenario == "S05" else "pods_log"
            result = asyncio.run(reader.call_tool(name, {"namespace": "kube-triage-demo", "name": "sample-a"}))
            assert outcome(result) == expected
            assert result["ok"] is (scenario == "S06")
        finally:
            process.terminate()
            process.wait(timeout=10)


def test_business_runnable_uses_real_openinference_parent_chain(monkeypatch):
    from langchain_core.runnables import RunnableLambda
    from langchain_core.tools import StructuredTool
    from obs_lab_faults import observed_reader
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from kube_triage.app_storage import reader_context

    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrumentor = LangChainInstrumentor()
    assert not instrumentor.is_instrumented_by_opentelemetry
    instrumentor.instrument(tracer_provider=provider)
    payload = {"ok": True, "result": '{"ok":false}'}

    async def native(namespace: str, name: str):
        return {"ok": False}

    tool = StructuredTool.from_function(coroutine=native, name="pods_log", description="Offline Tool")

    async def original(name, arguments, thread_id):
        assert await tool.ainvoke(arguments) == {"ok": False}
        return payload

    async def node(_input):
        with reader_context(graph_id="agent", tool_call_id="actual-id"):
            return await observed_reader(original)("pods_log", {
                "namespace": "kube-triage-demo", "name": "sample-a"}, "thread")

    try:
        result = asyncio.run(RunnableLambda(node, name="tools").ainvoke({}))
        assert result is payload
        spans = {span.name: span for span in exporter.get_finished_spans()}
        assert set(spans) == {"tools", "reader_outcome", "pods_log"}
        native_span, business, outer = (spans[n] for n in ("pods_log", "reader_outcome", "tools"))
        assert native_span.parent.span_id == business.context.span_id
        assert business.parent.span_id == outer.context.span_id
        assert len({span.context.trace_id for span in spans.values()}) == 1
        assert json.loads(business.attributes["output.value"]) == {
            "tool_outcome": "business_error", "wrapper_success": True,
            "tool_name": "pods_log", "tool_call_id": "actual-id"}
        assert "result" not in business.attributes["output.value"]
        assert business.attributes["langfuse.observation.level"] == "WARNING"
        assert business.attributes["langfuse.observation.status_message"] == "business_error; synthetic_redacted"
    finally:
        instrumentor.uninstrument()
        provider.shutdown()
    # Disabling OTel must preserve the actual Reader result as well.
    assert asyncio.run(RunnableLambda(node, name="tools").ainvoke({})) is payload
    assert len(exporter.get_finished_spans()) == 3


def test_locked_model_client_retries_synthetic_429_once(monkeypatch):
    from kube_triage.llm import chat_model

    data = json.dumps({"id": "offline-only", "model": "offline-model", "object": "chat.completion",
                       "choices": [{"index": 0, "finish_reason": "stop",
                                    "message": {"role": "assistant", "content": "offline"}}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()

    class Response:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self, limit):
            return data

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == lab.APPROVED_PROVIDER_URL + "/chat/completions"
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    records = []
    monkeypatch.setenv("TRIAGE_ENV", "test")
    monkeypatch.setenv("LLM_MODEL", "offline-model")
    monkeypatch.setenv("LLM_API_KEY", "offline-secret")
    monkeypatch.setenv("EVAL_LUNA_RESPONSES_HIGH", "false")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    with model_429({"LLM_BASE_URL": lab.APPROVED_PROVIDER_URL, "LLM_API_KEY": "offline-secret"},
                   lab.validate_provider, lambda rows: records.append(deepcopy(rows))) as endpoint:
        monkeypatch.setenv("LLM_BASE_URL", endpoint)
        model = chat_model()
        assert model.max_retries == 1
        result = model.invoke("Synthetic offline retry test")
        assert result.content == "offline"
    assert [r["status"] for r in records[-1]] == [429, 200]


def test_http_request_count_and_index_are_truthful_and_secret_free(tmp_path):
    (tmp_path / "api.log").write_text(
        'HTTP Request: POST http://127.0.0.1:43210/v1/chat/completions "HTTP/1.1 429 Too Many Requests"\n'
        'HTTP Request: POST http://127.0.0.1:43210/v1/chat/completions "HTTP/1.1 200 OK"\n'
        'HTTP Request: POST http://127.0.0.1:8000/mcp "HTTP/1.1 200 OK"\n'
        'some unrelated secret text\n')
    result = lab.model_request_summary(tmp_path)
    assert result["http_post_count"] == 2
    assert result["statuses"] == [429, 200]
    assert "secret" not in json.dumps(result)
    lab.write_index(tmp_path, {"runs": [{"scenario_id": "S07", "protocol_status": "unknown"}]})
    assert "https://" not in (tmp_path / "index.md").read_text()


@pytest.mark.parametrize("scenario", ["S04", "S05", "S06", "S07", "S08"])
def test_fault_choice_only_propagates_from_runner_config(monkeypatch, scenario):
    monkeypatch.setenv("OBS_LAB_SCENARIO", "S05")
    values = {"LLM_MODEL": "synthetic", "LLM_API_KEY": "fake", "LLM_BASE_URL": lab.APPROVED_PROVIDER_URL}
    api, mock = lab.environments(values, {}, {"pg": 1, "redis": 2, "api": 3}, "batch", False)
    assert "OBS_LAB_SCENARIO" not in api
    assert "OBS_LAB_SCENARIO" not in mock
    values["OBS_LAB_SCENARIO"] = scenario
    api, mock = lab.environments(values, {}, {"pg": 1, "redis": 2, "api": 3}, "batch", False)
    assert api["OBS_LAB_SCENARIO"] == mock["OBS_LAB_SCENARIO"] == scenario


def test_expected_timeout_must_belong_to_injected_tool_and_target():
    def inspect(name, pod):
        return inspect_faults([
            {"type": "ai", "tool_calls": [{"id": "a", "name": name,
              "args": {"namespace": "kube-triage-demo", "name": pod}}]},
            {"type": "tool", "tool_call_id": "a", "content": '{"ok":false,"error_type":"timeout"}'}], "S04")
    assert inspect("pods_log", "sample-a")["fault_observed"]
    assert not inspect("pods_get", "sample-a")["fault_observed"]
    assert not inspect("pods_log", "sample-e")["fault_observed"]
    assert inspect("pods_get", "sample-a")["unexpected_outcomes"] == ["timeout"]


@pytest.mark.parametrize("fault", [None, "no429", "no_forward", "bad_number", "wrong_count", "failure"])
def test_retry_recovery_requires_numbered_real_forwarding_and_model_count(fault):
    from obs_lab_faults import retry_recovered

    attempts = [{"attempt": 1, "forwarded": False, "status": 429},
                {"attempt": 2, "forwarded": True, "status": 200}]
    decisions = 1
    if fault == "no429":
        attempts[0]["status"] = 200
    elif fault == "no_forward":
        attempts[1]["forwarded"] = False
    elif fault == "bad_number":
        attempts[1]["attempt"] = 3
    elif fault == "wrong_count":
        decisions = 2
    elif fault == "failure":
        attempts[1]["status"] = 403
    assert retry_recovered(attempts, decisions) is (fault is None)


@pytest.mark.parametrize("broken", [None, "wrong_call_id", "sibling_tool", "missing_business"])
def test_same_generation_duplicate_tools_match_by_business_call_id(broken):
    row, _ = complete_evidence()
    first = row["tool_calls"][0]
    second = {**first, "id": "call-2"}
    row.update(scenario_id="S08", tool_calls=[first, second])
    rows = [observation("root", "CHAIN", "0", "15", None),
            observation("request", "GENERATION", "1", "2"),
            observation("response", "GENERATION", "12", "13")]
    rows[1]["output"] = {"tool_calls": [first, second]}
    rows[2]["input"] = {"messages": [{"tool_call_id": c["id"], "content": "synthetic"}
                                    for c in (first, second)]}
    records = []
    for index, call in enumerate((first, second)):
        offset = 3 + index * 4
        business = observation(f"business-{index}", "CHAIN", str(offset), str(offset + 3))
        business.update(name="reader_outcome", output={"tool_call_id": call["id"],
                        "tool_name": call["name"], "tool_outcome": "success", "wrapper_success": True})
        tool = observation(f"tool-{index}", "TOOL", str(offset + 1), str(offset + 2), parent=business["id"])
        tool.update(name=call["name"], input=call["args"])
        records.append({"tool_call_id": call["id"], "name": call["name"],
                        "outcome": "success", "wrapper_success": True})
        rows.extend([business, tool])
    row["fault_evidence"] = {"records": records}
    if broken == "wrong_call_id":
        rows[5]["output"]["tool_call_id"] = "wrong"
    elif broken == "sibling_tool":
        rows[6]["parentObservationId"] = "root"
    elif broken == "missing_business":
        rows.pop(5)
    result = lab.verify_cloud(rows, row, "project")
    assert result["chain_verified"] is (broken is None)
    if broken is None:
        assert len(result["tool_call_proof"]) == 2
        assert {p["tool_observation"] for p in result["tool_call_proof"]} == {"tool-0", "tool-1"}
