import pytest
from eval.intent_draft import draft_returns
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


class DraftModel:
    def __init__(self, values):
        self.values = values
        self.messages = []

    def with_structured_output(self, schema, include_raw):
        assert include_raw is True

        def respond(messages):
            self.messages.extend(messages)
            return {
                "parsed": schema(utterances=self.values),
                "raw": AIMessage(content="", response_metadata={"model_name": "fake-drafter"}),
            }

        return RunnableLambda(respond)


def test_drafting_preserves_model_provenance_and_requested_count() -> None:
    fake = DraftModel(["Exchange this shirt", "Replace my damaged mug"])
    texts, model = draft_returns(fake, count=2)
    assert texts == fake.values
    assert model == "fake-drafter"
    assert "2" in fake.messages[0].content


def test_drafting_rejects_wrong_count_instead_of_inventing_examples() -> None:
    with pytest.raises(ValueError, match="count"):
        draft_returns(DraftModel(["Exchange this shirt"]), count=2)
