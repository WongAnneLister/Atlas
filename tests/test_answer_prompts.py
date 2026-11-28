"""Keep single-question coverage rules in the multipart prompt."""

from support_agent.graph.handoff import PROMPTS


def test_multipart_answer_prompt_keeps_single_question_rules_verbatim():
    single = (PROMPTS / "answer.md").read_text(encoding="utf-8").splitlines()
    multipart = set((PROMPTS / "answer_parts.md").read_text(encoding="utf-8").splitlines())
    exceptions = {
        # The multipart planner provides the list of questions.
        "List EVERY requested part of the customer's question, including all requested attributes",
        'and all parts joined by "and", "also", or similar wording. Never omit a hard part.',
        # The graph can release supported parts while handing off unsupported parts.
        "No partial customer answer is released if any requested part lacks support.",
    }

    assert exceptions <= set(single), "Recheck the single-question-only exceptions"
    accounted_for = exceptions | multipart
    missing = [line for line in single if line.strip() and line not in accounted_for]
    assert not missing, "Missing shared prompt lines:\n" + "\n".join(missing)

    required_multipart = (
        "Each entry in the input JSON is one part, with a question and its numbered sources.",
        "Use only the sources listed for that question. "
        "Source numbers identify chunks across the reply.",
        "Return one structured coverage decision for each input question, in input order.",
        "Copy each question exactly into its decision. "
        "Never split, combine, add, or omit a question.",
        "If a question asks for several facts, each fact needs explicit evidence "
        "in that question's sources.",
    )
    missing_multipart = [line for line in required_multipart if line not in multipart]
    assert not missing_multipart, "Missing multipart prompt lines:\n" + "\n".join(missing_multipart)


def test_both_answer_prompts_ask_for_the_key_fact_first():
    # Grounding treats a part's first sentence as its main claim. An unsupported opening
    # summary dropped a part whose substantive sentence was verified (28h, sim-049 turn 14).
    rule = (
        "Begin each answer with the sentence that answers the question with its key fact.",
        "Do not open with a summary, heading, or general statement; every sentence needs a quote.",
    )
    for name in ("answer.md", "answer_parts.md"):
        lines = (PROMPTS / name).read_text(encoding="utf-8").splitlines()
        assert all(line in lines for line in rule), f"{name} lacks the lead-sentence rule"


def test_classifier_routes_cancel_and_refund_to_the_refund_path():
    # 12h: "cancel it and refund me" for a shipped order was classified as order_status in
    # two of three sim-030 runs, so it never reached the refund decision.
    lines = (PROMPTS / "classify.md").read_text(encoding="utf-8").splitlines()
    assert "A request to cancel an order and get the money back is refund_request; cancelling" in (
        lines
    )
    assert "without asking for the money back stays order_status." in lines


def test_classifier_separates_permission_account_problems_and_refund_tracking():
    # 13e: the main classifier errors on the reviewed intent holdout (13d).
    lines = (PROMPTS / "classify.md").read_text(encoding="utf-8").splitlines()
    for rule in (
        "Asking whether one may return, exchange, or replace an item is policy_question;",
        "A reported problem with an account, sign-up, or subscription action is chitchat_other,",
        "Checking or tracking the status of a refund is refund_request, not order_status.",
    ):
        assert rule in lines
