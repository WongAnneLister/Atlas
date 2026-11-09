"""Contrastive questions about differing, source-supported attributes of look-alike models."""

from __future__ import annotations

import re
from itertools import combinations

from eval.faq_candidates import candidate
from eval.schema import Candidate, Fact, Section
from support_agent.config import REPO_ROOT, Settings
from support_agent.data.doc_models import Product
from support_agent.data.product_docs import product_section_id


def facts(product: Product) -> dict[str, Fact]:
    found: dict[str, Fact] = {}
    for key, label in [
        ("Wattage", "wattage"),
        ("Nozzle", "nozzle width"),
        ("Heat/Speed settings", "heat/speed setting count"),
    ]:
        value = product.attributes.get(key)
        evidence = f"{key}: {value}"
        if value is not None and evidence in product.description:
            found[label] = Fact(label=label, value=value, evidence=evidence)
    patterns = {
        "series": r"\b\d{4} Series\b",
        "care technology": r"ThermoProtect attachment|ThermoShield technology",
        "temperature reduction": (
            r"It drops the temperature by \d+°C while still drying your hair quickly\."
        ),
    }
    for label, pattern in patterns.items():
        match = re.search(pattern, product.description)
        if match:
            found[label] = Fact(label=label, value=match.group(), evidence=match.group())
    return found


def product_candidates(settings: Settings, sections: dict[str, Section]) -> list[Candidate]:
    path = REPO_ROOT / settings.data.processed_dir / "catalog/products.jsonl"
    products = [
        Product.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    result: list[Candidate] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for target in products:
        target_facts = facts(target)
        for other in products:
            # A shared alphabetic model prefix defines look-alikes; no synthetic products.
            prefix = re.match(r"[A-Za-z]+", target.model)
            if (
                target.model == other.model
                or prefix is None
                or not other.model.startswith(prefix.group())
            ):
                continue
            other_facts = facts(other)
            different = sorted(
                label
                for label, fact in target_facts.items()
                if label in other_facts and fact.value != other_facts[label].value
            )
            for size in range(1, min(settings.evaluation.max_model_attributes, len(different)) + 1):
                for labels in combinations(different, size):
                    key = (target.model, labels)
                    if key in seen:
                        continue
                    sid = product_section_id(target.model)
                    points = [target_facts[label].evidence for label in labels]
                    if sid not in sections or any(
                        point not in sections[sid].text for point in points
                    ):
                        raise ValueError(f"Unsupported catalog facts: {target.model}")
                    seen.add(key)
                    question = (
                        f"I mean {target.model}, rather than {other.model}. "
                        f"What are its {', '.join(labels)}?"
                    )
                    result.append(
                        candidate(
                            "model_number",
                            question,
                            [sid],
                            points,
                            f"product:{target.product_id}|contrast:{other.model}",
                            f"product:{target.model}:{'|'.join(labels)}",
                            "All requested attributes differ from the named look-alike; "
                            "target-only answer.",
                        )
                    )
    return result
