"""One archived race -> structured records.

The archive stores, per race, five betting-dividend pages from race.kra.co.kr.
Two of them are keyed by a fixed horse, so a race is 3 + 2N pages for a field
of N.

    Scm     단승 · 연승 · 복승   three pools sharing one table
    Both    쌍승                 ordered pair,   header "( 후착 / 선착 )"
    Bc      복연승               unordered pair
    3Bc     삼복승               unordered triple, one page per fixed horse
    3Both   삼쌍승               ordered triple,   header "( 3위 / 2위 )"

Two rules this module keeps, because breaking either loses information that
cannot be recovered later:

1. **Cell values are copied, never interpreted.** `9999.9`, `----` and `-`
   come out as themselves. Deciding what they mean is a separate job with its
   own evidence; a parser that folds them into `None` destroys the difference
   between "no combination", "horse scratched" and "value at the cap".

2. **Coordinates come from the table's own headers, not from fixed offsets.**
   The column carrying horse numbers is found by looking for the header
   `출전 번호`, not by indexing column 2. Scm puts it third (its rows open with
   the win and place columns) while every other page puts it first, and a
   hardcoded index silently mis-reads one of them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .htmltable import Cell, Table, normalize, parse_tables

__all__ = ["Race", "CellRow", "parse_race", "POOL_BY_CAPTION"]

RACE_ID = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_(\d)_(\d+)$")
HORSE_COL_HEADER = "출전 번호"
WIN_GROUP = "단승식"          # the column whose '----' marks a scratch
CANCEL_NOTICE = "취소마공지"
NO_CANCEL = "없습니다"
# 3+ dashes marks a scratched horse; a single dash is a structural blank (the
# lower triangle of a symmetric grid, or a column past the field size).
SCRATCH = re.compile(r"^-{3,}$")
MEETS = {1: "서울", 2: "제주", 3: "부산경남"}

# Caption -> pool. Every page carries exactly one caption of the form
# "출전번호별 ...식의 배당률, 매출총액, 취소마를 제공하는 표".
POOL_BY_CAPTION = {
    "단,연,복승식": "Scm",
    "쌍승식": "Both",
    "복연승식": "Bc",
    "삼복승식": "3Bc",
    "삼쌍승식": "3Both",
}
_CAPTION_POOL = re.compile(r"출전번호별\s*(.+?)의\s*배당률")


@dataclass
class CellRow:
    """One cell of one page, with everything needed to place it again."""
    race_id: str
    page_key: str
    page_variant: str        # fixed-horse number, or "" for single pages
    section: str             # head | body | foot
    row: int
    col: int
    row_header: str          # horse number of the row, "" outside the body
    col_group: str           # pool-level header (단승식 / 복승식 / 쌍승식 …)
    col_header: str          # leaf header (a horse number, usually)
    cell_raw: str            # verbatim
    rowspan: int
    colspan: int
    spanned: int             # 1 if this coordinate is covered by another cell

    FIELDS = ("race_id", "page_key", "page_variant", "section", "row", "col",
              "row_header", "col_group", "col_header", "cell_raw",
              "rowspan", "colspan", "spanned")

    def as_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.FIELDS}


@dataclass
class Race:
    race_id: str
    date: str
    meet: int
    meet_name: str
    race_no: int
    horses: list[int] = field(default_factory=list)      # registered, in table order
    arrival: list[int] = field(default_factory=list)     # finishing order
    scratched: list[int] = field(default_factory=list)   # '----' in the win column
    cancel_notice: str = ""
    sales: dict[str, str] = field(default_factory=dict)  # pool label -> amount text
    pages: dict[str, list[str]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    @property
    def n_registered(self) -> int:
        return len(self.horses)

    def summary(self) -> dict:
        return {
            "race_id": self.race_id, "date": self.date, "meet": self.meet,
            "meet_name": self.meet_name, "race_no": self.race_no,
            "n_registered": self.n_registered,
            "horses": self.horses, "arrival": self.arrival,
            "n_arrival": len(self.arrival), "scratched": self.scratched,
            "cancel_notice": self.cancel_notice, "sales": self.sales,
            "pages": {k: len(v) for k, v in self.pages.items()},
            "problems": self.problems,
        }


class _ArrivalParser(HTMLParser):
    """Finishing order, which sits OUTSIDE the odds table.

        <label for="arrival_mabun">도착마번</label>
        <span> 3&nbsp;&nbsp; 4&nbsp;&nbsp; 6&nbsp;&nbsp; ... </span>

    Reading it here rather than from the grid matters: it is the only race
    outcome in the document, and no odds cell is involved in producing it.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: str | None = None
        self._armed = False
        self._depth = 0
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag.lower() == "label" and a.get("for") == "arrival_mabun":
            self._armed = True
        elif tag.lower() == "span" and self._armed and self.text is None:
            self._depth += 1
        elif self._depth:
            self._depth += 1

    def handle_endtag(self, tag):
        if self._depth:
            self._depth -= 1
            if self._depth == 0 and self.text is None:
                self.text = normalize("".join(self._buf))

    def handle_data(self, data):
        if self._depth:
            self._buf.append(data)


