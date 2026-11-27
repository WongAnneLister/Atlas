"""Refuse to report a run whose items mostly failed on a broken dependency.

A missing provider package, a dropped tunnel or a dead index makes every item hand off.
Scored as usual, that run looks like a working agent with a high reject rate. The rule is
the release gate's own: more dependency errors than `promotion_max_error_rate` allows.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from eval.gate import dependency_error_message, load_rules
from eval.run_record import Run

if TYPE_CHECKING:
    from eval.sim.models import ConversationTranscript

INVALID_RUN_STATUS = 3


def invalid_run_message(run: Run) -> str | None:
    """Describe why the run is invalid, or None when it may be reported."""
    return dependency_error_message(run, load_rules())


def invalid_transcripts_message(transcripts: list[ConversationTranscript]) -> str | None:
    """The same rule for simulator chats: a chat counts once if any turn hit an error."""
    errors: Counter[str] = Counter()
    for transcript in transcripts:
        kinds = [turn.dependency_error for turn in transcript.turns if turn.dependency_error]
        errors.update(kinds[:1])
    count = sum(errors.values())
    if count <= load_rules().promotion_max_error_rate * len(transcripts):
        return None
    kinds = ", ".join(f"{kind} x{n}" for kind, n in errors.most_common())
    return (
        f"dependency errors in {count}/{len(transcripts)} chats ({kinds}); "
        "fix the dependency and collect a new run"
    )
