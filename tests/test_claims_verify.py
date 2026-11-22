from eval import claims_verify
from eval.schema import ClaimItem

from support_agent.grounding.claims import ClaimAssessment


def _item(claim: str, source: str) -> ClaimItem:
    return ClaimItem(
        id="claim-test-1",
        split="test",
        group="real",
        source_run="run",
        source_item="item",
        part=0,
        sentence=0,
        question="How long is the return window?",
        claim=claim,
        sources=[{"n": 1, "section_id": "returns", "text": source}],
        label_source="human",
    )


def test_literal_check_runs_before_the_model(monkeypatch):
    calls = []
    monkeypatch.setattr(claims_verify, "verify_claims", lambda *a: calls.append(a))
    verdict, reason = claims_verify.verdict_for(
        object(), "fast", _item("Returns are accepted within 45 days.", "Within 30 days.")
    )
    assert verdict == "unsupported" and reason.startswith("missing_literal") and not calls


def test_model_verdict_passes_through_and_errors_fail_closed(monkeypatch):
    item = _item("Returns are accepted within 30 days.", "Returns are accepted within 30 days.")

    def supported(models, role, claims):
        assert [source.text for source in claims[0].sources] == [item.sources[0].text]
        assert claims[0].question == item.question
        return {1: ClaimAssessment(part=0, text=item.claim, verdict="supported", reason="ok")}

    monkeypatch.setattr(claims_verify, "verify_claims", supported)
    assert claims_verify.verdict_for(object(), "fast", item) == ("supported", "ok")

    def broken(models, role, claims):
        raise ValueError("skipped a number")

    monkeypatch.setattr(claims_verify, "verify_claims", broken)
    assert claims_verify.verdict_for(object(), "fast", item) == (
        "unsupported",
        "verifier_error: ValueError",
    )
