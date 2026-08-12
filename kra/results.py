"""Parse the winning dividends from a KRA detailed race-result page.

The betting-grid pages deliberately preserve the display cap ``9999.9``.
KRA's detailed result page is a different source: it prints the dividend that
was actually paid for the winning combination, including values above that
cap.  This module keeps the two sources separate and parses only the latter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from .htmltable import parse_tables

__all__ = [
    "WinningDividend",
    "detail_url",
    "parse_winning_dividends",
    "parse_winning_trifecta",
    "ticket_candidates",
]

DIVIDEND_CAPTION = "배당률의 정보를 제공하는 표"
DISPLAY_CAP = Decimal("9999.9")

# Number of horses in one winning combination, by the labels printed on the
# detailed result page.  Parsing every pool lets the collector recover capped
# winning payouts without assuming that only trifecta can exceed the display
# limit.
POOL_SIZES = {
    "단승식": 1,
    "연승식": 1,
    "복승식": 2,
    "쌍승식": 2,
    "복연승식": 2,
    "삼복승식": 3,
    "삼쌍승식": 3,
}

_CIRCLED = "\u2460-\u2473"  # ① through ⑳
_ODDS = r"[0-9][0-9,]*(?:\.[0-9]+)?"


@dataclass(frozen=True)
class WinningDividend:
    pool: str
    combination: tuple[int, ...]
    odds: Decimal


def detail_url(race_id: str) -> str:
    """Official KRA detailed-result URL for ``YYYY-MM-DD_meet_race``."""
    try:
        date, meet, race_no = race_id.split("_")
    except ValueError as exc:
        raise ValueError(f"unparseable race_id: {race_id!r}") from exc
    if not (date.replace("-", "").isdigit() and meet.isdigit() and race_no.isdigit()):
        raise ValueError(f"unparseable race_id: {race_id!r}")
    return (
        "https://race.kra.co.kr/raceScore/ScoretableDetailList.do"
        f"?Act=04&Sub=1&meet={int(meet)}"
        f"&realRcDate={date.replace('-', '')}&realRcNo={int(race_no)}"
    )


def _horse_number(char: str) -> int:
    n = ord(char) - 0x245F
    if not 1 <= n <= 20:
        raise ValueError(f"not a circled horse number: {char!r}")
    return n


def _parse_pool_cell(text: str) -> list[WinningDividend]:
    label, sep, payload = text.partition(":")
    label = label.strip()
    if not sep or label not in POOL_SIZES:
        return []
    size = POOL_SIZES[label]
    pattern = re.compile(
        rf"((?:[{_CIRCLED}]\s*){{{size}}})\s*({_ODDS})"
    )
    out = []
    for match in pattern.finditer(payload):
        combo = tuple(_horse_number(c) for c in re.findall(rf"[{_CIRCLED}]", match[1]))
        out.append(WinningDividend(label, combo, Decimal(match[2].replace(",", ""))))
    return out


def parse_winning_dividends(html: str) -> list[WinningDividend]:
    """Return all payouts printed in the detailed-result dividend table.

    More than one entry per pool is valid (place, quinella-place, or a dead
    heat), so callers must select by both pool and winning combination.
    """
    matches = [t for t in parse_tables(html) if t.caption == DIVIDEND_CAPTION]
    if len(matches) != 1:
        raise ValueError(
            f"expected one {DIVIDEND_CAPTION!r}, found {len(matches)}"
        )
    out = []
    for cell in matches[0].section("body").cells:
        if not cell.spanned:
            out.extend(_parse_pool_cell(cell.text))
    return out


def parse_winning_trifecta(html: str) -> list[WinningDividend]:
    return [d for d in parse_winning_dividends(html) if d.pool == "삼쌍승식"]


def ticket_candidates(
    sales_won: int,
    displayed_odds: Decimal,
    *,
    take_fraction: Fraction = Fraction(73, 100),
    ticket_won: int = 100,
    pool_multiplier: int = 1,
) -> range:
    """Integer 100-won ticket counts consistent with a one-decimal payout.

    With ``O = take_fraction * sales / (ticket_won * n)``, KRA displays O to
    one decimal.  The exact rounding interval is solved with integer
    arithmetic; no binary floating-point boundary is involved.  Half-way
    cases use the conventional half-up interval.
    """
    tenths = displayed_odds * 10
    if tenths != tenths.to_integral_value():
        raise ValueError(f"payout is not displayed to one decimal: {displayed_odds}")
    d = int(tenths)
    if sales_won <= 0 or d <= 0 or ticket_won <= 0 or pool_multiplier <= 0:
        return range(0)

    # 10*O = A/(B*n).
    a = 10 * take_fraction.numerator * sales_won
    b = take_fraction.denominator * ticket_won * pool_multiplier

    # d - 1/2 <= A/(B*n) < d + 1/2
    # therefore 2A/[B(2d+1)] < n <= 2A/[B(2d-1)].
    lower = Fraction(2 * a, b * (2 * d + 1))
    upper = Fraction(2 * a, b * (2 * d - 1))
    first = lower.numerator // lower.denominator + 1
    last = upper.numerator // upper.denominator
    return range(first, last + 1) if first <= last else range(0)