def extract_arrival(html: str) -> list[int]:
    p = _ArrivalParser()
    p.feed(html)
    p.close()
    return [int(x) for x in re.findall(r"\d+", p.text or "")]


def pool_of(table: Table) -> str | None:
    m = _CAPTION_POOL.search(table.caption)
    return POOL_BY_CAPTION.get(m.group(1).strip()) if m else None


def _header_maps(table: Table) -> tuple[dict[int, str], dict[int, str]]:
    """(col -> group header, col -> leaf header) from the expanded `<thead>`.

    The header is two meaningful rows deep: a pool row and a horse-number row.
    Row 0 is the page title spanning the full width, so it is skipped. Taking
    the last header row as the leaf and the one before it as the group works
    for every page shape here without hardcoding widths.
    """
    head = table.section("head")
    if head.n_rows == 0:
        return {}, {}
    leaf_r = head.n_rows - 1
    group_r = max(0, head.n_rows - 2)
    grid = head.grid()
    leaf = {c: grid[(leaf_r, c)].text for c in range(head.n_cols) if (leaf_r, c) in grid}
    group = {c: grid[(group_r, c)].text for c in range(head.n_cols) if (group_r, c) in grid}
    return group, leaf


def _horse_column(leaf: dict[int, str]) -> int | None:
    for col, text in sorted(leaf.items()):
        if text == HORSE_COL_HEADER:
            return col
    return None


SALES_SUFFIX = "매출총액"


def _sales_and_notice(table: Table) -> tuple[dict[str, str], str]:
    """`<tfoot>` carries per-pool turnover and the scratch notice.

    Two label shapes appear across pages, confirmed against raw HTML in
    findings/tfoot_diagnosis.md:

        Scm                    "단승식 : 33,279,700원"   -- one cell, colon-joined
        Both / Bc / 3Bc / 3Both "쌍승식 매출총액" | "289,737,000원"
                                                          -- label and amount in
                                                             adjacent cells, no colon

    Scm's colon format covers only 3 of the 7 pools (+ the Scm-page total);
    the other 4 pools' turnover lives on their own page, in this split shape.
    Both shapes must be read or 4 of 7 pools silently vanish.
    """
    foot = table.section("foot")
    sales: dict[str, str] = {}
    notice = ""
    for r in range(foot.n_rows):
        cells = [c for c in foot.row(r) if not c.spanned]
        texts = [c.text for c in cells]
        if texts and texts[0].startswith(CANCEL_NOTICE):
            notice = texts[1] if len(texts) > 1 else ""
            continue
        i = 0
        while i < len(texts):
            t = texts[i]
            if ":" in t:
                label, _, amount = t.partition(":")
                sales[label.strip()] = amount.strip()
                i += 1
            elif t.endswith(SALES_SUFFIX) and i + 1 < len(texts):
                sales[t[:-len(SALES_SUFFIX)].strip()] = texts[i + 1].strip()
                i += 2
            else:
                i += 1
    return sales, notice


def _pages(payload: dict) -> list[tuple[str, str, str]]:
    """(page_key, variant, html). `_probe` is skipped -- it is a duplicate of
    the first fixed-horse page and would double every advanced-page cell."""
    out = []
    for key, page in (payload.get("pages") or {}).items():
        if isinstance(page, str):
            out.append((key, "", page))
        elif isinstance(page, dict):
            for variant, html in page.items():
                if variant != "_probe" and isinstance(html, str):
                    out.append((key, variant, html))
    return out


