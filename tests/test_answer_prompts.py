"""Keep single-question coverage rules in the multipart prompt."""

from support_agent.graph.handoff import PROMPTS


def test_multipart_answer_prompt_keeps_single_question_rules_verbatim():
    single = (PROMPTS / "answer.md").read_text(encoding="utf-8").splitlines()
    multipart = (PROMPTS / "answer_parts.md").read_text(encoding="utf-8").splitlines()
    exceptions = {
        # The multipart planner provides the list of questions.
        "List EVERY requested part of the customer's question, including all requested attributes",
        'and all parts joined by "and", "also", or similar wording. Never omit a hard part.',
        # The graph can release supported parts while handing off unsupported parts.
        "No partial customer answer is released if any requested part lacks support.",
    }

    assert exceptions <= set(single), "Recheck the single-question-only exceptions"
    accounted_for = exceptions | set(multipart)
    missing = [line for line in single if line.strip() and line not in accounted_for]
    assert not missing, "Missing shared prompt lines:\n" + "\n".join(missing)
