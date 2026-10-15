"""Phase 3-4 冻结题库与四组对照的离线验收。"""

import importlib.util
import json
from pathlib import Path

from kube_triage.incident_memory_retrieval import target_pod

ROOT = Path(__file__).resolve().parents[2]


def evaluation():
    path = ROOT / "scripts/eval_incident_memory_phase34.py"
    spec = importlib.util.spec_from_file_location("eval_incident_memory_phase34", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_twelve_new_cases_and_frozen_reader_mapping():
    module = evaluation()
    rows = module.cases()
    assert len(rows) == 12
    assert {row["case_id"] for row in rows}.isdisjoint(
        {f"P33-{index:02d}" for index in range(1, 13)})
    for row in rows:
        assert target_pod(row["user_prompt"]) == row["target_pod"]
        assert row["historical_conversation"]["old_time"]
        assert row["memory_seeds"]
        assert set(row["reader_responses"]) == {
            "pods_get", "pods_log", "events_list", "pods_list_in_namespace"}
    assert sum(row["historical_conversation"]["rounds"] >= 6 for row in rows) >= 6


def test_four_arm_plan_and_fault_denominators():
    module = evaluation()
    assert module.make_plan("pilot-v3")["planned_runs"] == 8
    formal = module.make_plan("formal-v2")
    fault = module.make_plan("fault-v2")
    assert formal["planned_runs"] == 144
    assert fault["planned_runs"] == 32
    assert len({item["pair_id"] for item in formal["pairs"]}) == 36
    assert all(sorted(item["arm_order"]) == list("ABCD") for item in formal["pairs"])
    assert formal["context_estimated_total_budget"] == 9000
    assert {key for arm in module.ARMS.values() for key in arm} == {
        "CONTEXT_SUMMARY_ENABLED", "INCIDENT_MEMORY_READ_ENABLED"}


def test_p34_07_08_09_have_unrelated_success_and_unverified_target():
    rows = {row["case_id"]: row for row in evaluation().cases()}
    for ident in (7, 8, 9):
        row = rows[f"P34-{ident:02d}"]
        assert row["expected"]["target_verified"] is False
        assert row["reader_responses"]["pods_list_in_namespace"]["ok"] is True
        assert row["reader_responses"]["events_list"]["ok"] is True
    wrong = json.loads(rows["P34-09"]["reader_responses"]["pods_get"]["result"])
    assert wrong["metadata"]["name"] != rows["P34-09"]["target_pod"]


def test_oom_previous_termination_and_current_waiting_both_present():
    case = next(row for row in evaluation().cases() if row["case_id"] == "P34-05")
    pod = json.loads(case["reader_responses"]["pods_get"]["result"])
    container = pod["status"]["containerStatuses"][0]
    assert container["lastState"]["terminated"]["reason"] == "OOMKilled"
    assert container["state"]["waiting"]["reason"] == "CrashLoopBackOff"
