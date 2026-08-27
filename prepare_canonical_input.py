#!/usr/bin/env python3
"""Verify kra-data v1.0 and build a separate kra-v3-compatible input tree."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from kra.canonical import PROTOCOL_YEARS, materialize_legacy_input, verify_v1_source


def _years(value: str) -> tuple[int, ...]:
    result: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            first, last = map(int, part.split("-", 1))
            result.update(range(first, last + 1))
        elif part:
            result.add(int(part))
    if not result:
        raise argparse.ArgumentTypeError("empty year selection")
    return tuple(sorted(result))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path,
        default=Path(os.environ.get("KRA_CANONICAL_DIR", "canonical-v1.0")),
        help="local copy of Dropbox /앱/kra-data/research/2016-2025/",
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/canonical-v1.0"))
    parser.add_argument(
        "--years", type=_years,
        default=PROTOCOL_YEARS,
        help="comma/range selection (default preserves the frozen research protocol)",
    )
    parser.add_argument(
        "--check-only", action="store_true",
        help="verify the official bundle without materializing the legacy interface",
    )
    args = parser.parse_args()
    if args.check_only:
        manifest = verify_v1_source(args.source)
        print(json.dumps({
            "status": "ok", "schema_version": manifest["schema_version"],
            "source": str(args.source),
        }, ensure_ascii=False, sort_keys=True))
        return
    result = materialize_legacy_input(args.source, args.output, years=args.years)
    print(json.dumps(result["selection"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

