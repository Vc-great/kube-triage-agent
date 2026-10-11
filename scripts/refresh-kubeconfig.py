#!/usr/bin/env python3
"""Manually issue a short-lived reader token and write a single-context kubeconfig."""

import argparse
import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "kube-triage-demo"
ACCOUNT = "kube-triage-reader"


def kubectl(*args: str) -> str:
    return subprocess.check_output(["kubectl", *args], text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, help="Confirmed bootstrap context")
    parser.add_argument("--confirm", required=True,
                        help=f"Type the exact context name and /{NAMESPACE}")
    args = parser.parse_args()
    if args.confirm != f"{args.context}/{NAMESPACE}":
        parser.error("context/namespace confirmation did not match")

    source = json.loads(kubectl("config", "view", "--raw", "--minify",
                                "--context", args.context, "-o", "json"))
    cluster = source["clusters"][0]["cluster"]
    server = cluster["server"]
    if not server.startswith("https://"):
        parser.error("Kubernetes API server must use HTTPS")
    ca = cluster.get("certificate-authority-data")
    if not ca and cluster.get("certificate-authority"):
        ca_path = Path(cluster["certificate-authority"])
        if not ca_path.is_absolute():
            source_file = Path(os.environ.get("KUBECONFIG", str(Path.home() / ".kube/config"))
                               .split(os.pathsep)[0])
            ca_path = source_file.parent / ca_path
        ca = base64.b64encode(ca_path.read_bytes()).decode()
    if not ca or cluster.get("insecure-skip-tls-verify"):
        parser.error("trusted CA data is required; insecure TLS is forbidden")

    token = kubectl("--context", args.context, "-n", NAMESPACE, "create", "token",
                    ACCOUNT, "--duration=24h")
    if not token:
        raise RuntimeError("kubectl returned an empty token")
    config = {
        "apiVersion": "v1", "kind": "Config", "current-context": "kube-triage-reader",
        "clusters": [{"name": "target", "cluster": {
            "server": server, "certificate-authority-data": ca}}],
        "users": [{"name": ACCOUNT, "user": {"token": token}}],
        "contexts": [{"name": "kube-triage-reader", "context": {
            "cluster": "target", "user": ACCOUNT, "namespace": NAMESPACE}}],
    }
    directory = ROOT / ".local"
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    with tempfile.NamedTemporaryFile("w", dir=directory, prefix=".kubeconfig-",
                                     delete=False, encoding="utf-8") as output:
        os.chmod(output.name, 0o600)
        json.dump(config, output, indent=2)
        temporary = Path(output.name)
    temporary.replace(directory / "kubeconfig")
    print("Wrote project-only .local/kubeconfig (mode 0600); token was not displayed.")


if __name__ == "__main__":
    main()
