"""Refuse to report a run whose items mostly failed on a broken dependency.

A missing provider package, a dropped tunnel or a dead index makes every item hand off.
Scored as usual, that run looks like a working agent with a high reject rate. The rule is
the release gate's own: more dependency errors than `promotion_max_error_rate` allows.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from eval.gate import dependency_error_message, load_rules
from eval.run_record import Run

if TYPE_CHECKING:
    from eval.sim.models import ConversationTranscript

INVALID_RUN_STATUS = 3


def invalid_run_message(run: Run) -> str | None:
    """Describe why the run is invalid, or None when it may be reported."""
    return dependency_error_message(run, load_rules())


def state_dependency_error(values: Mapping[str, Any]) -> str | None:
    """The first model or dependency error a graph state recorded, if any."""
    for name in ("classification_error_type", "retrieval_error_type", "answer_error_type"):
        if values.get(name):
            return str(values[name])
    for event in values.get("reliability_events") or []:
        error = getattr(event, "error_type", None)
        if error is None and isinstance(event, dict):
            error = event.get("error_type")
        if error:
            return str(error)
    return None


def invalid_errors_message(errors: Iterable[str | None], unit: str) -> str | None:
    """The gate's error-rate rule over units that each carry their first error or None."""
    found = list(errors)
    counts = Counter(error for error in found if error)
    count = sum(counts.values())
    if count <= load_rules().promotion_max_error_rate * len(found):
        return None
    kinds = ", ".join(f"{kind} x{n}" for kind, n in counts.most_common())
    return (
        f"dependency errors in {count}/{len(found)} {unit} ({kinds}); "
        "fix the dependency and collect a new run"
    )


def transcript_error(transcript: ConversationTranscript) -> str | None:
    """A chat counts once: its first model error, else its first HTTP or stream error."""
    for field in ("dependency_error", "error_type"):
        if found := next((getattr(t, field) for t in transcript.turns if getattr(t, field)), None):
            return str(found)
    if transcript.stop_reason == "error" and not transcript.turns:
        return "session_error"
    return None


def invalid_transcripts_message(transcripts: list[ConversationTranscript]) -> str | None:
    """The same rule for simulator chats: a chat counts once if any turn hit an error."""
    return invalid_errors_message(map(transcript_error, transcripts), "chats")


def invalid_arms_message(arms: Mapping[str, list[ConversationTranscript]]) -> str | None:
    """Each arm is judged alone, so one dead arm cannot hide among healthy ones."""
    for name, transcripts in arms.items():
        if message := invalid_transcripts_message(transcripts):
            return f"arm {name}: {message}"
    return None
