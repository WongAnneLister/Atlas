"""Bind saved release evidence to the index lifecycle."""

from eval.index_release import collect_run, evaluate_release, find_live_run, load_release_set
from eval.run_record import read_run
from support_agent.config import Settings
from support_agent.retrieval.index_models import BuildRecord
from support_agent.retrieval.index_plan import embedding_profile
from support_agent.retrieval.index_release import Check, Decision


def check_for(
    settings: Settings,
    *,
    reranker_device: str | None = None,
    override_reason: str | None = None,
) -> Check:
    config = settings.model_copy(deep=True)
    if reranker_device is not None:
        config.retrieval.reranker_device = reranker_device
    selected = load_release_set(config)

    def check(candidate: BuildRecord, live: BuildRecord | None) -> tuple[Decision, str]:
        if candidate.embedding_profile != embedding_profile(config):
            raise ValueError("Effective embedding settings must match the candidate build")
        live_run = None
        if live is not None:
            old = config.model_copy(deep=True)
            old.retrieval = type(old.retrieval).model_validate(
                {
                    **old.retrieval.model_dump(),
                    **live.embedding_profile,
                }
            )
            path = find_live_run(
                old,
                build_id=live.build_id,
                release_set=selected,
                fingerprint=live.fingerprint,
                collection=live.collection,
            )
            if path is None:
                path = collect_run(
                    old,
                    live.collection,
                    build_id=live.build_id,
                    fingerprint=live.fingerprint,
                    release_set=selected,
                )
            live_run = read_run(path)
        path = collect_run(
            config,
            candidate.collection,
            build_id=candidate.build_id,
            fingerprint=candidate.fingerprint,
            release_set=selected,
        )
        result = evaluate_release(read_run(path), live_run, override_reason=override_reason)
        return result, path.name

    return check
