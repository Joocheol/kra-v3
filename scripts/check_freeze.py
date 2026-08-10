#!/usr/bin/env python3
"""Verify that frozen artifacts still reproduce.

Reads FROZEN.txt and, for each listed artifact, compares the committed file
against a freshly regenerated one at the declared tolerance tier.

    byte       bytes must be identical
    numeric    key columns identical as records, numeric columns within
               tolerance, and any sibling rendered table byte-identical
    invariant  reproduction is NOT required; scripts/check_invariants.py
               decides. For nondeterministic components only.

Usage:
    python scripts/check_freeze.py --regenerate     # CI: rebuild then compare
    python scripts/check_freeze.py                  # compare against .freeze-check/

Exit 0 = frozen results hold. Exit 1 = a headline number moved.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FROZEN = ROOT / "FROZEN.txt"
WORK = ROOT / ".freeze-check"

RTOL = 1e-9
ATOL = 1e-9

# Columns that identify a row rather than measure it. These must match exactly
# even at the numeric tier: a changed sample is never a rounding difference.
KEY_HINTS = ("id", "race", "n_", "market", "pool", "weight", "year", "bin", "band")


def parse_frozen() -> list[tuple[str, pathlib.Path]]:
    if not FROZEN.exists():
        sys.exit("[freeze] FROZEN.txt is missing")
    out = []
    for lineno, line in enumerate(FROZEN.read_text(encoding="utf-8").splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            sys.exit(f"[freeze] FROZEN.txt:{lineno}: expected '<tier> <path>'")
        tier, path = parts[0], parts[1].strip()
        if tier not in ("byte", "numeric", "invariant"):
            sys.exit(f"[freeze] FROZEN.txt:{lineno}: unknown tier {tier!r}")
        out.append((tier, pathlib.Path(path)))
    return out


def tracked(path: pathlib.Path) -> bool:
    return subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(path)],
        cwd=ROOT, capture_output=True).returncode == 0


def regenerate() -> None:
    """Run the pipeline that produces the frozen artifacts."""
    script = ROOT / "scripts" / "regenerate.sh"
    if not script.exists():
        sys.exit("[freeze] scripts/regenerate.sh is missing. It must rebuild "
                 "every artifact listed in FROZEN.txt from source.")
    WORK.mkdir(exist_ok=True)
    print("[freeze] regenerating...")
    subprocess.run(["bash", str(script), str(WORK)], cwd=ROOT, check=True)


def cmp_byte(committed: pathlib.Path, fresh: pathlib.Path) -> str | None:
    if committed.read_bytes() != fresh.read_bytes():
        return "bytes differ"
    return None


def cmp_numeric(committed: pathlib.Path, fresh: pathlib.Path) -> str | None:
    import numpy as np
    import pandas as pd

    a = pd.read_csv(committed, float_precision="round_trip")
    b = pd.read_csv(fresh, float_precision="round_trip")

    if list(a.columns) != list(b.columns):
        return "columns changed"
    if len(a) != len(b):
        return f"row count changed: {len(a)} -> {len(b)}"

    keys = [c for c in a.columns
            if a[c].dtype == object or any(h in c.lower() for h in KEY_HINTS)]
    if keys and a[keys].to_dict("records") != b[keys].to_dict("records"):
        return f"sample membership or key columns changed ({', '.join(keys)})"

    num = [c for c in a.columns if c not in keys]
    if num:
        av, bv = a[num].to_numpy(float), b[num].to_numpy(float)
        if not np.allclose(av, bv, rtol=RTOL, atol=ATOL, equal_nan=True):
            return f"values changed materially; max_abs_delta={np.nanmax(np.abs(av - bv)):.6g}"

    # A rendered sibling table must track its CSV exactly. This is the
    # renderer-connection check: it catches a hand-edited .tex as well as
    # CSV/TeX drift.
    for suffix in (".tex", ".md"):
        sib = committed.with_suffix(suffix)
        sib_fresh = fresh.with_suffix(suffix)
        if sib.exists() and sib_fresh.exists() and sib.read_bytes() != sib_fresh.read_bytes():
            return f"rendered table {sib.name} changed while CSV held"
    return None


def cmp_invariant(committed: pathlib.Path, fresh: pathlib.Path) -> str | None:
    checker = ROOT / "scripts" / "check_invariants.py"
    if not checker.exists():
        return ("invariant tier used but scripts/check_invariants.py is missing. "
                "Define the invariants before freezing a nondeterministic artifact.")
    r = subprocess.run([sys.executable, str(checker), str(committed), str(fresh)],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        return (r.stdout + r.stderr).strip()[:2000]
    return None


CHECKS = {"byte": cmp_byte, "numeric": cmp_numeric, "invariant": cmp_invariant}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regenerate", action="store_true")
    args = ap.parse_args()

    entries = parse_frozen()
    if not entries:
        print("[freeze] FROZEN.txt lists nothing yet \u2014 nothing to verify.")
        return

    if args.regenerate:
        if WORK.exists():
            shutil.rmtree(WORK)
        regenerate()

    problems: list[str] = []
    for tier, rel in entries:
        committed, fresh = ROOT / rel, WORK / rel
        if not tracked(rel):
            problems.append(f"{rel}: listed in FROZEN.txt but not tracked by git")
            continue
        if not committed.exists() or committed.stat().st_size == 0:
            problems.append(f"{rel}: committed artifact missing or empty")
            continue
        if not fresh.exists():
            problems.append(f"{rel}: regeneration did not produce this file")
            continue
        msg = CHECKS[tier](committed, fresh)
        if msg:
            problems.append(f"{rel} [{tier}]: {msg}")
        else:
            print(f"  OK  {rel} [{tier}]")

    if problems:
        print(f"\n[freeze] FAIL \u2014 {len(problems)}\uac74\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("\n\ub3d9\uacb0\ub41c \uc0b0\ucd9c\ubb3c\uc774 \uc6c0\uc9c1\uc600\uc2b5\ub2c8\ub2e4. \uc14b \uc911 \ud558\ub098\uc785\ub2c8\ub2e4:\n"
              "  1. \uc758\ub3c4\ud55c \ubcc0\uacbd\uc774\uba74 \ucee4\ubc0b\ubcf8\uc744 \uac31\uc2e0\ud558\uace0, \uc5b4\ub5a4 CLAIMS ID\uac00 \uc601\ud5a5\ubc1b\ub294\uc9c0\n"
              "     RESPONSE \ub610\ub294 correction log \uc5d0 \ub0a8\uae30\uc2ed\uc2dc\uc624.\n"
              "  2. \uc758\ub3c4\ud558\uc9c0 \uc54a\uc558\uc73c\uba74 \ubc84\uadf8\uc785\ub2c8\ub2e4.\n"
              "  3. \ube44\uacb0\uc815 \uc131\ubd84\uc774\uba74 tier \ub97c invariant \ub85c \ubc14\uafb8\ub418, \uc65c \uacb0\uc815\ub860\uc801\uc77c \uc218\n"
              "     \uc5c6\ub294\uc9c0 CONVENTIONS.md \uc5d0 \uadfc\uac70\ub97c \ub0a8\uae30\uc2ed\uc2dc\uc624.", file=sys.stderr)
        sys.exit(1)

    print(f"\n[freeze] PASS \u2014 {len(entries)}\uac1c \uc0b0\ucd9c\ubb3c\uc774 \uc7ac\ud604\ub429\ub2c8\ub2e4.")


if __name__ == "__main__":
    main()
