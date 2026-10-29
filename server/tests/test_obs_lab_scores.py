"""Phase C deterministic checks: synthetic fixtures only, no network/model I/O."""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import obs_lab_scores as scores


def evidence(pod="sample-g", uid=None):
    def receipt(ident, result):
        return {"type": "tool", "tool_call_id": ident, "status": "success",
                "content": json.dumps({"ok": True, "result": result})}
    messages = [{"type": "human", "content": "当前状态？"},
                {"type": "ai", "name": "triage_llm", "id": "model1", "tool_calls": [
                    {"id": "pod", "name": "pods_get", "args": {"namespace": "kube-triage-demo", "name": pod}},
                    {"id": "event", "name": "events_list", "args": {"namespace": "kube-triage-demo"}}]},
                receipt("pod", {"mock": True, "source": "static-fixture", "name": pod,
                                "metadata": {"uid": "synthetic-g"},
                                "status": {"phase": "Running", "containerStatuses": [{"ready": False}]}}),
                receipt("event", {"mock": True, "source": "static-fixture", "events": [{
                    "type": "Warning", "involvedObject": {"kind": "Pod", "name": pod,
                    "namespace": "kube-triage-demo", **({"uid": uid} if uid else {})}}]}),
                {"type": "ai", "id": "model2", "name": "triage_llm", "content": "UID缺失，仅弱归属，根因未知"}]
    state = {"values": {"messages": messages}}
    return {"state": state, "history": [deepcopy(state)]}


def test_s10_weak_uid_cannot_become_strong_or_diagnosis_correct():
    row = scores.score_run({"scenario_id": "S10"}, evidence(), scores.frozen_cases()["g"])
    assert row["rules"]["tool_protocol_valid"]["status"] == "PASS"
    assert row["rules"]["grounding_rule"]["status"] == "PASS"
    assert row["rules"]["evidence_uid_matched"]["status"] == "UNKNOWN"
    assert row["diagnosis_correct"] == "UNKNOWN"
    assert row["usage"]["totals"]["input"]["value"] is None


@pytest.mark.parametrize("uid,status", [("synthetic-g", "PASS"), ("different", "FAIL")])
def test_uid_correspondence_is_independent_of_text(uid, status):
    row = scores.score_run({"scenario_id": "S10"}, evidence(uid=uid), scores.frozen_cases()["g"])
    assert row["rules"]["evidence_uid_matched"]["status"] == status
    assert row["diagnosis_correct"] == "UNKNOWN"


def test_s10_wrong_answer_fails_lexical_grounding_check():
    raw = evidence()
    raw["state"]["values"]["messages"][-1]["content"] = "已确认数据库宕机"
    row = scores.score_run({"scenario_id": "S10"}, raw, scores.frozen_cases()["g"])
    assert row["rules"]["grounding_rule"]["status"] == "FAIL"
    assert row["diagnosis_correct"] == "UNKNOWN"


def test_orphan_and_history_tamper_fail_protocol():
    raw = evidence()
    raw["state"]["values"]["messages"][2]["tool_call_id"] = "wrong"
    result = scores.score_run({"scenario_id": "S10"}, raw, scores.frozen_cases()["g"])
    assert result["rules"]["tool_protocol_valid"]["status"] == "FAIL"
    assert result["rules"]["grounding_rule"]["status"] == "UNKNOWN"


def test_pairing_does_not_make_unapproved_tool_arguments_valid():
    raw = evidence()
    raw["state"]["values"]["messages"][1]["tool_calls"][0]["args"]["namespace"] = "other"
    raw["history"] = [deepcopy(raw["state"])]
    result = scores.score_run({"scenario_id": "S10"}, raw, scores.frozen_cases()["g"])
    assert result["rules"]["tool_protocol_valid"]["status"] == "FAIL"


def test_duplicate_alone_does_not_judge_unnecessary():
    raw = evidence()
    messages = raw["state"]["values"]["messages"]
    second = deepcopy(messages[1])
    second["tool_calls"] = [deepcopy(second["tool_calls"][0])]
    second["tool_calls"][0]["id"] = "pod2"
    receipt = deepcopy(messages[2])
    receipt["tool_call_id"] = "pod2"
    messages[-1:-1] = [second, receipt]
    raw["history"] = [deepcopy(raw["state"])]
    row = scores.score_run({"scenario_id": "S08"}, raw, scores.frozen_cases()["a"])
    assert row["duplicate_count"] == 1
    assert row["rules"]["unnecessary_retry"]["status"] == "UNKNOWN"


