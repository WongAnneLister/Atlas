"""Scratch fixtures use prior schema and keep production model prompts unchanged."""

from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import Field

from support_agent.config import Settings
from support_agent.graph.deps import GraphDeps


def test_dev_environment_can_only_seed_isolated_sqlite(tmp_path: Path, monkeypatch) -> None:
    from eval.redteam_canaries import ATTACKER_CUSTOMER, FOREIGN_CUSTOMER, FOREIGN_ORDER
    from eval.redteam_fixtures import open_fixtures

    dev_file = tmp_path / "dev.sqlite"
    dev_file.write_bytes(b"developer file")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example:example@127.0.0.1:1/atlas")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1")
    settings = Settings()
    settings.orders.db_path = str(dev_file)
    with open_fixtures(settings, run_dir) as fixtures:
        isolated = fixtures.settings
        assert isolated.db.backend == "sqlite"
        assert isolated.graph.checkpoint_backend == "memory"
        assert isolated.redis.backend == "null"
        assert isolated.database_url is None and isolated.redis_url is None
        assert fixtures.orders.repository.engine.dialect.name == "sqlite"
        assert Path(isolated.orders.db_path).parent == run_dir
        assert fixtures.orders.customer_exists(ATTACKER_CUSTOMER)
        other_order = fixtures.orders.get_order(FOREIGN_ORDER, FOREIGN_CUSTOMER)
        assert other_order.coupon_code == fixtures.canaries["foreign_coupon"]

    assert dev_file.read_bytes() == b"developer file"
    assert settings.orders.db_path == str(dev_file)


def test_scratch_refuses_outside_symlink_hardlink_and_preexisting_file(tmp_path: Path) -> None:
    from eval.redteam_fixtures import open_fixtures

    settings = Settings()
    source = tmp_path / "outside.sqlite"
    source.write_bytes(b"keep")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    link = tmp_path / "run-link"
    link.symlink_to(run_dir, target_is_directory=True)
    with pytest.raises(ValueError), open_fixtures(settings, link):
        pytest.fail("Resolved directory alias accepted")

    symbolic = run_dir / "symbolic.sqlite"
    symbolic.symlink_to(source)
    hard = run_dir / "hard.sqlite"
    hard.hardlink_to(source)
    ordinary = run_dir / "ordinary.sqlite"
    ordinary.write_bytes(b"keep this too")
    for candidate in (source, symbolic, hard, ordinary):
        with (
            pytest.raises((ValueError, FileExistsError)),
            open_fixtures(settings, run_dir, database_path=candidate),
        ):
            pytest.fail("Existing or external database accepted")
    assert source.read_bytes() == b"keep"
    assert ordinary.read_bytes() == b"keep this too"


class RecordingModel(FakeListChatModel):
    systems: list[str] = Field(default_factory=list)

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> AIMessage:
        self.systems.extend(str(msg.content) for msg in input if isinstance(msg, SystemMessage))
        return AIMessage(content="ack")


def test_render_hook_is_default_off_and_does_not_mutate_the_original_prompt() -> None:
    original = SystemMessage(content="Production system instructions.")
    messages = [original, HumanMessage(content="Synthetic question.")]

    def render(site: str, prompt: list[BaseMessage]) -> list[BaseMessage]:
        assert site == "rewrite"
        return [original.model_copy(update={"content": "Synthetic rendered prompt."}), *prompt[1:]]

    model = RecordingModel(responses=["unused"])
    with GraphDeps(Settings(), fast_model=model) as regular:
        regular.models.invoke("rewrite", "fast", messages)
    with GraphDeps(Settings(), fast_model=model, model_messages=render) as instrumented:
        instrumented.models.invoke("rewrite", "fast", messages)
    assert model.systems == ["Production system instructions.", "Synthetic rendered prompt."]
    assert original.content == "Production system instructions."


def test_repaired_model_attempt_has_one_fixture_marker_in_each_system_prompt() -> None:
    from eval.redteam_canaries import build_canaries
    from eval.redteam_fixtures import FixtureHooks

    from support_agent.graph.intents import Intent
    from support_agent.graph.nodes.classify import IntentPrediction
    from test_graph import StructuredFake

    model = StructuredFake(
        responses=["unused"], predictions=[None, {"intent": Intent.CHITCHAT_OTHER, "confidence": 1}]
    )
    canary = build_canaries()["system_prompt"]
    hooks = FixtureHooks(canary)
    original = SystemMessage(content="Production system instructions.")
    with GraphDeps(Settings(), fast_model=model, model_messages=hooks.model_messages) as deps:
        _, event = deps.models.structured(
            "classify", "fast", IntentPrediction, [original, HumanMessage(content="A fixture.")]
        )
    assert event.repaired
    assert len(model.classified_messages) == 2
    for attempt in model.classified_messages:
        assert str(attempt[0].content).count(canary) == 1
    assert canary not in original.content
