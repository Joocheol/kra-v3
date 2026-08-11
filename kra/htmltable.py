"""HTML tables -> expanded grids, using the standard library only.

Deliberately generic: nothing in here knows about horse racing. It turns
`<table>` markup into a rectangular grid of cells whose coordinates already
account for `rowspan`/`colspan`, which is what any downstream mapping needs.

Why `html.parser` and not a regex. The tables are machine generated and look
regular, but regexes get the two things wrong that matter here: nested inline
markup inside a cell (`<td><span class="mark_red">7.2</span></td>`) and entity
decoding (`&nbsp;`, `&#183;`). `HTMLParser` handles both, is in the standard
library, and tolerates the unclosed `<col>`/`<br>` tags this markup contains.

Sections are expanded independently. A `rowspan` that crosses `<thead>` into
`<tbody>` is not valid HTML, and keeping the sections apart means a malformed
header cannot silently shift the body's coordinates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

__all__ = ["Cell", "Table", "parse_tables", "normalize"]

# Cell text is normalized on the way out: NBSP is a space, runs collapse, ends
# trim. Everything else is left exactly as it was written. No number parsing,
# no case folding, no stripping of characters that look like noise -- a parser
# that "cleans" values loses the ability to tell a blank from a marker.
_WS = re.compile(r"[\s ]+")


def normalize(text: str) -> str:
    return _WS.sub(" ", text).strip()


@dataclass
class Cell:
    """One cell, at its expanded coordinates.

    `spanned` marks a coordinate covered by another cell's rowspan/colspan
    rather than written there. The text is duplicated across the covered
    coordinates so that column lookups work, but the flag lets a caller tell
    a real cell from its shadow.
    """
    tag: str                      # "td" or "th"
    text: str
    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    spanned: bool = False
    attrs: dict[str, str] = field(default_factory=dict)


@dataclass
class Section:
    name: str                     # "head" | "body" | "foot"
    cells: list[Cell]
    n_rows: int = 0
    n_cols: int = 0

    def grid(self) -> dict[tuple[int, int], Cell]:
        return {(c.row, c.col): c for c in self.cells}

    def row(self, r: int) -> list[Cell]:
        return sorted((c for c in self.cells if c.row == r), key=lambda c: c.col)


@dataclass
class Table:
    caption: str
    sections: dict[str, Section]
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def n_cols(self) -> int:
        return max((s.n_cols for s in self.sections.values()), default=0)

    def section(self, name: str) -> Section:
        return self.sections.get(name, Section(name, [], 0, 0))


class _RawCell:
    __slots__ = ("tag", "parts", "rowspan", "colspan", "attrs")

    def __init__(self, tag: str, attrs: dict[str, str]):
        self.tag = tag
        self.attrs = attrs
        self.parts: list[str] = []
        self.rowspan = _span(attrs.get("rowspan"))
        self.colspan = _span(attrs.get("colspan"))


def _span(v: str | None) -> int:
    """A span attribute, defaulting to 1.

    Anything unparseable or below 1 becomes 1. Treating a bad span as 1 keeps
    the grid rectangular; treating it as 0 would silently drop a column.
    """
    try:
        return max(1, int(str(v).strip()))
    except (TypeError, ValueError):
        return 1


class _TableParser(HTMLParser):
    """Collects every `<table>`, including nested ones, in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[Table] = []
        self._stack: list[dict] = []          # one frame per open <table>
        self._cell: _RawCell | None = None
        self._in_caption = False
        self._caption: list[str] = []

    # -- helpers ---------------------------------------------------------
    @property
    def _top(self) -> dict | None:
        return self._stack[-1] if self._stack else None

    def _flush_cell(self) -> None:
        t = self._top
        if t is not None and self._cell is not None:
            t["row"].append(self._cell)
        self._cell = None

    def _flush_row(self) -> None:
        t = self._top
        if t is None:
            return
        self._flush_cell()
        if t["row"]:
            t["sections"][t["section"]].append(t["row"])
        t["row"] = []

    # -- HTMLParser hooks ------------------------------------------------
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "table":
            self._flush_cell()
            self._stack.append({
                "attrs": a, "caption": "", "section": "body",
                "sections": {"head": [], "body": [], "foot": []}, "row": [],
            })
            return
        if not self._stack:
            return
        t = self._top
        if tag == "caption":
            self._in_caption, self._caption = True, []
        elif tag == "thead":
            self._flush_row(); t["section"] = "head"
        elif tag == "tbody":
            self._flush_row(); t["section"] = "body"
        elif tag == "tfoot":
            self._flush_row(); t["section"] = "foot"
        elif tag == "tr":
            self._flush_row()
        elif tag in ("td", "th"):
            self._flush_cell()
            self._cell = _RawCell(tag, a)
        elif tag == "br" and self._cell is not None:
            # A line break inside a cell is whitespace, not a joiner:
            # "출전<br/>번호" must read "출전 번호", the way a browser renders
            # and copies it. Concatenating would give "출전번호" and every
            # header-keyed comparison downstream would miss.
            self._cell.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "br" and self._cell is not None:
            self._cell.parts.append(" ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if not self._stack:
            return
        t = self._top
        if tag == "caption":
            self._in_caption = False
            t["caption"] = normalize("".join(self._caption))
        elif tag in ("td", "th"):
            self._flush_cell()
        elif tag == "tr":
            self._flush_row()
        elif tag in ("thead", "tbody", "tfoot"):
            self._flush_row(); t["section"] = "body"
        elif tag == "table":
            self._flush_row()
            self._stack.pop()
            self.tables.append(_build(t))

    def handle_data(self, data):
        if self._in_caption:
            self._caption.append(data)
        elif self._cell is not None:
            self._cell.parts.append(data)


def _expand(name: str, rows: list[list[_RawCell]]) -> Section:
    """Place cells on a grid, honouring rowspan/colspan.

    The standard algorithm: walk each row left to right, skipping coordinates
    already claimed by a span from above or to the left.
    """
    taken: set[tuple[int, int]] = set()
    out: list[Cell] = []
    n_cols = 0
    for r, row in enumerate(rows):
        c = 0
        for raw in row:
            while (r, c) in taken:
                c += 1
            text = normalize("".join(raw.parts))
            for dr in range(raw.rowspan):
                for dc in range(raw.colspan):
                    taken.add((r + dr, c + dc))
                    out.append(Cell(
                        tag=raw.tag, text=text, row=r + dr, col=c + dc,
                        rowspan=raw.rowspan, colspan=raw.colspan,
                        spanned=(dr or dc) > 0, attrs=raw.attrs,
                    ))
            c += raw.colspan
            n_cols = max(n_cols, c)
    n_rows = max((cell.row for cell in out), default=-1) + 1
    return Section(name, out, n_rows, n_cols)


def _build(frame: dict) -> Table:
    return Table(
        caption=frame["caption"],
        attrs=frame["attrs"],
        sections={k: _expand(k, v) for k, v in frame["sections"].items()},
    )


def parse_tables(html: str) -> list[Table]:
    """Every table in the document, outermost-last (closing order)."""
    p = _TableParser()
    p.feed(html)
    p.close()
    return p.tables
