#!/usr/bin/env python3
"""Block the next phase until every binding critique item carries a verdict.

Usage:
    python scripts/gate.py --phase P1
    python scripts/gate.py --phase M --milestone M2

Exit 0 = open, exit 1 = blocked. This is the only thing standing between the
project and the failure mode where critique gets read and then ignored.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REVIEW_DIR = ROOT / "review"

VERDICTS = {"\ubc18\ubc15", "\uc218\uc815", "\ud3ec\uae30", "\ubc31\ub85c\uadf8"}
MIN_GROUND_CHARS = 20

HEADER_RE = re.compile(r"^#{1,6}\s*(K\d+)\b", re.MULTILINE)
FIELD_RE = re.compile(r"^\s*(\ud310\uc815|\uadfc\uac70)\s*[:\uff1a]\s*(.*)$", re.MULTILINE)


def parse_response(text: str) -> dict[str, dict[str, str]]:
    """Split a RESPONSE file into {item_id: {verdict, grounds}}."""
    out: dict[str, dict[str, str]] = {}
    marks = list(HEADER_RE.finditer(text))
    for i, m in enumerate(marks):
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        rec = {"\ud310\uc815": "", "\uadfc\uac70": ""}
        for f in FIELD_RE.finditer(body):
            key, val = f.group(1), f.group(2).strip()
            if key == "\uadfc\uac70":
                # grounds may run over several lines until the next field
                tail = body[f.end():]
                stop = FIELD_RE.search(tail)
                val = (val + "\n" + (tail[:stop.start()] if stop else tail)).strip()
            rec[key] = val
        out[m.group(1)] = rec
    return out


def check_round(tag: str, rnd: int) -> list[str]:
    problems: list[str] = []
    cpath = REVIEW_DIR / f"CRITIQUE_{tag}_r{rnd}.json"
    payload = json.loads(cpath.read_text(encoding="utf-8"))
    binding = payload.get("binding", [])
    if not binding:
        print(f"  r{rnd}: \ud310\uc815 \uc758\ubb34 \ud56d\ubaa9 \uc5c6\uc74c \u2014 \ud1b5\uacfc")
        return problems

    rpath = REVIEW_DIR / f"RESPONSE_{tag}_r{rnd}.md"
    if not rpath.exists():
        return [f"r{rnd}: {rpath.relative_to(ROOT)} \uc5c6\uc74c "
                f"(\ud310\uc815 \uc758\ubb34 \ud56d\ubaa9 {len(binding)}\uac1c)"]

    answers = parse_response(rpath.read_text(encoding="utf-8"))

    for item in binding:
        iid = item["id"]
        rec = answers.get(iid)
        if rec is None:
            problems.append(f"r{rnd}/{iid}: \uc751\ub2f5 \uc5c6\uc74c \u2014 {item['title']}")
            continue
        verdict, ground = rec.get("\ud310\uc815", ""), rec.get("\uadfc\uac70", "")
        if verdict not in VERDICTS:
            problems.append(
                f"r{rnd}/{iid}: \ud310\uc815\uc774 {sorted(VERDICTS)} \uc911 \ud558\ub098\uac00 \uc544\ub2d8 "
                f"(\ubc1b\uc740 \uac12: {verdict!r})")
        if len(ground) < MIN_GROUND_CHARS:
            problems.append(f"r{rnd}/{iid}: \uadfc\uac70\uac00 \ube44\uc5c8\uac70\ub098 \ub108\ubb34 \uc9e7\uc74c")
        if verdict == "\ubc31\ub85c\uadf8" and "BACKLOG" not in ground.upper():
            problems.append(f"r{rnd}/{iid}: \ubc31\ub85c\uadf8 \ud310\uc815\uc740 BACKLOG.md \ud56d\ubaa9 \ubc88\ud638\ub97c \uadfc\uac70\uc5d0 \uba85\uc2dc")

    if not problems:
        print(f"  r{rnd}: {len(binding)}\uac1c \ud56d\ubaa9 \uc804\ubd80 \ud310\uc815\ub428 \u2014 \ud1b5\uacfc")
    return problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=("P0", "P1", "P2", "P3", "M"))
    ap.add_argument("--milestone")
    args = ap.parse_args()

    if args.phase == "M" and not args.milestone:
        sys.exit("[gate] --phase M requires --milestone")
    tag = args.milestone if args.phase == "M" else args.phase

    rounds = sorted(int(p.stem.rsplit("_r", 1)[1])
                    for p in REVIEW_DIR.glob(f"CRITIQUE_{tag}_r*.json"))
    if not rounds:
        sys.exit(f"[gate] BLOCKED: {tag} \ube44\ud3c9\uc774 \uc544\uc9c1 \uc2e4\ud589\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4. "
                 f"\uba3c\uc800 `make critique-{tag}`")

    print(f"[gate] {tag}: \ub77c\uc6b4\ub4dc {rounds} \uac80\uc0ac")
    problems: list[str] = []
    for rnd in rounds:
        problems += check_round(tag, rnd)

    if problems:
        print(f"\n[gate] BLOCKED \u2014 {len(problems)}\uac74\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(f"\n\ud15c\ud50c\ub9bf: templates/RESPONSE_TEMPLATE.md", file=sys.stderr)
        sys.exit(1)

    print(f"[gate] OPEN \u2014 {tag} \ud1b5\uacfc")


if __name__ == "__main__":
    main()
