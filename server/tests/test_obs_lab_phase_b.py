"""Approved Phase B gates, synthetic evidence only; no paid requests."""

import asyncio
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from obs_lab_verify import content_digest, verify_cloud
from test_obs_lab import observation


def cancelled_evidence():
    get = {"id": "get", "name": "pods_get", "args": {"namespace": "kube-triage-demo", "name": "sample-a"}}
    log = {"id": "log", "name": "pods_log", "args": {**get["args"], "tail": 30}}
    answer = "读取日志超时，未取得日志，无法判断具体根因。"
    row = {"scenario_id": "S04", "thread_id": "thread", "run_id": "run", "model_decisions": 2,
           "tool_pairs_valid": True, "history_tool_pairs_valid": True, "tool_calls": [get, log],
           "protocol_status": "success", "sse_error": False, "history_final_answer_valid": True,
           "final_answer": answer, "diagnosis_review": {"status": "PASS", "source": "synthetic fixture rubric",
                                                       "answer_sha256": content_digest(answer)},
           "fault_evidence": {"records": [
               {"tool_call_id": "get", "name": "pods_get", "outcome": "success", "wrapper_success": True},
               {"tool_call_id": "log", "name": "pods_log", "outcome": "timeout", "wrapper_success": False}]}}
    rows = [observation("root", "CHAIN", "0", "20", None),
            observation("llm1", "CHAIN", "1", "3"),
            observation("request", "GENERATION", "1", "2", "llm1"),
            observation("tools", "CHAIN", "4", "15"),
            observation("get-business", "CHAIN", "4", "6", "tools"),
            observation("get-tool", "TOOL", "4", "5", "get-business"),
            observation("log-business", "CHAIN", "6", "14", "tools"),
            observation("llm2", "CHAIN", "16", "19"),
            observation("response", "GENERATION", "17", "18", "llm2")]
    for span in rows:
        if span["id"] in {"tools", "llm1", "llm2"}:
            span["name"] = "tools" if span["id"] == "tools" else "llm"
    rows[2]["output"] = {"tool_calls": [get, log]}
    rows[5].update(name="pods_get", input=get["args"])
    for span, record in zip((rows[4], rows[6]), row["fault_evidence"]["records"], strict=True):
        span.update(name="reader_outcome", output={"tool_name": record["name"],
                    "tool_call_id": record["tool_call_id"], "tool_outcome": record["outcome"],
                    "wrapper_success": record["wrapper_success"]})
    row["tool_receipts"] = [{"type": "tool", "tool_call_id": "get", "content": '{"ok":true}'},
                            {"type": "tool", "tool_call_id": "log", "content": '{"ok":false,"error_type":"timeout"}'}]
    rows[8].update(input={"messages": deepcopy(row["tool_receipts"])},
                   output={"message": {"content": answer}})
    return row, rows


def test_s04_observable_pass_keeps_native_failure_and_actual_missing_id():
    row, rows = cancelled_evidence()
    result = verify_cloud(rows, row, "project")
    assert result["scenario_observable"] == "PASS", result
    assert result["native_trace_complete"] == "FAIL"
    assert not result["chain_verified"]
    assert result["cancelled_tool_calls"] == ["log"]
    assert (result["generation_count"], result["tool_count"]) == (2, 1)
    assert len(result["scenario_proof"]) == 2


@pytest.mark.parametrize("fault", ["generation", "business", "request_id", "response_id", "parent",
                                  "classification", "history", "normal_tool", "final", "review", "identity",
                                  "extra_tool", "wrong_target", "wrong_native_parent", "wrong_receipt", "history_final"])
