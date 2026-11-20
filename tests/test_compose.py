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


def test_state_services_are_healthy_and_loopback_only() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    postgres = compose["services"]["postgres"]
    redis = compose["services"]["redis"]
    assert postgres["ports"] == ["127.0.0.1:${ATLAS_POSTGRES_PORT:-5433}:5432"]
    assert redis["ports"] == ["127.0.0.1:${ATLAS_REDIS_PORT:-6379}:6379"]
    assert "@localhost:5433/support" in example
    assert "redis://localhost:6379/0" in example
    assert "postgres_data:/var/lib/postgresql/data" in postgres["volumes"]
    assert "postgres_data" in compose["volumes"]
    assert "pg_isready" in " ".join(postgres["healthcheck"]["test"])
    assert redis["healthcheck"]["test"] == ["CMD", "redis-cli", "ping"]
