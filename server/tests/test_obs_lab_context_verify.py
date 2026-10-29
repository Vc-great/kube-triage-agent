"""S09 Summary may occur between a tool receipt and the next diagnostic Generation."""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from obs_lab_context_verify import verify_context_cloud
from obs_lab_scores import evaluate
from obs_lab_verify import verify_native
from test_obs_lab import complete_evidence, observation


def interrupted_chain():
    row, rows = complete_evidence()
    row.update(scenario_id="S09", repeat=1, end="2026-10-27T00:00:10+00:00")
    rows[-1].update(startTime="2026-10-27T00:00:07+00:00", endTime="2026-10-27T00:00:08+00:00")
    wrapper = observation("summary", "CHAIN", 4, 7)
    wrapper.update(name="context_summary_outcome", output={"context_summary_outcomes": [{
        "status": "adopted", "summary_calls": 1, "input_tokens": 100, "output_tokens": 30}]})
    summary = observation("summary-generation", "GENERATION", 5, 6, "summary")
    summary.update(input={"messages": ["serialized historical rounds"]}, output="synthetic summary")
    rows.extend([wrapper, summary])
    return row, rows


def test_summary_between_tool_and_answer_preserves_all_generations():
    row, rows = interrupted_chain()
    old = verify_native(rows, {**row, "model_decisions": 3}, "p")
    assert any(m.startswith("request_tool_response") for m in old["missing"])
    verified = verify_context_cloud(rows, row, "p")
    assert verified["chain_verified"], verified
    assert verified["generation_count"] == 3
    assert verified["summary_generation_ids"] == ["summary-generation"]
    assert verified["tool_call_proof"][0]["response_generation"] == "c"


@pytest.mark.parametrize("fault", ["parent", "missing_generation", "audit_count", "time", "missing_answer"])
def test_summary_classification_never_hides_incomplete_chain(fault):
    row, rows = interrupted_chain()
    if fault == "parent":
        rows[-1]["parentObservationId"] = "root"
    elif fault == "missing_generation":
        rows.pop()
    elif fault == "audit_count":
        rows[-2]["output"]["context_summary_outcomes"][0]["summary_calls"] = 0
    elif fault == "time":
        rows[-1]["endTime"] = "2026-10-27T00:00:09+00:00"
    elif fault == "missing_answer":
        rows = [r for r in rows if r["id"] != "c"]
    verified = verify_context_cloud(rows, row, "p")
    assert not verified["chain_verified"]


def test_offline_evaluate_uses_same_summary_role_verifier(tmp_path):
    row, cloud = interrupted_chain()
    call = row["tool_calls"][0]
    call["args"]["name"] = "sample-h"
    cloud[2]["input"]["name"] = "sample-h"
    messages = [{"type": "human", "content": "current"},
                {"type": "ai", "tool_calls": [call], "response_metadata": {"model_name": "synthetic"}},
                {"type": "tool", "tool_call_id": call["id"], "content": "synthetic", "status": "success"},
                {"type": "ai", "content": "Ready，业务未知", "response_metadata": {"model_name": "synthetic"}}]
    # complete_evidence shared the original call object with Cloud output; keep it explicit.
    cloud[1]["output"]["generations"][0][0]["message"]["kwargs"]["tool_calls"] = [deepcopy(call)]
    state = {"values": {"messages": messages}}
    raw = {"thread_id": "thread", "prior_run_ids": [], "state": state, "history": [state], "events": [],
           "runs": [{"run_id": "run", "thread_id": "thread", "status": "success"}]}
    for path, value in (("manifest.json", {"project_id": "p", "batch_id": "b", "runs": [row]}),
                        ("S09-1-private.json", raw), ("S09-1-cloud.json", cloud)):
        (tmp_path / path).write_text(json.dumps(value))
    result = evaluate([tmp_path])
    assert result["runs"][0]["native_trace_complete"] == "PASS"
    assert result["runs"][0]["summary_outcomes"][0]["status"] == "adopted"
