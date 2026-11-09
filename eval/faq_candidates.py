"""FAQ candidates with code-owned gold labels and real Bitext phrasing prefixes."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict

from eval.common import normalised
from eval.schema import Candidate, EvalItem, Group, Section
from support_agent.config import REPO_ROOT, Settings
from support_agent.data.doc_models import FAQ, digest
from support_agent.data.faq_docs import load_faqs

# Match the requested operation, not Bitext responses or invented policy answers.
INTENT_RULES = {
    "check_refund_policy": r"refund|return|exchange|replacement",
    "check_payment_methods": r"payment|pay\b|credit card|debit card|paypal",
    "delivery_period": r"how long.*ship|shipping.*take|deliver.*time|delivery.*time",
    "delivery_options": r"shipping|delivery|courier|package|pickup",
    "recover_password": r"password",
    "create_account": r"account|register|sign up|registration",
    "newsletter_subscription": r"newsletter|subscrib",
    "contact_customer_service": r"contact|customer support|customer service",
    "get_invoice": r"invoice|receipt",
    "cancel_order": r"cancel",
    "change_order": r"change.*order|modify.*order",
}


def candidate(
    group: Group,
    question: str,
    gold: list[str],
    points: list[str],
    source: str,
    family: str,
    notes: str = "",
    key_terms: list[str] | None = None,
) -> Candidate:
    return Candidate(
        item=EvalItem(
            id=f"{group}-{digest(question)}",
            group=group,
            split="dev",
            question=question,
            gold_sections=gold,
            answer_points=points,
            answerable=group != "no_answer",
            source=source,
            reviewed=False,
            notes=notes,
        ),
        family=family,
        key_terms=key_terms or [],
    )


def source_faqs(settings: Settings, sections: dict[str, Section]) -> list[tuple[FAQ, str]]:
    folder = REPO_ROOT / settings.data.processed_dir
    provenance = json.loads((folder / "docs/provenance.json").read_text(encoding="utf-8"))
    reverse = {source: sid for sid, sources in provenance.items() for source in sources}
    found: list[tuple[FAQ, str]] = []
    seen: set[str] = set()
    for faq in load_faqs(REPO_ROOT / settings.data.raw_dir):
        sid = reverse.get(faq.source_id)
        if (
            sid is None
            or sid not in sections
            or sections[sid].doc_id not in settings.evaluation.policy_topics
        ):
            continue
        if faq.dataset == "flipkart_faqs" and not any(
            faq.category.endswith("/ " + category)
            for category in settings.evaluation.faq_categories
        ):
            continue
        key = normalised(faq.question + " " + faq.answer)
        if key in seen:
            continue
        if faq.question not in sections[sid].text or faq.answer not in sections[sid].text:
            raise ValueError(f"FAQ text missing from its gold section: {faq.source_id}")
        seen.add(key)
        found.append((faq, sid))
    return found


def bitext_phrasings(settings: Settings) -> dict[str, list[tuple[str, str]]]:
    source = next(s for s in settings.data.sources if s.name == "bitext")
    path = REPO_ROOT / settings.data.raw_dir / source.name / source.files[0]
    phrasings: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            if row["intent"] not in INTENT_RULES or not {"Q", "Z"} & set(row["flags"]):
                continue
            # Select actual utterances without identifiers or unresolved placeholders.
            utterance = row["instruction"].strip()
            if "{{" not in utterance:
                phrasings[row["intent"]].append((utterance, f"bitext:{index}"))
    return phrasings


def faq_candidates(settings: Settings, sections: dict[str, Section]) -> list[Candidate]:
    phrasings = bitext_phrasings(settings)
    result: list[Candidate] = []
    for faq, sid in source_faqs(settings, sections):
        scope = "Flipkart" if faq.dataset == "flipkart_faqs" else "the generic store"
        question = f"For {scope}: {faq.question}"
        family = "faq:" + digest(normalised(faq.question))
        result.append(
            candidate("basic_policy", question, [sid], [faq.answer], "faq:" + faq.source_id, family)
        )
        intent = next(
            (
                name
                for name, pattern in INTENT_RULES.items()
                if re.search(pattern, faq.question, re.I) and phrasings[name]
            ),
            None,
        )
        if intent is not None:
            options = phrasings[intent]
            offset = int(digest(faq.source_id), 16) % len(options)
            phrase, bitext_id = options[offset]
            colloquial = f"{phrase} — for {scope}, specifically: {faq.question.lower()}"
            result.append(
                candidate(
                    "colloquial",
                    colloquial,
                    [sid],
                    [faq.answer],
                    f"faq:{faq.source_id}|{bitext_id}:{intent}",
                    family,
                    "Real Bitext prefix; explicit FAQ context preserves the requested fact.",
                )
            )
    return result
