from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from support_agent.config import Settings, get_settings
from support_agent.data.build_docs import build_docs, document
from support_agent.data.doc_models import FAQ, normalise
from support_agent.data.faq_docs import TopicClassifier, deduplicate, load_faqs
from support_agent.data.manifest import Manifest, SourceRecord, describe_file, write_manifest
from support_agent.data.validate_docs import check_numbers, parse_document, validate_docs
from support_agent.llm import override_chat_model


def faq(question: str, answer: str = "Read the policy.", **kwargs: str) -> FAQ:
    values = {"source_id": question, "dataset": "fixture", "category": "Store"}
    values.update(kwargs)
    return FAQ(question=question, answer=answer, **values)


def test_normalise_html_and_dedupe_keep_scopes_and_changed_facts() -> None:
    assert normalise("<p>A&nbsp; test</p><script>bad</script><p>here</p>") == "A test here"
    records = [
        faq("How can I track an order?", source_id="a"),
        faq("How can I track an order?", source_id="b"),
        faq("How can I track my order?", source_id="c"),
        faq("How can I track an order?", "It cannot be tracked.", source_id="d"),
        faq("How can I track an order?", dataset="another", source_id="e"),
        faq("Can I return in 30 days?", source_id="f"),
        faq("Can I return in 31 days?", source_id="g"),
        faq("An empty answer?", "", source_id="h"),
    ]
    groups, excluded, counts = deduplicate(records, 0.90)
    assert len(groups) == 5
    assert {f.source_id for f in groups[0].records} == {"a", "b", "c"}
    assert excluded == {"h": "empty_question_or_answer"}
    assert counts == {"exact": 1, "near": 1, "empty": 1}


@pytest.mark.parametrize(
    ("question", "topic"),
    [
        ("When is my refund?", "refunds"),
        ("Can I return this?", "returns"),
        ("Track my shipment", "shipping"),
        ("Which payment methods?", "payments"),
        ("Reset my password", "membership"),
        ("Cancel an order", "orders"),
        ("Is there a warranty?", "warranty"),
    ],
)
def test_topic_rules_precede_category(tmp_path: Path, question: str, topic: str) -> None:
    classifier = TopicClassifier(get_settings(), tmp_path / "cache.jsonl")
    assert classifier.classify(faq(question, category="Shipping")) == topic
    assert classifier.methods == {"rule": 1}


def test_fake_model_leftovers_are_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "cache.jsonl"
    classifier = TopicClassifier(get_settings(), cache)
    record = faq("What about gift wrap?")
    with override_chat_model("fast", FakeListChatModel(responses=["other"])):
        assert classifier.classify(record) == "other"
    classifier.save()
    original = cache.read_bytes()

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Cached topics must not call the model factory")

    monkeypatch.setattr("support_agent.data.faq_docs.get_chat_model", forbidden)
    cached = TopicClassifier(get_settings(), cache)
    assert cached.classify(record) == "other"
    cached.save()
    assert cache.read_bytes() == original
    assert cached.methods == {"fast_model": 1}


def test_invalid_model_topic_is_rejected(tmp_path: Path) -> None:
    classifier = TopicClassifier(get_settings(), tmp_path / "cache.jsonl")
    with (
        override_chat_model("fast", FakeListChatModel(responses=["invented_topic"])),
        pytest.raises(ValueError, match="Invalid model topic"),
    ):
        classifier.classify(faq("Tell me something unknown"))


