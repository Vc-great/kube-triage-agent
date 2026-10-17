"""Run a selected Compose stack with Langfuse when root .env has valid keys."""

import os
import re
import sys

from dev import ENV_FILE, read_langfuse_env

STACK_FILES = {
    "formal": ("infra/compose.yaml",),
    "dev01": ("infra/compose.yaml", "infra/dev01.compose.yaml"),
    "test": ("infra/test.compose.yaml",),
}


def compose_invocation(stack, project, args, host_env=None):
    """Return Docker argv and a credential-scoped environment without printing keys."""
    if stack not in STACK_FILES or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", project):
        raise RuntimeError("COMPOSE_ARGUMENT_INVALID：项目或配置类型错误。")
    credentials = read_langfuse_env(ENV_FILE, optional=True)
    source = os.environ if host_env is None else host_env
    environment = {key: value for key, value in source.items()
                   if key not in {"LANGFUSE_SECRET_KEY", "LANGFUSE_PUBLIC_KEY",
                                  "LANGFUSE_BASE_URL", "KTA_LANGFUSE_PROXY_URL"}}
    environment.update(credentials)
    if credentials and stack == "dev01":
        environment["KTA_LANGFUSE_PROXY_URL"] = "http://192.168.31.110:7890"
    command = ["docker", "compose", "-p", project, "--env-file", str(ENV_FILE)]
    for file in STACK_FILES[stack]:
        command.extend(("-f", file))
    if credentials:
        command.extend(("-f", "infra/langfuse.compose.yaml"))
    command.extend(args)
    return command, environment


def main():
    if len(sys.argv) < 4:
        raise RuntimeError("COMPOSE_ARGUMENT_INVALID：缺少配置类型、项目或命令。")
    command, environment = compose_invocation(sys.argv[1], sys.argv[2], sys.argv[3:])
    os.chdir(ENV_FILE.parent)
    os.execvpe("docker", command, environment)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(error, file=sys.stderr)
        raise SystemExit(2) from None
