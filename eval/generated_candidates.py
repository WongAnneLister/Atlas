"""Draft multi-document and absent-topic questions; code owns all evidence labels."""

from __future__ import annotations

import random
from itertools import combinations

import yaml
from pydantic import BaseModel

from eval.common import term_present
from eval.drafter import Drafter
from eval.faq_candidates import candidate, source_faqs
from eval.schema import Candidate, Section
from support_agent.config import REPO_ROOT, Settings
from support_agent.data.doc_models import digest


class AbsentTopicGroup(BaseModel):
    template: str
    terms: list[str]


class AbsentTopics(BaseModel):
    groups: list[AbsentTopicGroup]


def generated_candidates(
    settings: Settings,
    sections: dict[str, Section],
    drafter: Drafter,
) -> tuple[list[Candidate], dict[str, int]]:
    faqs = source_faqs(settings, sections)
    pairs = [
        (a, b)
        for a, b in combinations(faqs, 2)
        if a[0].dataset == b[0].dataset and sections[a[1]].doc_id != sections[b[1]].doc_id
    ]
    random.Random(settings.evaluation.seed).shuffle(pairs)
    result: list[Candidate] = []
    for (first, sid_a), (second, sid_b) in pairs[: settings.evaluation.cross_doc_candidates]:
        scope = "Flipkart" if first.dataset == "flipkart_faqs" else "the generic store"
        question = f"For {scope}, {first.question} Also, {second.question}"
        question = drafter.question(question, {"first": first.answer, "second": second.answer})
        result.append(
            candidate(
                "cross_doc",
                question,
                [sid_a, sid_b],
                [first.answer, second.answer],
                f"gen:cross_doc:v1|{first.source_id}|{second.source_id}",
                "pair:" + digest(first.source_id + "|" + second.source_id),
                "Code chose same-store sources from different documents; draft needs human review.",
            )
        )
    drafts = AbsentTopics.model_validate(
        yaml.safe_load(
            (REPO_ROOT / settings.evaluation.no_answer_drafts).read_text(encoding="utf-8"),
        )
    )
    corpus = "\n".join(section.text for section in sections.values())
    dropped = 0
    for group in drafts.groups:
        for term in group.terms:
            if term_present(term, corpus):
                dropped += 1
                continue
            question = drafter.question(
                group.template.format(term=term), {"absent_key_terms": [term]}
            )
            if not term_present(term, question):
                raise ValueError("Draft model removed an absent-topic key term")
            result.append(
                candidate(
                    "no_answer",
                    question,
                    [],
                    [],
                    "gen:no_answer:v1",
                    "absent:" + term,
                    "Absent key phrase: "
                    + term
                    + ". Lexical absence is not semantic proof; human review required.",
                    [term],
                )
            )
    return result, {"no_answer_present_term_rejections": dropped}
