"""Offline negative cases for the three reviewed Issue #11 Pod manifests."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check_issue11_manifests.py"
SCENARIOS = ROOT / "infra/k8s/scenarios"


def checker():
    spec = importlib.util.spec_from_file_location("issue11_manifest_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def copied_scenarios(tmp_path):
    for path in SCENARIOS.glob("*.yaml"):
        shutil.copyfile(path, tmp_path / path.name)
    return tmp_path


def test_reviewed_manifests_pass(copied_scenarios):
    module = checker()
    module.SCENARIOS = copied_scenarios
    module.check()


@pytest.mark.parametrize(
    ("case", "path", "value"),
    [
        ("healthy", ("metadata", "namespace"), "default"),
        ("healthy", ("metadata", "labels", "app.kubernetes.io/part-of"), "other"),
        ("healthy", ("spec", "containers", 0, "resources", "requests", "cpu"), "1"),
        ("healthy", ("spec", "containers", 0, "image"), "other:latest"),
        ("healthy", ("spec", "hostNetwork"), True),
        ("healthy", ("spec", "volumes"), [{"name": "host", "hostPath": {"path": "/"}}]),
        ("healthy", ("spec", "containers", 0, "securityContext", "privileged"), True),
    ],
)
def test_modified_manifest_is_rejected(copied_scenarios, case, path, value):
    target = copied_scenarios / f"triage-case-{case}.yaml"
    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    current = document
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    target.write_text(yaml.safe_dump(document), encoding="utf-8")
    module = checker()
    module.SCENARIOS = copied_scenarios
    with pytest.raises(ValueError):
        module.check()


def test_optimized_python_still_rejects_modified_namespace(copied_scenarios):
    target = copied_scenarios / "triage-case-healthy.yaml"
    document = yaml.safe_load(target.read_text(encoding="utf-8"))
    document["metadata"]["namespace"] = "default"
    target.write_text(yaml.safe_dump(document), encoding="utf-8")
    code = (
        "import importlib.util, pathlib, sys; "
        "s=importlib.util.spec_from_file_location('check', sys.argv[1]); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "m.SCENARIOS=pathlib.Path(sys.argv[2]); m.check()"
    )
    result = subprocess.run(
        [sys.executable, "-O", "-c", code, str(SCRIPT), str(copied_scenarios)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "ValueError" in result.stderr
