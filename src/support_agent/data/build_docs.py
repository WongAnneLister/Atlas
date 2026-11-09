"""Build extractive policy documents and a catalog. Run with make data-docs."""

from __future__ import annotations

import logging
import re
from collections import defaultdict

import yaml

from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import BuildIndex, FAQGroup, digest, json_text, write_text
from support_agent.data.faq_docs import TopicClassifier, deduplicate, load_faqs
from support_agent.data.manifest import is_current, load_manifest
from support_agent.data.product_docs import extract_products, product_category, product_section_id

log = logging.getLogger(__name__)


def section_id(topic: str, group: FAQGroup) -> str:
    faq = group.records[0]
    slug = re.sub(r"[^a-z0-9]+", "-", faq.category.lower()).strip("-")
    # Full category digest avoids collisions after punctuation stripping.
    return f"{topic}.{faq.dataset}.{slug}.{digest(faq.category)}"


def document(doc_id: str, sources: list[str], built_at: str, sections: list[str]) -> str:
    header = yaml.safe_dump(
        {
            "doc_id": doc_id,
            "title": doc_id.replace("_", " ").title(),
            "source_datasets": sorted(sources),
            "built_at": built_at,
        },
        sort_keys=True,
        allow_unicode=True,
    ).strip()
    return f"---\n{header}\n---\n\n" + "\n\n".join(sections) + "\n"


def render_group(group: FAQGroup) -> str:
    questions = sorted({f.question for f in group.records})
    context = " / ".join(f"“{q}”" for q in questions)
    # Extractive prose avoids changing conditions, amounts or promises.
    return f"Regarding {context}:\n\n{group.records[0].answer}"


def verify_inputs(settings: Settings) -> tuple[str, str]:
    raw_dir = REPO_ROOT / settings.data.raw_dir
    manifest = load_manifest(raw_dir)
    names = {"flipkart_faqs", "maktek_faqs", "philips_manuals"}
    for name in sorted(names):
        source = next(s for s in settings.data.sources if s.name == name)
        if not is_current(manifest.sources.get(name), source.revision, raw_dir / name):
            raise ValueError(f"Missing or changed raw source {name}; run make data-download")
    records = {name: manifest.sources[name].model_dump() for name in sorted(names)}
    built_at = max(manifest.sources[name].downloaded_at for name in names)
    return built_at, digest(json_text(records))


def build_docs(settings: Settings) -> BuildIndex:
    built_at, input_hash = verify_inputs(settings)
    raw_dir = REPO_ROOT / settings.data.raw_dir
    processed = REPO_ROOT / settings.data.processed_dir
    docs_dir = processed / "docs"
    # Refuse to erase user files; only replace files from a previous build index.
    previous = processed / "document_files.json"
    if previous.exists():
        import json

        for name in json.loads(previous.read_text(encoding="utf-8")):
            path = docs_dir / name
            if path.parent.resolve() != docs_dir.resolve() or path.suffix != ".md":
                raise ValueError("Unsafe previous document path")
            path.unlink(missing_ok=True)
    groups, excluded, counts = deduplicate(
        load_faqs(raw_dir),
        settings.data.docs.near_duplicate_threshold,
    )
    classifier = TopicClassifier(settings, processed / "topic_cache.jsonl")
    buckets: dict[str, dict[str, list[FAQGroup]]] = defaultdict(lambda: defaultdict(list))
    index = BuildIndex(
        built_at=built_at,
        input_hash=input_hash,
        config_hash=digest(json_text(settings.model_dump(mode="json"))),
        excluded=excluded,
        dedupe_counts=counts,
    )
    provenance: dict[str, list[str]] = {}
    for group in groups:
        topic = classifier.classify(group.records[0])
        sid = section_id(topic, group)
        buckets[topic][sid].append(group)
        for faq in group.records:
            index.assignments[faq.source_id] = sid
    classifier.save()
    index.topic_methods = dict(classifier.methods)
    index.topic_models = sorted(classifier.models)
    files: list[str] = []
    for topic, sections in sorted(buckets.items()):
        rendered: list[str] = []
        sources: set[str] = set()
        for sid, section_groups in sorted(sections.items()):
            faq = section_groups[0].records[0]
            rendered.append(
                f"## {faq.dataset} / {faq.category}\n<!-- section: {sid} -->\n\n"
                + "\n\n".join(render_group(g) for g in section_groups)
            )
            provenance[sid] = sorted(f.source_id for g in section_groups for f in g.records)
            sources.update(f.dataset for g in section_groups for f in g.records)
        files.append(f"{topic}.md")
        write_text(docs_dir / files[-1], document(topic, sorted(sources), built_at, rendered))
    products = extract_products(raw_dir, settings.data.docs)
    catalogs: dict[str, list[str]] = defaultdict(list)
    for product in products:
        sid = product_section_id(product.model)
        catalogs[product_category(product.model, settings.data.docs)].append(
            f"## {product.name}\n<!-- section: {sid} -->\n\n{product.description}"
        )
        provenance[sid] = [product.source_id]
    for category, sections_list in sorted(catalogs.items()):
        doc_id = f"catalog_{category}"
        files.append(f"{doc_id}.md")
        write_text(
            docs_dir / files[-1],
            document(
                doc_id,
                ["philips_manuals"],
                built_at,
                sections_list,
            ),
        )
    write_text(
        processed / "catalog/products.jsonl",
        "".join(p.model_dump_json() + "\n" for p in products),
    )
    write_text(docs_dir / "provenance.json", json_text(provenance))
    write_text(processed / "build_index.json", index.model_dump_json(indent=2) + "\n")
    write_text(previous, json_text(sorted(files)))
    log.info("built %d documents and %d products", len(files), len(products))
    return index


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        build_docs(get_settings())
    except (OSError, ValueError) as exc:
        log.error("document build failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
