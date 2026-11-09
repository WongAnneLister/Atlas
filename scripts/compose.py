"""Run the Compose plugin or the official standalone CLI, without changing Docker context."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def command() -> list[str]:
    docker = shutil.which("docker")
    if (
        docker
        and subprocess.run([docker, "compose", "version"], capture_output=True).returncode == 0
    ):
        return [docker, "compose"]
    standalone = shutil.which("docker-compose")
    if standalone:
        return [standalone]
    raise RuntimeError("Install the Docker Compose plugin or official docker-compose CLI")


def main() -> int:
    try:
        return subprocess.call([*command(), *sys.argv[1:]], cwd=Path(__file__).resolve().parents[1])
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
