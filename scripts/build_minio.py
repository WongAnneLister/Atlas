"""Build the pinned MinIO runtime image locally when a remote Docker host lacks build space."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REVISION = "e1f26f7c8e7f06abfe1bc6c4023f6012e1d0aa9f"
SOURCE_SHA256 = "b33290f7078d81a029a62aebe10a07aeb005ae349f5854fd52c656c324a6de3e"


def main() -> None:
    go = shutil.which("go")
    if not go or "go1.23.4 " not in subprocess.check_output([go, "version"], text=True):
        raise RuntimeError("Put the official Go 1.23.4 toolchain on PATH first")
    cache = ROOT / ".cache/minio-build"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / "source.tar.gz"
    if not archive.exists():
        with httpx.stream(
            "GET", f"https://codeload.github.com/minio/minio/tar.gz/{REVISION}", timeout=60
        ) as response:
            response.raise_for_status()
            with archive.open("wb") as output:
                for piece in response.iter_bytes():
                    output.write(piece)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("Pinned MinIO source checksum mismatch")
    source = cache / f"minio-{REVISION}"
    if not (source / "go.mod").exists():
        with tarfile.open(archive) as bundle:
            bundle.extractall(cache, filter="data")
    runtime = cache / "runtime"
    runtime.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        GOOS="linux",
        GOARCH=os.environ.get("MINIO_TARGET_ARCH", "amd64"),
        CGO_ENABLED="0",
        GOMAXPROCS="2",
        GOMEMLIMIT="768MiB",
        GOPATH=str(cache / "go"),
        GOCACHE=str(cache / "go-build"),
        GOTMPDIR=str(cache / "tmp"),
    )
    (cache / "tmp").mkdir(exist_ok=True)
    subprocess.run(
        [go, "build", "-p", "1", "-trimpath", "-ldflags=-s -w", "-o", str(runtime / "minio"), "."],
        cwd=source,
        env=environment,
        check=True,
    )
    for name in ("LICENSE", "CREDITS"):
        shutil.copyfile(source / name, runtime / name)
    (runtime / "Dockerfile").write_text(
        "FROM alpine:3.21.3\nCOPY minio /usr/local/bin/minio\n"
        "RUN chmod +x /usr/local/bin/minio\nCOPY LICENSE CREDITS /licenses/\n"
        'ENTRYPOINT ["minio"]\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["docker", "build", "--tag", "support-agent-minio:2024-12-18", str(runtime)], check=True
    )


if __name__ == "__main__":
    main()