def test_missing_model_uses_explicit_other(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FAST_MODEL", raising=False)
    classifier = TopicClassifier(get_settings(), tmp_path / "cache.jsonl")
    assert classifier.classify(faq("Gift wrap options?")) == "other"
    assert classifier.methods == {"other_without_model": 1}


def test_document_rejects_duplicate_missing_and_empty_section_ids() -> None:
    section = "## Window\n<!-- section: returns.window -->\n\nWithin 30 days."
    text = document("returns", ["fixture"], "2026-11-09", [section])
    assert parse_document(text)[0] == {"returns.window": "Within 30 days."}
    with pytest.raises(ValueError, match="Duplicate section"):
        parse_document(text + "\n" + section)
    with pytest.raises(ValueError, match="Empty section"):
        parse_document(document("returns", [], "2026-11-09", [section.split("\n\n")[0]]))
    with pytest.raises(ValueError, match="Every heading"):
        parse_document(text.replace("<!-- section: returns.window -->", ""))


def test_numeric_guard_rejects_new_values_and_changed_units() -> None:
    check_numbers("Return within 30 days.", "Returns take 30 days.")
    with pytest.raises(ValueError, match="Unsupported numbers"):
        check_numbers("Return within 60 days.", "Returns take 30 days.")
    with pytest.raises(ValueError, match="Unsupported numbers"):
        check_numbers("Refund 30%.", "Return within 30 days.")


def pdf_bytes(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf ({text}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def build_settings(tmp_path: Path) -> Settings:
    settings = get_settings().model_copy(deep=True)
    raw = tmp_path / "raw"
    settings.data.raw_dir = str(raw)
    settings.data.processed_dir = str(tmp_path / "processed")
    settings.data.docs.classify_leftovers = False
    settings.data.docs.model_pattern = r"\bW\d+(?: Pro)?\b"
    settings.data.docs.product_categories = {"W": "fixture"}
    for name in ["flipkart_faqs", "maktek_faqs", "philips_manuals"]:
        (raw / name).mkdir(parents=True)
    with (raw / "flipkart_faqs/FAQs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "parent_category",
                "category",
                "question_id",
                "question",
                "answer",
            ],
        )
        writer.writeheader()
        for i, (question, answer) in enumerate(
            [
                ("What are return terms?", "Return within 30 days."),
                ("What are shipping times?", "Shipping takes 3 days."),
                ("Which payment methods?", "We accept cards."),
                ("How do I create an account?", "Use the signup form."),
            ]
        ):
            writer.writerow(
                dict(
                    parent_category="",
                    category="Store",
                    question_id=str(i),
                    question=question,
                    answer=answer,
                )
            )
    (raw / "maktek_faqs/train_expanded.json").write_text(
        json.dumps({"question": "What are return terms?", "answer": "Return within 10 days."})
        + "\n",
        encoding="utf-8",
    )
    with zipfile.ZipFile(raw / "philips_manuals/products.zip", "w") as archive:
        archive.writestr("Wrong-model-name.pdf", pdf_bytes("W40 W40 Pro W400 Manual"))
    manifest = Manifest()
    for source in settings.data.sources:
        if source.name == "bitext":
            continue
        source_dir = raw / source.name
        manifest.sources[source.name] = SourceRecord(
            name=source.name,
            repo_id=source.repo_id,
            revision=source.revision,
            downloaded_at="2026-11-09",
            files=[describe_file(p, source_dir) for p in sorted(source_dir.iterdir())],
        )
    write_manifest(raw, manifest)
    return settings


def snapshot(path: Path) -> dict[str, bytes]:
    return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}


def test_build_is_valid_and_byte_identical(build_settings: Settings) -> None:
    build_docs(build_settings)
    summary = validate_docs(build_settings)
    assert summary.coverage == 1.0
    assert summary.products == 3
    assert summary.source_faqs == 5
    processed = Path(build_settings.data.processed_dir)
    first = snapshot(processed)
    build_docs(build_settings)
    assert snapshot(processed) == first
    text = (processed / "docs/catalog_fixture.md").read_text(encoding="utf-8")
    assert set(parse_document(text)[0]) == {"product.W40", "product.W40 Pro", "product.W400"}
    assert set(load_faqs(Path(build_settings.data.raw_dir))[i].answer for i in (0, 4)) == {
        "Return within 30 days.",
        "Return within 10 days.",
    }


@pytest.mark.parametrize(
    "corruption",
    [
        "numbers",
        "facts",
        "duplicate",
        "provenance",
        "catalog",
        "new_promise",
        "preamble",
    ],
)
def test_validator_rejects_output_corruption(build_settings: Settings, corruption: str) -> None:
    build_docs(build_settings)
    processed = Path(build_settings.data.processed_dir)
    path = processed / "docs/returns.md"
    text = path.read_text(encoding="utf-8")
    if corruption == "numbers":
        path.write_text(text + "\nRefund in 999 days.\n", encoding="utf-8")
    elif corruption == "facts":
        path.write_text(text.replace("30 days", "10 days"), encoding="utf-8")
    elif corruption == "duplicate":
        (processed / "docs/duplicate.md").write_text(text, encoding="utf-8")
    elif corruption == "provenance":
        (processed / "docs/provenance.json").write_text("{}", encoding="utf-8")
    elif corruption == "new_promise":
        path.write_text(text + "\nWe always refund every purchase.\n", encoding="utf-8")
    elif corruption == "preamble":
        path.write_text(text.replace("\n## ", "\nUnconditional refunds.\n## ", 1), encoding="utf-8")
    else:
        path = processed / "catalog/products.jsonl"
        path.write_text(path.read_text(encoding="utf-8").replace("W400", "W999"), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_docs(build_settings)


def test_disabled_versions_keep_build_bytes_and_do_not_read_the_spec(
    build_settings: Settings,
) -> None:
    assert not build_settings.policy_versions.enabled
    build_docs(build_settings)
    processed = Path(build_settings.data.processed_dir)
    original = snapshot(processed)
    build_settings.policy_versions.spec_path = "missing-spec.yaml"
    build_docs(build_settings)
    validate_docs(build_settings)
    assert snapshot(processed) == original


def test_enabled_versions_generate_validated_synthetic_sections(
    build_settings: Settings, tmp_path: Path
) -> None:
    from support_agent.data.doc_models import digest

    base_id = f"returns.maktek_faqs.generic-store.{digest('Generic store')}"
    spec = tmp_path / "policy-versions.yaml"
    spec.write_text(
        f"""entries:
  - base_section_id: {base_id}
    effective_from: 2026-09-01
    old:
      effective_from: 2026-01-01
      effective_to: 2026-09-01
      find: Return within 10 days.
      replace: Return within 90 days.
""",
        encoding="utf-8",
    )
    build_settings.policy_versions.enabled = True
    build_settings.policy_versions.spec_path = str(spec)
    build_docs(build_settings)
    validate_docs(build_settings)
    text = (Path(build_settings.data.processed_dir) / "docs/returns.md").read_text()
    parsed, _ = parse_document(text)
    assert "Return within 10 days." in parsed[base_id]
    assert "Return within 90 days." in parsed[f"{base_id}@2026-01-01"]