def test_s04_exception_never_hides_other_missing_or_ambiguous_evidence(fault):
    row, rows = cancelled_evidence()
    if fault == "generation":
        rows.pop(2)
    elif fault == "business":
        rows.pop(6)
    elif fault == "request_id":
        rows[2]["output"] = {"tool_calls": [row["tool_calls"][0]]}
    elif fault == "response_id":
        rows[8]["input"] = {"tool_call_id": "get"}
    elif fault == "parent":
        rows[6]["parentObservationId"] = "root"
    elif fault == "classification":
        rows[6]["output"]["tool_outcome"] = "success"
    elif fault == "history":
        row["history_tool_pairs_valid"] = False
    elif fault == "normal_tool":
        rows.pop(5)
    elif fault == "final":
        rows[8]["output"] = {"content": "我已读取日志并确认根因"}
    elif fault == "review":
        row["diagnosis_review"]["answer_sha256"] = "stale"
    elif fault == "identity":
        rows[6]["metadata"]["run_id"] = "other"
    elif fault == "extra_tool":
        rows.append(observation("extra", "TOOL", "7", "8", "tools"))
    elif fault == "wrong_target":
        row["tool_calls"][1]["args"]["name"] = "sample-e"
    elif fault == "history_final":
        row["history_final_answer_valid"] = False
    elif fault == "wrong_receipt":
        rows[8]["input"]["messages"][1]["content"] = '{"ok":true}'
    elif fault == "wrong_native_parent":
        rows[5]["parentObservationId"] = "tools"
    assert verify_cloud(rows, row, "project")["scenario_observable"] == "BLOCKED"


@pytest.mark.parametrize("scenario", ["S01", "S02", "S03", "S05", "S06", "S08"])
def test_cancellation_exception_is_exclusive_to_s04(scenario):
    row, rows = cancelled_evidence()
    row["scenario_id"] = scenario
    result = verify_cloud(rows, row, "project")
    assert result["scenario_observable"] == "BLOCKED"
    assert not result["chain_verified"]


