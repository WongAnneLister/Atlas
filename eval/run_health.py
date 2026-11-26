"""Refuse to report a run whose items mostly failed on a broken dependency.

A missing provider package, a dropped tunnel or a dead index makes every item hand off.
Scored as usual, that run looks like a working agent with a high reject rate. The rule is
the release gate's own: more dependency errors than `promotion_max_error_rate` allows.
"""

from __future__ import annotations

from eval.gate import dependency_error_message, load_rules
from eval.run_record import Run

INVALID_RUN_STATUS = 3


def invalid_run_message(run: Run) -> str | None:
    """Describe why the run is invalid, or None when it may be reported."""
    return dependency_error_message(run, load_rules())
