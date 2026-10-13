"""Offline Gate A contract check. This file never invokes Kubernetes or a shell."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "infra/k8s/scenarios"
CASES = {"crashloop", "imagepull", "healthy"}


def check() -> None:
    paths = sorted(SCENARIOS.glob("*.yaml"))
    expected = {SCENARIOS / f"triage-case-{case}.yaml" for case in CASES}
    assert set(paths) == expected, "Scenario files must be exactly the three reviewed Pods"
    names = set()
    for path in paths:
        documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        assert len(documents) == 1 and isinstance(documents[0], dict), path
        item = documents[0]
        case = path.stem.removeprefix("triage-case-")
        assert item.get("apiVersion") == "v1" and item.get("kind") == "Pod", path
        assert set(item) == {"apiVersion", "kind", "metadata", "spec"}, path
        meta = item["metadata"]
        assert set(meta) == {"name", "namespace", "labels"}, path
        assert meta["name"] == path.stem and meta["name"] not in names, path
        names.add(meta["name"])
        assert meta["namespace"] == "kube-triage-demo", path
        assert meta["labels"] == {
            "app.kubernetes.io/part-of": "kube-triage-agent",
            "app.kubernetes.io/component": f"scenario-{case}",
        }, path
        spec = item["spec"]
        assert set(spec) == {
            "automountServiceAccountToken", "restartPolicy", "securityContext", "containers"
        }, path
        assert spec["automountServiceAccountToken"] is False, path
        assert spec["restartPolicy"] == "Always", path
        assert spec["securityContext"] == {
            "runAsNonRoot": True, "runAsUser": 101,
            "seccompProfile": {"type": "RuntimeDefault"},
        }, path
        assert len(spec["containers"]) == 1, path
        container = spec["containers"][0]
        common = {"name", "image", "command", "resources", "securityContext"}
        extras = {"imagepull": {"imagePullPolicy"}, "healthy": {"ports", "readinessProbe"},
                  "crashloop": set()}
        assert set(container) == common | extras[case], path
        assert container["name"] == "app", path
        assert container["securityContext"] == {
            "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}
        }, path
        assert container["resources"] == {
            "requests": {"cpu": "10m" if case == "healthy" else "5m",
                         "memory": "32Mi" if case == "healthy" else "16Mi"},
            "limits": {"cpu": "100m" if case == "healthy" else "50m",
                       "memory": "64Mi" if case == "healthy" else "32Mi"},
        }, path
        command = container["command"]
        assert command[:2] == ["sh", "-c"], path
        if case == "crashloop":
            assert container["image"] == "busybox:1.36.1", path
            assert "REQUIRED_GREETING" in command[2] and "exit 42" in command[2], path
        elif case == "imagepull":
            assert container["image"] == "busybox:triage-issue11-tag-does-not-exist-20261013", path
            assert container["imagePullPolicy"] == "Always", path
        else:
            assert container["image"] == "busybox:1.36.1", path
            assert "exec httpd -f -p 8080" in command[2], path
            assert container["ports"] == [{"containerPort": 8080}], path
            assert container["readinessProbe"]["httpGet"] == {"path": "/", "port": 8080}, path
    print("PASS: 3 distinct Pod manifests; namespace, labels, security, resources and triggers verified")


if __name__ == "__main__":
    check()
