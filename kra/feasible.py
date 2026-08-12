"""Exact integer bounds for capped pari-mutuel dividend grids.

The public grid stores a displayed dividend, not the number of 100-won
tickets.  This module translates one-decimal dividends back to integer ticket
intervals and combines the intervals with the pool-total accounting identity.
Binary floating point is deliberately avoided at every boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction


DISPLAY_CAP = Decimal("9999.9")
TAKE_FRACTION = Fraction(73, 100)
TICKET_WON = 100


def _ceil(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def displayed_ticket_interval(
    sales_won: int,
    displayed_odds: Decimal,
    *,
    take_fraction: Fraction = TAKE_FRACTION,
    ticket_won: int = TICKET_WON,
    pool_multiplier: int = 1,
    rounding: str = "half_up",
) -> range:
    """Return positive integer ticket counts rounding to ``displayed_odds``.

    KRA prints one decimal place.  The maintained convention is positive
    half-up, ``d - 0.5 <= 10*O < d + 0.5``.  ``half_even`` and ``floor`` are
    exposed only for falsification diagnostics.  ``pool_multiplier`` divides
    the payout resource (quinella-place has multiplier three).  An empty range
    records an incompatibility; callers must not silently repair it.
    """
    tenths = displayed_odds * 10
    if tenths != tenths.to_integral_value():
        raise ValueError(f"not a one-decimal dividend: {displayed_odds}")
    d = int(tenths)
    if sales_won <= 0 or d <= 0 or ticket_won <= 0 or pool_multiplier <= 0:
        return range(0)

    # 10*O = A/(B*n).
    a = 10 * take_fraction.numerator * sales_won
    b = take_fraction.denominator * ticket_won * pool_multiplier
    if rounding == "floor":
        # d <= 10*O < d+1.
        lower = Fraction(a, b * (d + 1))
        upper = Fraction(a, b * d)
        first = lower.numerator // lower.denominator + 1
        last = upper.numerator // upper.denominator
    elif rounding in {"half_up", "half_even"}:
        lower = Fraction(2 * a, b * (2 * d + 1))
        upper = Fraction(2 * a, b * (2 * d - 1))
        if rounding == "half_even" and d % 2 == 0:
            # An even displayed digit owns both exact half-way boundaries.
            first = _ceil(lower)
            last = upper.numerator // upper.denominator
        elif rounding == "half_even":
            # An odd displayed digit owns neither exact half-way boundary.
            first = lower.numerator // lower.denominator + 1
            last = _ceil(upper) - 1
        else:
            first = lower.numerator // lower.denominator + 1
            last = upper.numerator // upper.denominator
    else:
        raise ValueError(f"unknown rounding convention: {rounding!r}")
    return range(first, last + 1) if first <= last else range(0)


def capped_ticket_upper(
    sales_won: int,
    *,
    cap: Decimal = DISPLAY_CAP,
    take_fraction: Fraction = TAKE_FRACTION,
    ticket_won: int = TICKET_WON,
    pool_multiplier: int = 1,
    definition: str = "display_event",
) -> int:
    """Largest positive ticket count consistent with a capped display cell.

    The default observation is the *display event*: under positive half-up,
    every true dividend at least ``cap - 0.05`` displays as the capped value.
    ``strict_true`` retains the narrower ``true dividend > cap`` definition as
    a sensitivity check.  Zero is always a separate possible state, so the
    full candidate set is ``{0, 1, ..., capped_ticket_upper(...)}``.
    """
    if sales_won <= 0 or cap <= 0 or ticket_won <= 0 or pool_multiplier <= 0:
        raise ValueError("sales, cap, ticket size, and multiplier must be positive")
    k = take_fraction * sales_won / (ticket_won * pool_multiplier)
    if definition == "display_event":
        threshold = Fraction(cap - Decimal("0.05"))
        value = k / threshold
        return value.numerator // value.denominator
    if definition == "strict_true":
        return _ceil(k / Fraction(cap)) - 1
    raise ValueError(f"unknown cap definition: {definition!r}")


@dataclass(frozen=True)
class ConstrainedBounds:
    """Sharp bounds implied by identical capped-cell limits and one sum."""

    residual_min: int
    residual_max: int
    min_zero_cells: int
    max_zero_cells: int
    cell_ticket_min: int
    cell_ticket_max: int


def constrained_capped_bounds(
    cell_count: int,
    per_cell_upper: int,
    residual_min: int,
    residual_max: int,
) -> ConstrainedBounds | None:
    """Intersect capped cell boxes with a residual-ticket sum interval.

    Each of ``cell_count`` cells is an integer in ``[0, per_cell_upper]``.
    The sum is allowed to be any integer in ``[residual_min, residual_max]``.
    The returned zero-count bounds are sharp.  ``None`` means that no integer
    allocation satisfies the accounting identity.
    """
    if cell_count < 0 or per_cell_upper < 0 or residual_min > residual_max:
        raise ValueError("invalid constrained-bound inputs")
    capacity = cell_count * per_cell_upper
    lo = max(0, residual_min)
    hi = min(capacity, residual_max)
    if lo > hi:
        return None
    if cell_count == 0:
        if lo == hi == 0:
            return ConstrainedBounds(0, 0, 0, 0, 0, 0)
        return None
    if per_cell_upper == 0:
        return ConstrainedBounds(0, 0, cell_count, cell_count, 0, 0)

    min_zeros = max(0, cell_count - hi)
    min_positive = 0 if lo == 0 else _ceil(Fraction(lo, per_cell_upper))
    max_zeros = cell_count - min_positive
    cell_min = max(0, lo - (cell_count - 1) * per_cell_upper)
    cell_max = min(per_cell_upper, hi)
    return ConstrainedBounds(lo, hi, min_zeros, max_zeros, cell_min, cell_max)
