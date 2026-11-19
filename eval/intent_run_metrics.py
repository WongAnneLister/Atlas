"""Compute macro intent scores from a confusion-cell observation per question."""

import numpy as np
from numpy.typing import NDArray

from support_agent.graph.intents import Intent

LABELS = {intent: index for index, intent in enumerate(Intent)}


def confusion_observation(gold: Intent, predicted: Intent) -> float:
    return float(len(LABELS) * LABELS[gold] + LABELS[predicted])


def intent_macro_stat(values: NDArray[np.float64], *, precision: bool) -> float:
    size = len(LABELS)
    table = np.bincount(values.astype(int), minlength=size * size).reshape(size, size)
    totals = table.sum(axis=0 if precision else 1)
    by_label = np.divide(
        table.diagonal(),
        totals,
        out=np.zeros(size, dtype=float),
        where=totals != 0,
    )
    return float(by_label.mean())
