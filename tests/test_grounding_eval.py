from __future__ import annotations

from eval import grounding_eval as ge


def answer(item_id: str, trace: list[str], text: str = "It shipped.") -> ge.AnswerRecord:
    return ge.AnswerRecord(
        item=ge.OrderQuestion(id=item_id, text="q"),
        trace=trace,
        answer=text,
        order_context={"get_order": {"order_id": "ORD-1"}},
    )


def test_only_released_tool_answers_are_checked() -> None:
    assert answer("a", ["rewrite", "classify", "tools"]).tools_answer
    assert not answer("b", ["tools", "tools_fallback", "retrieve", "gate", "answer"]).tools_answer
    assert not answer("c", ["tools", "handoff"]).tools_answer
    assert not answer("d", ["retrieve", "gate", "answer"]).tools_answer
    assert not answer("e", ["tools"], text="").tools_answer


def check(variant: str, kind: str, item: str, status: str, **extra: object) -> ge.CheckRecord:
    return ge.CheckRecord.model_validate(
        {
            "variant": variant,
            "kind": kind,
            "id": item,
            "max_attempts": 2,
            "rep": 1,
            "status": status,
            "attempts": 1,
            **extra,
        }
    )


def test_report_scores_real_answers_and_attacks_per_variant(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ge, "REPO_ROOT", tmp_path)
    answers = [answer("a", ["tools"]), answer("b", ["retrieve", "gate", "handoff"])]
    checks = [
        check("single-quote", "order", "a", "ungrounded", missing=["Old."]),
        check("single-quote", "attack", "x", "grounded"),
        check("sentence-quotes", "order", "a", "grounded"),
        check("sentence-quotes", "order", "a", "ungrounded", missing=["It shipped."]),
        check("sentence-quotes", "attack", "x", "ungrounded", attempts=2),
        check("sentence-quotes", "attack", "y", "error"),
    ]
    text = "\n".join(ge.report_lines(answers, checks))
    assert "Questions: 2; answered by the order tools: 1." in text
    assert "or fallback): `b`" in text
    assert "| single-quote | 2 | 0/1" in text
    assert "| sentence-quotes | 2 | 1/2 (50.00%" in text
    assert "`single-quote` attacks that passed the check at least once: 1" in text
    assert "`sentence-quotes` attacks that passed the check at least once: 0" in text
    assert "`sentence-quotes` checks that used a retry: 1" in text
    assert "- 1 x It shipped." in text
    assert "Old." not in text


def test_attack_cases_reuse_base_answers_and_replay_tools(seeded) -> None:
    _, service = seeded
    bases = sorted({row["base"] for row in ge._yaml(ge.ATTACKS) if "base" in row})
    answers = [answer(b, ["tools"], text="It is in transit.") for b in bases]
    base = answers[bases.index("order-where-13")]
    cases = ge.build_cases(answers, service, "CUST-0001")
    attacks = {c.id: c for c in cases if c.kind == "attack"}
    assert sorted(c.id for c in cases if c.kind == "order") == bases
    friend = attacks["attack-friend-collect"]
    assert friend.answer.startswith("It is in transit.\n\n")
    assert friend.order_context == base.order_context
    assert attacks["recorded-friend-collect"].order_context["list_recent_orders"]
