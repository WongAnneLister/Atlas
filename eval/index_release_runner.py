"""Bind saved release evidence to the index lifecycle."""

from eval.index_release import (
    absolute_ids,
    collect_run,
    evaluate_release,
    find_live_run,
    load_release_set,
)
from eval.run_record import read_run
from support_agent.config import Settings
from support_agent.retrieval.chunking import chunk_size_stats
from support_agent.retrieval.index_models import BuildRecord
from support_agent.retrieval.index_plan import embedding_profile
from support_agent.retrieval.index_release import Check, Decision
from support_agent.retrieval.index_snapshot import load_build_chunks


def chunk_size_note(settings: Settings, role: str, build_id: str) -> str:
    """One release-report line with a build's chunk size distribution (28g)."""
    try:
        stats = chunk_size_stats(load_build_chunks(settings, build_id), settings.chunk)
    except (OSError, ValueError) as error:
        reason = type(error).__name__
        return f"{role} build {build_id} chunk sizes: snapshot unavailable ({reason})."
    return (
        f"{role} build {build_id} chunk sizes: {stats.count} chunks, max {stats.max_tokens}, "
        f"p99 {stats.p99_tokens}, {stats.over_max_tokens} over chunk.max_tokens "
        f"({settings.chunk.max_tokens}); hard cap {stats.hard_max_tokens}."
    )


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
        # A clean run with the same build, items and evidence config is valid in either role.
        path = find_live_run(
            config,
            build_id=candidate.build_id,
            release_set=selected,
            fingerprint=candidate.fingerprint,
            collection=candidate.collection,
        ) or collect_run(
            config,
            candidate.collection,
            build_id=candidate.build_id,
            fingerprint=candidate.fingerprint,
            release_set=selected,
        )
        result = evaluate_release(
            read_run(path),
            live_run,
            override_reason=override_reason,
            absolute=absolute_ids(selected, config),
        )
        result.notes.append(chunk_size_note(config, "Candidate", candidate.build_id))
        if live is not None:
            result.notes.append(chunk_size_note(config, "Live", live.build_id))
        return result, path.name

    return check
