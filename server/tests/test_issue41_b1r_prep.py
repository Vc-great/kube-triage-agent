"""Issue #41 B1-R Prep: frozen manifest and offline-only FakeModel execution."""

import asyncio
import json
import runpy
import socket
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "issue41_b1r_prep.py"


def test_manifest_is_frozen_and_contains_twelve_ab_pairs():
    runner = runpy.run_path(str(_SCRIPT))
    manifest, cases = runner["_load_frozen"]()
    assert len(cases) == 6
    assert len(manifest["runs"]) == 24
    pairs = {}
    for slot in manifest["runs"]:
        pairs.setdefault(slot["pair_id"], []).append(slot)
    assert len(pairs) == 12
    assert all({slot["arm"] for slot in pair} == {"A", "B"} for pair in pairs.values())


def test_offline_dry_run_exercises_all_pairs_without_network(monkeypatch, capsys):
    from kube_triage import deep_diagnosis

    runner = runpy.run_path(str(_SCRIPT))
    original_reader = deep_diagnosis.call_tool
    original_sockets = (socket.socket.connect, socket.socket.connect_ex,
                        socket.create_connection)
    monkeypatch.setattr(sys, "argv", [str(_SCRIPT), "--dry-run"])
    assert runner["main"]() == 0
    assert deep_diagnosis.call_tool is original_reader
    assert (socket.socket.connect, socket.socket.connect_ex,
            socket.create_connection) == original_sockets
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "pass"
    assert report["run_count"] == 24
    assert report["pair_count"] == 12
    assert report["provider_requests"] == report["kubernetes_requests"] == 0
    assert report["external_network"] is False
    assert all(item["status"] == "pass" for item in report["results"])
    assert all(item["target_evidence_verified"] for item in report["results"]
               if item["case_id"].startswith(("R01", "R02", "R03", "R04")))
    assert all(not item["target_evidence_verified"] for item in report["results"]
               if item["case_id"].startswith(("R05", "R06")))
    assert all(item["uid_conflict_detected"] and not item["target_evidence_verified"]
               for item in report["results"] if item["case_id"].startswith("R05"))
    assert all(not item["graph_guard_verified"] for item in report["results"]
               if item["case_id"].startswith("R05"))
    assert all("fixture_data_isolation" not in item["safety_findings"]
               and "uid_conflict_not_fenced" not in item["safety_findings"]
               for item in report["results"] if item["case_id"].startswith("R05"))


def test_reader_mock_is_restored_when_graph_execution_raises(monkeypatch):
    from kube_triage import deep_diagnosis

    runner = runpy.run_path(str(_SCRIPT))
    manifest, cases = runner["_load_frozen"]()
    slot = next(item for item in manifest["runs"] if item["arm"] == "A")
    original_reader = deep_diagnosis.call_tool

    def fail_build(_model):
        raise RuntimeError("synthetic graph build failure")

    monkeypatch.setattr(deep_diagnosis, "build_graph", fail_build)
    with pytest.raises(RuntimeError, match="synthetic graph build failure"):
        asyncio.run(runner["_execute"](slot, cases[slot["case_id"]]))
    assert deep_diagnosis.call_tool is original_reader


def test_uid_conflict_overrides_a_guard_that_accepts_last_pod(monkeypatch):
    from kube_triage import deep_diagnosis

    runner = runpy.run_path(str(_SCRIPT))
    manifest, cases = runner["_load_frozen"]()
    slot = next(item for item in manifest["runs"]
                if item["arm"] == "A" and item["case_id"].startswith("R05"))
    monkeypatch.setattr(deep_diagnosis, "_target_evidence", lambda *_args: (True, None))
    result = asyncio.run(runner["_execute"](slot, cases[slot["case_id"]]))
    assert result["uid_conflict_detected"]
    assert result["graph_guard_verified"]
    assert not result["target_evidence_verified"]
    assert result["status"] == "pass"
    assert "uid_conflict_not_fenced" not in result["safety_findings"]


def test_tampered_frozen_input_fails_closed(tmp_path, monkeypatch):
    runner = runpy.run_path(str(_SCRIPT))
    data = tmp_path / "issue41-b1r"
    data.mkdir()
    source = _ROOT / "eval" / "issue41-b1r"
    for name in ("cases.json", "rubric.json", "human-review-template.csv", "manifest.json"):
        (data / name).write_bytes((source / name).read_bytes())
    with (data / "cases.json").open("a", encoding="utf-8") as stream:
        stream.write(" ")
    monkeypatch.setitem(runner["_load_frozen"].__globals__, "DATA", data)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        runner["_load_frozen"]()


def test_tampered_manifest_fails_closed(tmp_path, monkeypatch):
    runner = runpy.run_path(str(_SCRIPT))
    data = tmp_path / "issue41-b1r"
    data.mkdir()
    source = _ROOT / "eval" / "issue41-b1r"
    (data / "manifest.json").write_bytes((source / "manifest.json").read_bytes() + b" ")
    monkeypatch.setitem(runner["_load_frozen"].__globals__, "DATA", data)
    with pytest.raises(ValueError, match="manifest SHA-256 mismatch"):
        runner["_load_frozen"]()
