from __future__ import annotations

import json
import shlex

import yaml

from support_agent.config import REPO_ROOT


def test_minio_entrypoint_receives_server_subcommand() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    dockerfile = (REPO_ROOT / "docker/minio/Dockerfile").read_text(encoding="utf-8")
    entrypoint = json.loads(dockerfile.split("ENTRYPOINT ")[-1].strip())
    command = compose["services"]["minio"]["command"]
    arguments = shlex.split(command) if isinstance(command, str) else command
    invocation = [*entrypoint, *arguments]
    assert invocation[0] == "minio"
    assert invocation[1] == "server", "The custom image must receive the server subcommand"
