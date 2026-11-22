"""Validate generated sections against original local inputs, not model claims."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict

import yaml

from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.build_docs import render_group, verify_inputs
from support_agent.data.doc_models import (
    BuildIndex,
    DocumentHeader,
    DocumentStats,
    Product,
    ValidationSummary,
    numeric_tokens,
)
from support_agent.data.faq_docs import deduplicate, load_faqs
from support_agent.data.policy_versions import PolicySection, docs_config_hash, load_versions
from support_agent.data.product_docs import extract_products, product_category, product_section_id
from support_agent.data.section_metadata import build_section_metadata, load_section_metadata

log = logging.getLogger(__name__)
SECTION = re.compile(r"^## ([^\n]+)\n<!-- section: ([^\n]+) -->\n(.*?)(?=^## |\Z)", re.M | re.S)


def parse_document(text: str) -> tuple[dict[str, str], DocumentHeader]:
    if not text.startswith("---\n"):
        raise ValueError("Missing YAML front matter")
    _, header, body = text.split("---\n", 2)
    metadata = DocumentHeader.model_validate(yaml.safe_load(header))
    matches = list(SECTION.finditer(body))
    if matches and body[: matches[0].start()].strip():
        raise ValueError("Unexpected prose outside sections")
    if body.count("\n## ") + int(body.startswith("## ")) != len(matches):
        raise ValueError("Every heading needs a section id")
    sections: dict[str, str] = {}
    for match in matches:
        sid, prose = match.group(2).strip(), match.group(3).strip()
        if sid in sections:
            raise ValueError(f"Duplicate section id: {sid}")
        if not re.sub(r"<!--.*?-->", "", prose, flags=re.S).strip():
            raise ValueError(f"Empty section: {sid}")
        sections[sid] = prose
    if not sections:
        raise ValueError("Document has no sections")
    return sections, metadata


def check_numbers(prose: str, source_text: str) -> None:
    extra = numeric_tokens(prose) - numeric_tokens(source_text)
    if extra:
        raise ValueError(f"Unsupported numbers: {sorted(extra)}")


def validate_docs(settings: Settings) -> ValidationSummary:
    processed = REPO_ROOT / settings.data.processed_dir
    docs_dir = processed / "docs"
    raw_dir = REPO_ROOT / settings.data.raw_dir
    index = BuildIndex.model_validate_json(
        (processed / "build_index.json").read_text(encoding="utf-8"),
    )
    built_at, input_hash = verify_inputs(settings)
    if (built_at, input_hash) != (index.built_at, index.input_hash):
        raise ValueError("Build inputs changed; run make data-docs")
    versions = load_versions(settings.policy_versions) if settings.policy_versions.enabled else None
    if index.config_hash != docs_config_hash(settings, versions):
        raise ValueError("Build config changed; run make data-docs")
    provenance = json.loads((docs_dir / "provenance.json").read_text(encoding="utf-8"))
    sections: dict[str, str] = {}
    section_documents: dict[str, str] = {}
    stats: list[DocumentStats] = []
    for path in sorted(docs_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        parsed, metadata = parse_document(text)
        if sections.keys() & parsed.keys():
            raise ValueError("Duplicate section id across documents")
        if metadata.doc_id != path.stem or metadata.built_at != built_at:
            raise ValueError(f"Incorrect metadata: {path.name}")
        sections.update(parsed)
        section_documents.update(dict.fromkeys(parsed, metadata.doc_id))
        stats.append(
            DocumentStats(
                doc_id=path.stem,
                sections=len(parsed),
                words=sum(len(prose.split()) for prose in parsed.values()),
            )
        )
    if sections.keys() != provenance.keys():
        raise ValueError("Provenance sections differ from rendered sections")
    faqs = load_faqs(raw_dir)
    known_ids = {f.source_id for f in faqs}
    if (index.assignments.keys() | index.excluded.keys()) != known_ids:
        raise ValueError("Every source FAQ needs an assignment or an exclusion reason")
    if index.assignments.keys() & index.excluded.keys():
        raise ValueError("A FAQ cannot be both covered and excluded")
    expected_sources: dict[str, list[str]] = defaultdict(list)
    originals: dict[str, list[str]] = defaultdict(list)
    covered = 0
    for faq in faqs:
        if faq.source_id in index.excluded:
            if faq.question and faq.answer:
                raise ValueError(f"Nonempty FAQ excluded: {faq.source_id}")
            continue
        sid = index.assignments[faq.source_id]
        prose = sections[sid]
        if (
            not faq.question
            or not faq.answer
            or faq.question not in prose
            or faq.answer not in prose
        ):
            raise ValueError(f"Source facts missing: {faq.source_id}")
        expected_sources[sid].append(faq.source_id)
        originals[sid].extend([faq.question, faq.answer])
        covered += 1
    for sid, sources in originals.items():
        check_numbers(sections[sid], "\n".join(sources))
    groups, excluded, counts = deduplicate(faqs, settings.data.docs.near_duplicate_threshold)
    if excluded != index.excluded or counts != index.dedupe_counts:
        raise ValueError("Dedupe audit differs from raw sources")
    expected_prose: dict[str, list[str]] = defaultdict(list)
    for group in groups:
        ids = {index.assignments[f.source_id] for f in group.records}
        if len(ids) != 1:
            raise ValueError("Duplicate group split across sections")
        expected_prose[ids.pop()].append(render_group(group))
    for sid, paragraphs in expected_prose.items():
        if sections[sid] != "\n\n".join(paragraphs):
            raise ValueError(f"Unexpected prose beyond source facts: {sid}")
    if versions is not None:
        bases = {
            sid: PolicySection(heading="", prose="\n\n".join(paragraphs))
            for sid, paragraphs in expected_prose.items()
        }
        historical = versions.apply_versions(bases)
        for entry in versions.entries:
            if sections[entry.old_id] != historical[entry.old_id].prose:
                raise ValueError(f"Unexpected synthetic policy text: {entry.old_id}")
            expected_sources[entry.old_id] = expected_sources[entry.base_section_id]
    products = [
        Product.model_validate_json(line)
        for line in (processed / "catalog/products.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if products != extract_products(raw_dir, settings.data.docs):
        raise ValueError("Catalog differs from source PDFs")
    catalog_categories: dict[str, str] = {}
    for product in products:
        sid = product_section_id(product.model)
        if sections[sid] != product.description:
            raise ValueError(f"Product text differs from source: {product.model}")
        expected_sources[sid].append(product.source_id)
        catalog_categories[sid] = product_category(product.model, settings.data.docs)
    if {k: sorted(v) for k, v in expected_sources.items()} != provenance:
        raise ValueError("Incorrect source-to-section provenance")
    expected_metadata = build_section_metadata(
        {sid: section_documents[sid] for sid in expected_prose},
        catalog_categories,
        settings.policy_versions.default_effective_from,
        versions,
    )
    if load_section_metadata(docs_dir) != expected_metadata:
        raise ValueError(
            "Section metadata differs from the source and policy version configuration"
        )
    coverage = covered / len(faqs) if faqs else 0.0
    if coverage < settings.data.docs.minimum_coverage:
        raise ValueError(f"FAQ coverage below configured minimum: {coverage:.2%}")
    return ValidationSummary(
        documents=stats,
        source_faqs=len(faqs),
        covered_faqs=covered,
        coverage=coverage,
        products=len(products),
        sections=len(sections),
        excluded=index.excluded,
        dedupe_counts=index.dedupe_counts,
        topic_methods=index.topic_methods,
    )


def summary_table(summary: ValidationSummary) -> str:
    lines = ["| Document | Sections | Words |", "|---|---:|---:|"]
    lines.extend(f"| {d.doc_id} | {d.sections} | {d.words} |" for d in summary.documents)
    lines.append(
        f"\nFAQ coverage: {summary.covered_faqs}/{summary.source_faqs} ({summary.coverage:.2%}).",
    )
    lines.append(f"Products: {summary.products}. Sections: {summary.sections}.")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        summary = validate_docs(get_settings())
    except (OSError, ValueError, KeyError) as exc:
        log.error("validation failed: %s", exc)
        return 1
    log.info("\n%s", summary_table(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
