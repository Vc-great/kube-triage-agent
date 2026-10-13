"""Offline Gate A contract check. This file never invokes Kubernetes or a shell."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "infra/k8s/scenarios"
CASES = {"crashloop", "imagepull", "healthy"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check() -> None:
    paths = sorted(SCENARIOS.glob("*.yaml"))
    expected = {SCENARIOS / f"triage-case-{case}.yaml" for case in CASES}
    require(set(paths) == expected, "Scenario files must be exactly the three reviewed Pods")
    names = set()
    for path in paths:
        documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        require(len(documents) == 1 and isinstance(documents[0], dict), str(path))
        item = documents[0]
        case = path.stem.removeprefix("triage-case-")
        require(item.get("apiVersion") == "v1" and item.get("kind") == "Pod", str(path))
        require(set(item) == {"apiVersion", "kind", "metadata", "spec"}, str(path))
        meta = item["metadata"]
        require(isinstance(meta, dict), str(path))
        require(set(meta) == {"name", "namespace", "labels"}, str(path))
        require(meta["name"] == path.stem and meta["name"] not in names, str(path))
        names.add(meta["name"])
        require(meta["namespace"] == "kube-triage-demo", str(path))
        require(meta["labels"] == {
            "app.kubernetes.io/part-of": "kube-triage-agent",
            "app.kubernetes.io/component": f"scenario-{case}",
        }, str(path))
        spec = item["spec"]
        require(isinstance(spec, dict), str(path))
        require(set(spec) == {
            "automountServiceAccountToken", "restartPolicy", "securityContext", "containers"
        }, str(path))
        require(spec["automountServiceAccountToken"] is False, str(path))
        require(spec["restartPolicy"] == "Always", str(path))
        require(spec["securityContext"] == {
            "runAsNonRoot": True, "runAsUser": 101,
            "seccompProfile": {"type": "RuntimeDefault"},
        }, str(path))
        require(isinstance(spec["containers"], list) and len(spec["containers"]) == 1, str(path))
        container = spec["containers"][0]
        require(isinstance(container, dict), str(path))
        common = {"name", "image", "command", "resources", "securityContext"}
        extras = {"imagepull": {"imagePullPolicy"}, "healthy": {"ports", "readinessProbe"},
                  "crashloop": set()}
        require(set(container) == common | extras[case], str(path))
        require(container["name"] == "app", str(path))
        require(container["securityContext"] == {
            "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}
        }, str(path))
        require(container["resources"] == {
            "requests": {"cpu": "10m" if case == "healthy" else "5m",
                         "memory": "32Mi" if case == "healthy" else "16Mi"},
            "limits": {"cpu": "100m" if case == "healthy" else "50m",
                       "memory": "64Mi" if case == "healthy" else "32Mi"},
        }, str(path))
        command = container["command"]
        require(isinstance(command, list) and len(command) == 3 and command[:2] == ["sh", "-c"], str(path))
        if case == "crashloop":
            require(container["image"] == "busybox:1.36.1", str(path))
            require("REQUIRED_GREETING" in command[2] and "exit 42" in command[2], str(path))
        elif case == "imagepull":
            require(container["image"] == "busybox:triage-issue11-tag-does-not-exist-20261013", str(path))
            require(container["imagePullPolicy"] == "Always", str(path))
        else:
            require(container["image"] == "busybox:1.36.1", str(path))
            require("exec httpd -f -p 8080" in command[2], str(path))
            require(container["ports"] == [{"containerPort": 8080}], str(path))
            require(container["readinessProbe"]["httpGet"] == {"path": "/", "port": 8080}, str(path))
    print("PASS: 3 distinct Pod manifests; namespace, labels, security, resources and triggers verified")


if __name__ == "__main__":
    check()
