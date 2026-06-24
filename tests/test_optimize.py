"""Unit tests for P4 washing-schedule optimization."""

from __future__ import annotations

from spis import config
from spis.optimize import (
    SoilingRateBand,
    optimal_interval_closed_form,
    optimal_interval_grid_search,
    rate_for_scenario,
    total_cost_per_day,
)


def _band() -> SoilingRateBand:
    return SoilingRateBand(
        point=0.00125,
        low=0.00064,
        high=0.00186,
        source="test",
        half_width=0.00061,
    )


def test_closed_form_matches_grid_search() -> None:
    """Closed-form T* must agree with numeric grid search within tolerance."""
    wash = 150_000.0
    energy = 11_000.0
    price = 2000.0
    rate = 0.00125
    t_closed = optimal_interval_closed_form(wash, energy, price, rate)
    t_grid, _ = optimal_interval_grid_search(wash, energy, price, rate)
    assert abs(t_closed - t_grid) <= config.OPTIMIZE_CLOSED_FORM_TOLERANCE_DAYS


def test_t_star_decreases_as_wash_cost_falls() -> None:
    """Cheaper washes justify more frequent cleaning."""
    energy = 11_000.0
    price = 2000.0
    rate = 0.00125
    t_high_cost = optimal_interval_closed_form(300_000.0, energy, price, rate)
    t_low_cost = optimal_interval_closed_form(50_000.0, energy, price, rate)
    assert t_low_cost < t_high_cost


def test_t_star_decreases_as_rate_or_price_rise() -> None:
    """Stronger soiling or higher revenue increases washing frequency."""
    wash = 150_000.0
    energy = 11_000.0
    t_low_rate = optimal_interval_closed_form(wash, energy, 2000.0, 0.0005)
    t_high_rate = optimal_interval_closed_form(wash, energy, 2000.0, 0.0020)
    assert t_high_rate < t_low_rate
    t_low_price = optimal_interval_closed_form(wash, energy, 1000.0, 0.00125)
    t_high_price = optimal_interval_closed_form(wash, energy, 3500.0, 0.00125)
    assert t_high_price < t_low_price


def test_zero_rate_returns_max_interval() -> None:
    """Zero soiling rate -> no revenue loss; longest interval wins."""
    t_closed = optimal_interval_closed_form(150_000.0, 11_000.0, 2000.0, 0.0)
    t_grid, _ = optimal_interval_grid_search(150_000.0, 11_000.0, 2000.0, 0.0)
    assert t_closed == float(config.OPTIMIZE_GRID_MAX_DAYS)
    assert t_grid == float(config.OPTIMIZE_GRID_MAX_DAYS)


def test_ci_band_ordering_sane() -> None:
    """Low rate gives longer T*; CI bounds bracket the point estimate."""
    band = _band()
    wash = config.WASH_COST_TL_CENTRAL
    energy = 11_000.0
    price = 2189.30
    t_slow = optimal_interval_closed_form(
        wash, energy, price, rate_for_scenario(band, "low")
    )
    t_point = optimal_interval_closed_form(
        wash, energy, price, rate_for_scenario(band, "point")
    )
    t_fast = optimal_interval_closed_form(
        wash, energy, price, rate_for_scenario(band, "high")
    )
    assert t_slow >= t_point >= t_fast
    ci_low = min(t_fast, t_slow)
    ci_high = max(t_fast, t_slow)
    assert ci_low <= t_point <= ci_high


def test_total_cost_minimized_at_t_star() -> None:
    """Cost curve minimum sits at closed-form T*."""
    wash = 150_000.0
    energy = 11_000.0
    price = 2000.0
    rate = 0.00125
    t_star = optimal_interval_closed_form(wash, energy, price, rate)
    cost_star = total_cost_per_day(t_star, wash, energy, price, rate)
    cost_late = total_cost_per_day(t_star + 30, wash, energy, price, rate)
    cost_early = total_cost_per_day(max(t_star - 30, 1), wash, energy, price, rate)
    assert cost_star <= cost_late
    assert cost_star <= cost_early
