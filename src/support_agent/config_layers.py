"""Layer environment YAML over the base configuration."""

from pathlib import Path
from typing import Any

import yaml


def _read(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a settings mapping in {path}")
    return data


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = base.copy()
    for key, value in overlay.items():
        original = merged.get(key)
        merged[key] = (
            deep_merge(original, value)
            if isinstance(original, dict) and isinstance(value, dict)
            else value
        )
    return merged


def yaml_layers(base: Path, config_dir: Path, environment: str) -> dict[str, Any]:
    if environment not in {"local", "dev", "prod"}:
        raise ValueError("ENV must be local, dev or prod")
    settings = _read(base)
    if environment != "local":
        settings = deep_merge(settings, _read(config_dir / f"{environment}.yaml"))
    return settings