def test_s07_real_locked_sdk_attempts_share_native_trace_and_are_redacted(monkeypatch):
    import httpx
    from langchain_core.runnables import RunnableLambda
    from obs_lab_faults import attempt_transport, observed_model_factory
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from kube_triage.llm import chat_model

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrumentor = LangChainInstrumentor()
    instrumentor.instrument(tracer_provider=provider)
    for key, value in {"TRIAGE_ENV": "test", "LLM_MODEL": "offline-model", "LLM_API_KEY": "never-export-this-secret",
                       "LLM_BASE_URL": "http://127.0.0.1:12345/v1", "EVAL_LUNA_RESPONSES_HIGH": "false",
                       "LANGSMITH_TRACING": "false"}.items():
        monkeypatch.setenv(key, value)
    count = 0

    async def handler(request):
        nonlocal count
        count += 1
        assert "never-export-this-secret" in request.headers["Authorization"]
        if count == 1:
            return httpx.Response(429, json={"error": {"message": "synthetic", "type": "rate_limit_error"}},
                                  headers={"X-Obs-Lab-Attempt": "1", "Retry-After": "0"})
        return httpx.Response(200, json={"id": "offline", "model": "offline-model", "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "offline"}}]},
            headers={"X-Obs-Lab-Attempt": "2"})

    async def run():
        async with httpx.AsyncClient(transport=attempt_transport(httpx.MockTransport(handler))) as client:
            factory = observed_model_factory(chat_model, client)

            async def node(_):
                return await factory().ainvoke("Synthetic offline prompt")

            return await RunnableLambda(node, name="llm").ainvoke({})

    try:
        assert asyncio.run(run()).content == "offline"
        spans = exporter.get_finished_spans()
        attempts = [s for s in spans if s.name == "model_http_attempt"]
        llm = next(s for s in spans if s.name == "llm")
        assert len(attempts) == 2
        assert len({s.context.trace_id for s in spans}) == 1
        assert all(s.parent.span_id == llm.context.span_id for s in attempts)
        assert [json.loads(s.attributes["output.value"])["status"] for s in attempts] == [429, 200]
        assert attempts[0].attributes["langfuse.observation.level"] == "WARNING"
        assert attempts[0].attributes["langfuse.observation.metadata.fault_category"] == "synthetic_rate_limit"
        assert "never-export-this-secret" not in str([s.attributes for s in spans])
        assert sum(s.attributes.get("openinference.span.kind") == "LLM" for s in spans) == 1
    finally:
        instrumentor.uninstrument()
        provider.shutdown()


@pytest.mark.parametrize("broken", [None, "missing", "wrong_number", "wrong_parent", "wrong_trace", "local_only", "wrong_decision"])
def test_s07_recovery_requires_cloud_attempt_correlation(broken):
    row, rows = cancelled_evidence()
    row["scenario_id"] = "S07"
    row["fault_evidence"]["records"][1].update(outcome="success", wrapper_success=True)
    rows[6]["output"].update(tool_outcome="success", wrapper_success=True)
    tool = observation("log-tool", "TOOL", "7", "8", "log-business")
    tool.update(name="pods_log", input=row["tool_calls"][1]["args"])
    rows.append(tool)
    row["model_attempts"] = [{"attempt": 1, "forwarded": False, "status": 429},
                             {"attempt": 2, "forwarded": True, "status": 200},
                             {"attempt": 3, "forwarded": True, "status": 200}]
    for index, record in enumerate(row["model_attempts"]):
        span = observation(f"attempt-{index}", "CHAIN", "1" if index < 2 else "17",
                           "2" if index < 2 else "18", "llm1" if index < 2 else "llm2")
        span.update(name="model_http_attempt", output=deepcopy(record))
        rows.append(span)
    if broken == "missing":
        rows.pop()
    elif broken == "wrong_number":
        rows[-1]["output"]["attempt"] = 4
    elif broken == "wrong_parent":
        rows[-1]["parentObservationId"] = "root"
    elif broken == "wrong_decision":
        rows[-1]["parentObservationId"] = "llm1"
        rows[-1].update(startTime=rows[-2]["startTime"], endTime=rows[-2]["endTime"])
    elif broken == "wrong_trace":
        rows[-1]["traceId"] = "other"
    elif broken == "local_only":
        rows = [r for r in rows if r.get("name") != "model_http_attempt"]
    result = verify_cloud(rows, row, "project")
    assert (result["scenario_observable"] == "PASS") is (broken is None), result
    assert (result["event_result"] == "RECOVERED") is (broken is None)


def test_offline_reverification_preserves_original_failure_files(tmp_path, monkeypatch):
    from obs_lab_reverify import reverify

    row, rows = cancelled_evidence()
    row["repeat"] = 1
    messages = [{"type": "ai", "response_metadata": {"model_name": "offline"}, "tool_calls": row["tool_calls"]},
                *row["tool_receipts"], {"type": "ai", "tool_calls": [], "content": row["final_answer"],
                                       "response_metadata": {"model_name": "offline"}}]
    state = {"values": {"messages": messages}}
    raw = {"state": state, "history": [deepcopy(state)], "runs": [{"run_id": "run", "status": "success"}], "events": []}
    files = {"manifest.json": {"runs": [row], "project_id": "project", "stop": "historical STOP"},
             "S04-1-private.json": raw, "S04-1-cloud.json": rows}
    for name, data in files.items():
        (tmp_path / name).write_text(json.dumps(data))
    before = {name: (tmp_path / name).read_bytes() for name in files}
    result = reverify(tmp_path, {"run": row["diagnosis_review"]})
    assert result["runs"][0]["cloud"]["scenario_observable"] == "PASS"
    assert result["original_stop"] == "historical STOP"
    assert before == {name: (tmp_path / name).read_bytes() for name in files}
    assert reverify(tmp_path, {})["runs"][0]["cloud"]["diagnosis_behavior"] == "UNKNOWN"
    from obs_lab_reverify import main

    output = tmp_path.parent / (tmp_path.name + "-result.json")
    monkeypatch.setattr(sys, "argv", ["obs_lab_reverify", "--source", str(tmp_path), "--output", str(output)])
    main()
    assert output.stat().st_mode & 0o777 == 0o600
    assert json.loads(output.read_text())["original_stop"] == "historical STOP"
    with pytest.raises(SystemExit):
        main()  # Never overwrite an existing result.
    monkeypatch.setattr(sys, "argv", ["obs_lab_reverify", "--source", str(tmp_path),
                                    "--output", str(tmp_path / "overwrite-history.json")])
    with pytest.raises(SystemExit):
        main()
    assert before == {name: (tmp_path / name).read_bytes() for name in files}


def test_locked_sdk_cancel_reproduction_only_finishes_business_span(monkeypatch):
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
    instrumentor.instrument(tracer_provider=provider)

    async def native(name: str):
        await asyncio.sleep(1)

    tool = StructuredTool.from_function(coroutine=native, name="pods_log", description="Synthetic cancellation")

    async def original(name, arguments, thread_id):
        try:
            await asyncio.wait_for(tool.ainvoke(arguments), .01)
        except TimeoutError:
            return {"ok": False, "error_type": "timeout"}
        pytest.fail("Cancellation did not happen")

    async def node(_):
        with reader_context(graph_id="agent", tool_call_id="cancelled"):
            return await observed_reader(original)("pods_log", {"name": "sample-a"})

    try:
        assert asyncio.run(RunnableLambda(node, name="tools").ainvoke({}))["error_type"] == "timeout"
        spans = {s.name: s for s in exporter.get_finished_spans()}
        assert set(spans) == {"reader_outcome", "tools"}
        assert json.loads(spans["reader_outcome"].attributes["output.value"])["tool_outcome"] == "timeout"
        assert spans["reader_outcome"].attributes["langfuse.observation.level"] == "WARNING"
    finally:
        instrumentor.uninstrument()
        provider.shutdown()


@pytest.mark.parametrize("scenario", ["S05", "S06"])
@pytest.mark.parametrize("missing_native", [False, True])
def test_s05_s06_require_both_native_tool_and_correct_business_fault(scenario, missing_native):
    row, rows = cancelled_evidence()
    row["scenario_id"] = scenario
    row["fault_evidence"]["records"][1].update(outcome="success", wrapper_success=True)
    rows[6]["output"].update(tool_outcome="success", wrapper_success=True)
    row["tool_receipts"][1]["content"] = '{"ok":true}'
    index = 0 if scenario == "S05" else 1
    label, wrapper, payload = (("permission_denied", False, '{"ok":false,"error_type":"forbidden"}') if scenario == "S05"
                               else ("business_error", True, '{"ok":true,"result":{"ok":false}}'))
    row["fault_evidence"]["records"][index].update(outcome=label, wrapper_success=wrapper)
    rows[4 if index == 0 else 6]["output"].update(tool_outcome=label, wrapper_success=wrapper)
    row["tool_receipts"][index]["content"] = payload
    rows[8]["input"] = {"messages": deepcopy(row["tool_receipts"])}
    tool = observation("log-tool", "TOOL", "7", "8", "log-business")
    tool.update(name="pods_log", input=row["tool_calls"][1]["args"])
    rows.append(tool)
    if missing_native:
        rows = [o for o in rows if o["id"] != ("get-tool" if index == 0 else "log-tool")]
    result = verify_cloud(rows, row, "project")
    assert (result["scenario_observable"] == "PASS") is (not missing_native), result
    assert (result["native_trace_complete"] == "PASS") is (not missing_native)


def test_timeout_classification_without_actual_eight_second_business_span_is_blocked():
    row, rows = cancelled_evidence()
    rows[6]["endTime"] = rows[6]["startTime"]
    assert verify_cloud(rows, row, "project")["scenario_observable"] == "BLOCKED"


def test_history_final_answer_must_match_same_complete_snapshot():
    from obs_lab_verify import history_answer_matches

    row, _ = cancelled_evidence()
    messages = [{"type": "ai", "tool_calls": row["tool_calls"]}, *row["tool_receipts"],
                {"type": "ai", "content": row["final_answer"]}]
    state = {"values": {"messages": messages}}
    history = deepcopy(state)
    assert history_answer_matches(state, [history])
    history["values"]["messages"][-1]["content"] = "contradictory history"
    assert not history_answer_matches(state, [history])
