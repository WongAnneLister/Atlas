import numpy as np
import pytest
from eval.stats import (
    bootstrap_ci,
    cohens_kappa,
    mcnemar_exact,
    paired_bootstrap_diff,
    rule_of_three_upper,
    verdict,
    wilson_interval,
)


def test_seeded_bootstrap():
    values = np.random.default_rng(17).binomial(1, 0.3, size=200)
    interval = bootstrap_ci(values, seed=19)
    assert interval.low < 0.3 < interval.high
    assert interval == bootstrap_ci(values, seed=19)


@pytest.mark.parametrize(("n", "rule", "wilson"), [(30, 0.10, 0.1135), (60, 0.05, 0.0602)])
def test_zero_event_bounds(n, rule, wilson):
    assert rule_of_three_upper(n) == rule
    assert wilson_interval(0, n).high == pytest.approx(wilson, abs=0.0001)


def test_exact_mcnemar_and_kappa():
    assert mcnemar_exact(10, 2) == 158 / 4096
    assert mcnemar_exact(0, 0) == 1
    assert cohens_kappa([[8, 2], [2, 8]]) == pytest.approx(0.6)
    assert cohens_kappa([[8, 0], [0, 8]]) == 1
    assert cohens_kappa([[8, 0], [0, 0]]) is None


def test_pairing_retains_identical_outcomes():
    interval = paired_bootstrap_diff([1, 0, 1], [1, 0, 1])
    assert interval.point == interval.low == interval.high == 0
    assert verdict(interval, direction="higher") == "no significant change"