def test_missing_state_never_scores_zero_or_pass():
    result = scores.score_run({"scenario_id": "S10"}, {}, scores.frozen_cases()["g"])
    assert {r["status"] for r in result["rules"].values()} == {"UNKNOWN"}


def test_plan_stable_ids_and_no_raw_text():
    row = scores.score_run({"scenario_id": "S10"}, evidence(), scores.frozen_cases()["g"])
    row.update(project_id="project", batch_id="batch", run_id="run", trace_id="trace", source_sha256="hash",
               score_timestamp="2026-10-28T00:00:00+00:00")
    plan = scores.upload_plan({"runs": [row]})
    assert plan == scores.upload_plan({"runs": [row]})
    assert len({s["id"] for s in plan["scores"]}) == plan["max_writes"] == 5
    assert "根因未知" not in json.dumps(plan, ensure_ascii=False)
    row["trace_id"] = "different"
    assert scores.upload_plan({"runs": [row]})["plan_sha256"] != plan["plan_sha256"]


def test_frozen_ground_truth_change_stops(monkeypatch):
    monkeypatch.setattr(scores, "fixtures_sha", lambda: "changed")
    with pytest.raises(ValueError, match="STOP"):
        scores.frozen_cases()


def test_saved_batch_end_to_end_and_duplicate_identity_stop(tmp_path):
    from test_obs_lab import complete_evidence

    row, cloud = complete_evidence()
    row.update(scenario_id="S01", repeat=1, end="2026-10-27T00:00:10+00:00")
    call = row["tool_calls"][0]
    messages = [{"type": "human", "content": "当前状态？"},
                {"type": "ai", "tool_calls": [call]},
                {"type": "tool", "tool_call_id": call["id"], "status": "success", "content": "synthetic"},
                {"type": "ai", "content": "Ready，端到端业务未知"}]
    state = {"values": {"messages": messages}}
    raw = {"state": state, "history": [state], "thread_id": "thread", "events": [],
           "runs": [{"run_id": "run", "status": "success"}]}
    for path, data in (("manifest.json", {"project_id": "p", "batch_id": "b", "runs": [row]}),
                       ("S01-1-private.json", raw), ("S01-1-cloud.json", cloud)):
        (tmp_path / path).write_text(json.dumps(data))
    original = {p: p.read_bytes() for p in tmp_path.iterdir()}
    result = scores.evaluate([tmp_path])
    assert result["denominators"]["runs"] == 1
    assert result["trace_root_latency"]["p50"]["value"] == 9
    assert result["latency"]["p50"]["value"] is None
    assert scores.upload_plan(result)["max_writes"] == 5
    assert all(p.read_bytes() == data for p, data in original.items())
    with pytest.raises(ValueError, match="duplicate"):
        scores.evaluate([tmp_path, tmp_path])


def test_multiturn_projection_uses_saved_history_and_current_run_only():
    raw = evidence()
    original = deepcopy(raw)
    raw["prior_run_ids"] = ["old"]
    raw["thread_id"] = "thread"
    raw["runs"] = [{"run_id": "old", "thread_id": "thread"}, {"run_id": "new", "thread_id": "thread"}]
    old_turn = [{"type": "human", "content": "old"}, {"type": "ai", "content": "old response"}]
    raw["state"]["values"]["messages"][:0] = old_turn
    projected = scores.turn_evidence(raw)
    assert projected["state"] == original["state"]
    assert projected["history"] == original["history"]
    assert [r["run_id"] for r in projected["runs"]] == ["new"]
    raw["history"] = []
    projected = scores.turn_evidence(raw)
    assert projected["history"] == []  # Never synthesize a matching History from State.
    assert scores.score_run({"scenario_id": "S10"}, projected, scores.frozen_cases()["g"])[
        "rules"]["tool_protocol_valid"]["status"] == "FAIL"
