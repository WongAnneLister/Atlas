"""Deterministic, offline confidence intervals and paired tests."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import comb, sqrt
from statistics import NormalDist
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

Direction = Literal["higher", "lower"]
Verdict = Literal["better", "worse", "no significant change"]
Statistic = Literal["mean", "p50", "p95"] | Callable[[NDArray[np.float64]], float]


@dataclass(frozen=True)
class Interval:
    point: float
    low: float
    high: float


def _values(values: ArrayLike) -> NDArray[np.float64]:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or not len(array) or not np.isfinite(array).all():
        raise ValueError("Expected a nonempty vector of finite observations")
    return array


def _reduce(samples: NDArray[np.float64], stat: Statistic) -> NDArray[np.float64]:
    if stat == "mean":
        return np.mean(samples, axis=1)
    if stat in ("p50", "p95"):
        percentile = 50 if stat == "p50" else 95
        rank = (percentile * samples.shape[1] + 99) // 100 - 1
        return np.partition(samples, rank, axis=1)[:, rank]
    return np.asarray([stat(row) for row in samples], dtype=float)


def _interval(point: float, samples: NDArray[np.float64], alpha: float) -> Interval:
    valid = samples[np.isfinite(samples)]
    if not len(valid) or not np.isfinite(point):
        raise ValueError("Statistic is undefined")
    low, high = np.quantile(valid, [alpha / 2, 1 - alpha / 2])
    return Interval(float(point), float(low), float(high))


def _indices(size: int, n_resamples: int, seed: int, alpha: float) -> NDArray[np.int64]:
    if n_resamples <= 0 or not 0 < alpha < 1:
        raise ValueError("Expected positive resample count and alpha between zero and one")
    return np.random.default_rng(seed).integers(size, size=(n_resamples, size))


def bootstrap_ci(
    values: ArrayLike,
    stat: Statistic = "mean",
    *,
    n_resamples: int = 2000,
    seed: int = 17,
    alpha: float = 0.05,
) -> Interval:
    array = _values(values)
    indices = _indices(len(array), n_resamples, seed, alpha)
    return _interval(_reduce(array[None, :], stat)[0], _reduce(array[indices], stat), alpha)


def paired_bootstrap_diff(
    a: ArrayLike,
    b: ArrayLike,
    stat: Statistic = "mean",
    *,
    n_resamples: int = 2000,
    seed: int = 17,
    alpha: float = 0.05,
) -> Interval:
    left, right = _values(a), _values(b)
    if left.shape != right.shape:
        raise ValueError("Paired samples must have the same length")
    indices = _indices(len(left), n_resamples, seed, alpha)
    point = _reduce(right[None, :], stat)[0] - _reduce(left[None, :], stat)[0]
    return _interval(point, _reduce(right[indices], stat) - _reduce(left[indices], stat), alpha)


def wilson_interval(k: int, n: int, alpha: float = 0.05) -> Interval:
    if n <= 0 or not 0 <= k <= n or not 0 < alpha < 1:
        raise ValueError("Invalid count, sample size or alpha")
    p = k / n
    z = NormalDist().inv_cdf(1 - alpha / 2)
    scale = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / scale
    radius = z * sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / scale
    return Interval(p, max(0, center - radius), min(1, center + radius))


def rule_of_three_upper(n: int) -> float:
    if n <= 0:
        raise ValueError("Sample size must be positive")
    return 3 / n


def mcnemar_exact(b: int, c: int) -> float:
    if min(b, c) < 0:
        raise ValueError("Discordant counts cannot be negative")
    n = b + c
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / 2**n)


def cohens_kappa(table_2x2: Sequence[Sequence[int]]) -> float | None:
    (a, b), (c, d) = table_2x2
    if min(a, b, c, d) < 0:
        raise ValueError("Agreement counts cannot be negative")
    n = a + b + c + d
    expected = (a + b) * (a + c) + (c + d) * (b + d)
    denominator = n**2 - expected
    return ((a + d) * n - expected) / denominator if denominator else None


def verdict(
    interval: Interval, *, direction: Direction, p_value: float | None = None, alpha: float = 0.05
) -> Verdict:
    significant = interval.low > 0 or interval.high < 0 if p_value is None else p_value < alpha
    if not significant or interval.point == 0:
        return "no significant change"
    return "better" if (interval.point > 0) == (direction == "higher") else "worse"
