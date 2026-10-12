#!/usr/bin/env python3
"""Manually issue a short-lived project SA token and write a single-context kubeconfig."""

import argparse
import base64
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "kube-triage-demo"
ACCOUNT = "kube-triage-reader"
REPAIR_ACCOUNT = "kube-triage-repairer"
REMOTE_SOURCE = r'''
import base64
import json
import pathlib
import subprocess
import sys

try:
    account = sys.argv[1]
    if account not in {"kube-triage-reader", "kube-triage-repairer"}:
        raise ValueError("unexpected account")
    source = json.loads(subprocess.check_output(
        ["kubectl", "config", "view", "--raw", "--minify", "-o", "json"],
        stderr=subprocess.DEVNULL, text=True))
    cluster = source["clusters"][0]["cluster"]
    ca = cluster.get("certificate-authority-data")
    if not ca and cluster.get("certificate-authority"):
        path = pathlib.Path(cluster["certificate-authority"])
        if not path.is_absolute():
            path = pathlib.Path.home() / ".kube" / path
        ca = base64.b64encode(path.read_bytes()).decode()
    if (not cluster["server"].startswith("https://") or not ca or
            cluster.get("insecure-skip-tls-verify", False)):
        raise ValueError("trusted HTTPS cluster required")
    token = subprocess.check_output(
        ["kubectl", "-n", "kube-triage-demo", "create", "token",
         account, "--duration=24h"],
        stderr=subprocess.DEVNULL, text=True).strip()
    print(json.dumps({"server": cluster["server"], "ca": ca,
                      "insecure": cluster.get("insecure-skip-tls-verify", False),
                      "token": token}))
except Exception:
    print("SSH kubeconfig source failed", file=sys.stderr)
    sys.exit(1)
'''


def kubectl(*args: str) -> str:
    return subprocess.check_output(["kubectl", *args], text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--context", help="Confirmed local bootstrap context")
    source_group.add_argument("--ssh-host", help="Confirmed SSH management host")
    parser.add_argument("--account", choices=[ACCOUNT, REPAIR_ACCOUNT], default=ACCOUNT)
    parser.add_argument("--confirm", required=True,
                        help="Type source/namespace (repairer also requires /account)")
    args = parser.parse_args()
    source_name = args.context or args.ssh_host
    expected = f"{source_name}/{NAMESPACE}"
    if args.account == REPAIR_ACCOUNT:
        expected += f"/{REPAIR_ACCOUNT}"
    if args.confirm != expected:
        parser.error("context/namespace confirmation did not match")
    if args.ssh_host:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.ssh_host):
            parser.error("SSH host must be a simple host name or alias")
        response = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", args.ssh_host, "python3", "-", args.account],
            input=REMOTE_SOURCE, capture_output=True, text=True, check=False)
        if response.returncode:
            parser.error("SSH kubeconfig source failed; no credential was written")
        data = json.loads(response.stdout)
        server, ca, token = data["server"], data["ca"], data["token"]
        insecure = data["insecure"]
    else:
        source = json.loads(kubectl("config", "view", "--raw", "--minify",
                                    "--context", args.context, "-o", "json"))
        cluster = source["clusters"][0]["cluster"]
        server = cluster["server"]
        ca = cluster.get("certificate-authority-data")
        if not ca and cluster.get("certificate-authority"):
            ca_path = Path(cluster["certificate-authority"])
            if not ca_path.is_absolute():
                source_file = Path(os.environ.get("KUBECONFIG", str(Path.home() / ".kube/config"))
                                   .split(os.pathsep)[0])
                ca_path = source_file.parent / ca_path
            ca = base64.b64encode(ca_path.read_bytes()).decode()
        token = kubectl("--context", args.context, "-n", NAMESPACE, "create", "token",
                        args.account, "--duration=24h")
        insecure = cluster.get("insecure-skip-tls-verify", False)
    if not server.startswith("https://"):
        parser.error("Kubernetes API server must use HTTPS")
    if not ca or insecure:
        parser.error("trusted CA data is required; insecure TLS is forbidden")
    if not token:
        raise RuntimeError("kubectl returned an empty token")
    config = {
        "apiVersion": "v1", "kind": "Config", "current-context": args.account,
        "clusters": [{"name": "target", "cluster": {
            "server": server, "certificate-authority-data": ca}}],
        "users": [{"name": args.account, "user": {"token": token}}],
        "contexts": [{"name": args.account, "context": {
            "cluster": "target", "user": args.account, "namespace": NAMESPACE}}],
    }
    directory = ROOT / ".local"
    if directory.is_symlink():
        parser.error(".local must be a real project directory")
    directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    with tempfile.NamedTemporaryFile("w", dir=directory, prefix=".kubeconfig-",
                                     delete=False, encoding="utf-8") as output:
        os.chmod(output.name, 0o600)
        json.dump(config, output, indent=2)
        temporary = Path(output.name)
    destination = "repair-kubeconfig" if args.account == REPAIR_ACCOUNT else "kubeconfig"
    temporary.replace(directory / destination)
    print(f"Wrote project-only .local/{destination} (mode 0600); token was not displayed.")


if __name__ == "__main__":
    main()