def parse_race(payload: dict, *, sections=("body", "foot")) -> tuple[Race, list[CellRow]]:
    """Parse one archived race.

    `sections` selects which parts of each table become cell rows. The header
    is excluded by default because its content is already carried on every
    body cell as `col_group`/`col_header`; pass `("head", "body", "foot")` to
    keep it verbatim as well.
    """
    race_id = payload.get("race_id", "")
    m = RACE_ID.match(race_id)
    if not m:
        raise ValueError(f"unparseable race_id: {race_id!r}")
    y, mo, d, meet, rno = m.groups()
    race = Race(race_id=race_id, date=f"{y}-{mo}-{d}", meet=int(meet),
                meet_name=MEETS.get(int(meet), "?"), race_no=int(rno))

    rows: list[CellRow] = []
    for page_key, variant, html in _pages(payload):
        race.pages.setdefault(page_key, []).append(variant)
        tables = parse_tables(html)
        if not tables:
            race.problems.append(f"{page_key}{'/' + variant if variant else ''}: 표 없음")
            continue
        if len(tables) > 1:
            race.problems.append(
                f"{page_key}{'/' + variant if variant else ''}: 표 {len(tables)}개")
        table = tables[0]
        if pool_of(table) is None:
            race.problems.append(
                f"{page_key}{'/' + variant if variant else ''}: 캡션 불일치 {table.caption!r}")

        group, leaf = _header_maps(table)
        hcol = _horse_column(leaf)
        if hcol is None:
            race.problems.append(
                f"{page_key}{'/' + variant if variant else ''}: '{HORSE_COL_HEADER}' 열 없음")

        body = table.section("body")
        body_grid = body.grid()
        for name in sections:
            sec = table.section(name)
            for cell in sorted(sec.cells, key=lambda c: (c.row, c.col)):
                row_header = ""
                if name == "body" and hcol is not None:
                    h = body_grid.get((cell.row, hcol))
                    row_header = h.text if h else ""
                rows.append(CellRow(
                    race_id=race_id, page_key=page_key, page_variant=variant,
                    section=name, row=cell.row, col=cell.col,
                    row_header=row_header,
                    col_group=group.get(cell.col, ""),
                    col_header=leaf.get(cell.col, ""),
                    cell_raw=cell.text, rowspan=cell.rowspan,
                    colspan=cell.colspan, spanned=int(cell.spanned),
                ))

        # Turnover is collected from every page, not just Scm: Scm's colon
        # format ("단승식 : 33,279,700원") carries only 3 of the 7 pools plus
        # its own page total, while the other 4 pools' turnover lives on
        # their own page (Both/Bc/3Bc/3Both) in a different, split shape --
        # confirmed against raw HTML in findings/tfoot_diagnosis.md. 3Bc and
        # 3Both repeat the same figure across their per-fixed-horse variant
        # pages, so a mismatch across variants is recorded as a problem
        # rather than silently overwritten (the "halt not skip" rule for
        # anything that could hide a real discrepancy).
        page_sales, page_notice = _sales_and_notice(table)
        for label, amount in page_sales.items():
            prior = race.sales.get(label)
            if prior is not None and prior != amount:
                race.problems.append(
                    f"{page_key}{'/' + variant if variant else ''}: "
                    f"매출액 불일치 {label!r} {prior!r} vs {amount!r}")
            else:
                race.sales[label] = amount

        # Race-level facts other than turnover are taken from Scm, the only
        # page that carries them.
        if page_key == "Scm":
            race.arrival = extract_arrival(html)
            race.cancel_notice = page_notice
            win_col = next((c for c, g in sorted(group.items()) if g == WIN_GROUP), None)
            if hcol is None or win_col is None:
                race.problems.append(f"Scm: '{WIN_GROUP}' 열을 찾지 못함")
            else:
                for r in range(body.n_rows):
                    h = body_grid.get((r, hcol))
                    if h is None or not h.text.isdigit():
                        continue
                    race.horses.append(int(h.text))
                    win = body_grid.get((r, win_col))
                    if win is not None and SCRATCH.match(win.text):
                        race.scratched.append(int(h.text))

    if not race.horses:
        race.problems.append("Scm: 등록 마번을 읽지 못함")
    if not race.arrival:
        race.problems.append("Scm: 도착마번 없음")
    return race, rows
