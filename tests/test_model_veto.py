from __future__ import annotations

from eval import model_veto
from eval.sweep import GateScore


def score(item_id: str, answerable: bool, value: float, vetoed: bool = False) -> GateScore:
    return GateScore(
        id=item_id,
        group="g",
        split="dev",
        answerable=answerable,
        score=value,
        signals={},
        vetoed=vetoed,
    )


def test_counts_use_the_threshold_and_the_veto() -> None:
    records = [
        score("a", True, 0.5),
        score("b", True, 0.1),
        score("c", False, 0.6, vetoed=True),
        score("d", False, 0.6),
    ]
    fr, fa = model_veto.counts(records, 0.3)
    assert fr.startswith("1/2")
    assert fa.startswith("1/2")
    assert model_veto.counts([score("a", True, 0.5)], 0.3)[1] == "n/a"


def test_variant_settings_only_toggle_the_model_veto() -> None:
    from support_agent.config import Settings

    base = Settings()
    on = model_veto.variant_settings(base, True)
    assert on.gate.require_model_number_hit is True
    assert model_veto.variant_settings(base, False).gate.require_model_number_hit is False
    assert on.gate.model_dump(exclude={"require_model_number_hit"}) == base.gate.model_dump(
        exclude={"require_model_number_hit"}
    )
