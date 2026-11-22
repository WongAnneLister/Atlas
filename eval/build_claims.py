"""Build and register a local claim set from explicit saved E2E runs."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from random import Random

from eval.claim_perturbations import Perturbations
from eval.claims import extract_claims
from eval.common import load_sections
from eval.e2e_runs import load_e2e
from eval.registry import bump, file_hash, inspect_dataset, load_registry, write_registry
from eval.schema import ClaimItem, Section, Split
from support_agent.config import REPO_ROOT, get_settings
from support_agent.data.doc_models import digest, json_text, write_text

NAME = "claims_v1"
CLAIMS_PATH = REPO_ROOT / "eval/sets/claims_v1.jsonl"
PROVENANCE_PATH = REPO_ROOT / "eval/sets/claims_v1_sources.json"
SPLITS: tuple[Split, ...] = ("dev", "test")


def _real_sample(items: list[ClaimItem], cap: int, target: int, rng: Random) -> list[ClaimItem]:
    candidates = sorted(items, key=lambda item: item.id)
    rng.shuffle(candidates)
    selected = []
    counts: Counter[str] = Counter()
    seen: set[tuple[str, str]] = set()
    for item in candidates:
        key = (item.source_item, " ".join(item.claim.casefold().split()))
        if counts[item.source_item] >= cap or key in seen:
            continue
        counts[item.source_item] += 1
        seen.add(key)
        selected.append(item)
        if len(selected) == target:
            break
    return selected


def _synthetic_sample(
    real: list[ClaimItem], perturbations: Perturbations, quota: int, rng: Random
) -> list[ClaimItem]:
    candidates = [
        (item, kind, text)
        for item in real
        for kind, text in perturbations.variants(item, rng)
        if text != item.claim
    ]
    rng.shuffle(candidates)
    selected = []
    seen: set[tuple[str, str]] = set()
    for item, kind, text in candidates:
        key = (item.source_item, text)
        if key in seen:
            continue
        seen.add(key)
        selected.append(
            ClaimItem(
                **{
                    **item.model_dump(),
                    "id": f"synthetic-{item.split}-{digest(f'{item.id}:{kind}:{text}')}",
                    "group": "synthetic",
                    "claim": text,
                    "label": None,
                    "label_source": "construction",
                    "perturbation": kind,
                    "reviewed": False,
                    "note": "",
                }
            )
        )
        if len(selected) == quota:
            break
    return selected


def build_claim_set(
    claims: Sequence[ClaimItem],
    sections: dict[str, Section],
    *,
    seed: int,
    real_targets: dict[Split, int],
    synthetic_per_split: int,
    cap: int,
    support_overlap: float,
    splits: Sequence[Split] = SPLITS,
) -> list[ClaimItem]:
    if any(item.group != "real" for item in claims) or len({c.id for c in claims}) != len(claims):
        raise ValueError("Expected distinct extracted real claims")
    output: list[ClaimItem] = []
    perturbations = Perturbations(sections, support_overlap)
    for split in splits:
        rng = Random(f"{seed}:{split}")
        real = _real_sample(
            [item for item in claims if item.split == split], cap, real_targets[split], rng
        )
        if len(real) < real_targets[split]:
            raise ValueError(f"{split}: need {real_targets[split]} real claims, found {len(real)}")
        synthetic = _synthetic_sample(real, perturbations, synthetic_per_split, rng)
        if len(synthetic) < synthetic_per_split:
            raise ValueError(
                f"{split}: need {synthetic_per_split} synthetic claims, found {len(synthetic)}"
            )
        output.extend(real)
        output.extend(synthetic)
    return output


def read_claims(path: Path = CLAIMS_PATH) -> list[ClaimItem]:
    return [
        ClaimItem.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def publish_claims(items: list[ClaimItem], *, version: str | None, note: str) -> None:
    entries = load_registry()
    entry = entries.get(NAME)
    data = "".join(f"{item.model_dump_json()}\n" for item in items)
    if not items or len({item.id for item in items}) != len(items):
        raise ValueError("Claim set must contain distinct items")
    if entry is not None and digest(data) == entry.sha256:
        if not CLAIMS_PATH.is_file() or file_hash(CLAIMS_PATH) != entry.sha256:
            if CLAIMS_PATH.exists():
                raise ValueError("Local claim set differs from the registry")
            write_text(CLAIMS_PATH, data)
        return
    if entry is not None and (
        not version
        or not version.startswith("v")
        or not version[1:].isdecimal()
        or int(version[1:]) <= int(entry.version[1:])
    ):
        raise ValueError(f"Changing {NAME} requires --version higher than {entry.version}")
    if entry is None and version not in {None, "v1"}:
        raise ValueError("The first claim set must be v1")
    write_text(CLAIMS_PATH, data)
    entries[NAME] = (
        bump(entry, version, note)
        if entry is not None and version is not None
        else inspect_dataset(CLAIMS_PATH, name=NAME, version="v1", changelog=[note])
    )
    write_registry(entries)


def _read_runs(
    paths: Sequence[Path], splits: Sequence[Split]
) -> tuple[list[ClaimItem], list[dict[str, object]]]:
    claims: list[ClaimItem] = []
    provenance: list[dict[str, object]] = []
    for path in sorted({path.resolve() for path in paths}):
        source_run = path.relative_to(REPO_ROOT).as_posix()
        metadata, records = load_e2e(path)
        if metadata.split == "all" or metadata.split not in splits:
            raise ValueError(f"{source_run}: expected a run restricted to one requested split")
        if any(record.item.split != metadata.split for record in records):
            raise ValueError(f"{source_run}: row split disagrees with the run")
        files = [path / "manifest.json", path / "items.jsonl"] if path.is_dir() else [path]
        provenance.append(
            {
                "path": source_run,
                "split": metadata.split,
                "git_sha": metadata.git_sha,
                "config_hash": metadata.config_hash,
                "models": metadata.models,
                "dataset_versions": metadata.dataset_versions,
                "date": metadata.date,
                "hashes": {
                    file.relative_to(REPO_ROOT).as_posix(): file_hash(file) for file in files
                },
            }
        )
        for record in records:
            claims.extend(extract_claims(record, source_run))
    return claims, provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--split", choices=("all", *SPLITS), default="all")
    parser.add_argument("--version", help="New registry version when changing an existing set")
    args = parser.parse_args(argv)
    settings = get_settings()
    config = settings.eval.claims
    splits = [split for split in SPLITS if args.split in {"all", split}]
    try:
        claims, provenance = _read_runs(args.run, splits)
        sections = load_sections(settings)
        items = build_claim_set(
            claims,
            sections,
            seed=config.seed,
            real_targets={"dev": config.dev_target, "test": config.test_target},
            synthetic_per_split=config.synthetic_per_split,
            cap=config.max_per_item,
            support_overlap=settings.evaluation.phrase_overlap,
            splits=splits,
        )
        publish_claims(
            items, version=args.version, note=f"Build claim set for {' and '.join(splits)}."
        )
        write_text(
            PROVENANCE_PATH,
            json_text(
                {
                    "unlabelled_dataset_sha256": file_hash(CLAIMS_PATH),
                    "sampling": {
                        **config.model_dump(),
                        "support_overlap": settings.evaluation.phrase_overlap,
                    },
                    "corpus_sha256": digest(
                        json_text({key: value.model_dump() for key, value in sections.items()})
                    ),
                    "runs": provenance,
                }
            ),
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    sys.stdout.write(f"Wrote {len(items)} claims to {CLAIMS_PATH}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
