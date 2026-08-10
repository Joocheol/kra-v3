#!/usr/bin/env python3
"""Process hygiene gate. Adapted from the v1 repository's scripts/validate.sh.

Runs on every PR, before anything expensive. Cheap checks that catch the
failure modes which are hard to see by reading.

    1. design documents exist and are non-empty (they are build dependencies)
    2. no unresolved markers (TODO / FIXME / TBD / and their Korean forms)
    3. no control characters in tracked text
    4. bibliography closes in BOTH directions when a .bib exists
    5. no duplicate LaTeX labels
    6. REVIEW_REQUEST.md header is parseable and its inputs exist

Check 4 is the one that matters most. A fabricated reference either is not in
the .bib (missing key, fail) or is in the .bib without being cited (unused key,
fail). Hallucinated citations become structurally impossible rather than a
thing the author is asked to be careful about.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

REQUIRED = ["PROCESS.md", "CONVENTIONS.md", "CLAIMS.md", "FROZEN.txt"]
MARKERS = re.compile(r"TODO|FIXME|TBD|XXX|\uc791\uc131 \uc608\uc815|\ucd94\ud6c4 \uc791\uc131|\uc5ec\uae30\uc5d0 \ucd94\uac00")
TEXTY = (".md", ".tex", ".py", ".txt", ".bib", ".yml", ".yaml", ".mjs", ".sh")
SKIP_MARKER_CHECK = {"PROCESS.md", "CONVENTIONS.md", "BACKLOG.md", "OPEN_ITEMS.md",
                     "EXPLORATION_LOG.md", "CLAIMS.md", "FROZEN.txt",
                     "scripts/check_process.py"}

problems: list[str] = []


def tracked_files() -> list[pathlib.Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [pathlib.Path(p) for p in out.splitlines() if p]


def check_required() -> None:
    for name in REQUIRED:
        p = ROOT / name
        if not p.exists() or p.stat().st_size == 0:
            problems.append(f"required file missing or empty: {name}")


def check_markers_and_controls(files: list[pathlib.Path]) -> None:
    for rel in files:
        if rel.suffix not in TEXTY:
            continue
        posix = rel.as_posix()
        if posix.startswith(("templates/", "prompts/", "review/")):
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if any(ord(c) < 32 and c not in "\n\t\r" for c in text):
            problems.append(f"{posix}: control character in tracked text")
        if posix in SKIP_MARKER_CHECK:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if MARKERS.search(line):
                problems.append(f"{posix}:{n}: unresolved marker \u2014 {line.strip()[:70]}")


def check_bibliography(files: list[pathlib.Path]) -> None:
    bibs = [f for f in files if f.suffix == ".bib"]
    texs = [f for f in files if f.suffix == ".tex"]
    if not bibs or not texs:
        return
    text = "\n".join((ROOT / f).read_text(encoding="utf-8") for f in texs)
    bib = "\n".join((ROOT / f).read_text(encoding="utf-8") for f in bibs)

    bib_keys = set(re.findall(r"@\w+\s*\{\s*([^,\s]+)", bib))
    groups = re.findall(
        r"\\cite(?:alp|alt|author|num|p|t|year|yearpar)?\*?"
        r"(?:\[[^]]*\])?(?:\[[^]]*\])?\{([^}]+)\}", text)
    cite_keys = {k.strip() for g in groups for k in g.split(",") if k.strip()}

    for k in sorted(cite_keys - bib_keys):
        problems.append(f"bibliography: cited but not in .bib \u2014 {k}")
    for k in sorted(bib_keys - cite_keys):
        problems.append(f"bibliography: in .bib but never cited \u2014 {k} "
                        "(uncited entries are how fabricated references survive)")

    labels = re.findall(r"\\label\{([^}]+)\}", text)
    for lab in sorted({l for l in labels if labels.count(l) > 1}):
        problems.append(f"duplicate LaTeX label: {lab}")


def check_review_request() -> None:
    rr = ROOT / "REVIEW_REQUEST.md"
    if not rr.exists():
        return
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import critique
        meta = critique.parse_request(rr)
    except SystemExit as exc:
        problems.append(f"REVIEW_REQUEST.md: {exc}")
        return
    for rel in meta.get("inputs", []) + meta.get("context", []):
        if not (ROOT / rel).exists():
            problems.append(f"REVIEW_REQUEST.md lists a nonexistent input: {rel}")


def main() -> None:
    files = tracked_files()
    check_required()
    check_markers_and_controls(files)
    check_bibliography(files)
    check_review_request()

    if problems:
        print(f"[process] FAIL \u2014 {len(problems)}\uac74\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        sys.exit(1)
    print(f"[process] PASS \u2014 {len(files)} tracked files")


if __name__ == "__main__":
    main()
