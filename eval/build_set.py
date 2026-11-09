"""Build and freeze version-one drafts before retrieval exists. Run make eval-build."""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from pathlib import Path

from eval.common import load_items, load_sections, save_items, set_hash
from eval.drafter import Drafter
from eval.faq_candidates import faq_candidates
from eval.generated_candidates import generated_candidates
from eval.product_candidates import product_candidates
from eval.split_set import sample_split
from eval.validate_set import validate_items
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import digest, json_text, write_text
from support_agent.data.manifest import is_current, load_manifest, sha256_file

log = logging.getLogger(__name__)


def input_metadata(settings: Settings) -> dict[str, object]:
    sections = load_sections(settings)
    manifest = load_manifest(REPO_ROOT / settings.data.raw_dir)
    versions: dict[str, str] = {}
    for source in settings.data.sources:
        if not is_current(
            manifest.sources.get(source.name),
            source.revision,
            REPO_ROOT / settings.data.raw_dir / source.name,
        ):
            raise ValueError(f"Changed raw source {source.name}; run make data-download")
        versions[source.name] = f"{source.repo_id}@{source.revision}"
    processed = REPO_ROOT / settings.data.processed_dir
    return {
        "corpus_hash": digest(json_text([s.model_dump() for s in sections.values()])),
        "products_hash": sha256_file(processed / "catalog/products.jsonl"),
        "provenance_hash": sha256_file(processed / "docs/provenance.json"),
        "raw_hash": digest(manifest.model_dump_json()),
        "dataset_versions": versions,
        "eval_config": settings.evaluation.model_dump(mode="json"),
        "absent_drafts_hash": sha256_file(REPO_ROOT / settings.evaluation.no_answer_drafts),
    }


def build(settings: Settings) -> Path:
    folder = REPO_ROOT / settings.evaluation.sets_dir
    output = folder / "eval_v1.jsonl"
    manifest_path = folder / "manifest.json"
    metadata = input_metadata(settings)
    fingerprint = digest(json_text(metadata))
    if output.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        items = load_items(output)
        if previous["input_fingerprint"] != fingerprint or previous["set_hash"] != set_hash(items):
            raise ValueError(
                "Frozen eval inputs/labels changed; use a new sets_dir for a new version"
            )
        failures = validate_items(items, load_sections(settings), settings.evaluation)
        if failures:
            raise ValueError("\n".join(failures))
        log.info("reuse frozen evaluation set; review flags preserved")
        return output
    sections = load_sections(settings)
    drafter = Drafter(settings, folder / "draft_cache.json")
    generated, audit = generated_candidates(settings, sections, drafter)
    candidates = (
        faq_candidates(settings, sections) + product_candidates(settings, sections) + generated
    )
    write_text(folder / "candidates.jsonl", "".join(c.model_dump_json() + "\n" for c in candidates))
    log.info("draft pool: %s", dict(Counter(c.item.group for c in candidates)))
    items, split_audit = sample_split(candidates, settings.evaluation)
    failures = validate_items(items, sections, settings.evaluation)
    if failures:
        raise ValueError("\n".join(failures))
    save_items(output, items)
    write_text(
        manifest_path,
        json_text(
            {
                **metadata,
                "input_fingerprint": fingerprint,
                "set_hash": set_hash(items),
                "candidate_counts": dict(Counter(c.item.group for c in candidates)),
                "draft_mode": settings.evaluation.draft_mode,
                "draft_model": (os.environ.get("LLM_FAST_MODEL") or settings.llm.fast_model)
                if settings.evaluation.draft_mode == "fast"
                else None,
                "audit": {**audit, **split_audit},
            }
        ),
    )
    log.info("froze %d unreviewed questions at %s", len(items), output)
    return output


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        build(get_settings())
    except (OSError, ValueError) as exc:
        log.error("eval build failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
