#!/usr/bin/env python3
"""Plot scale-free trifecta empirical rank profiles for 2018-07-01."""
from __future__ import annotations

import csv
import gzip
import pathlib
import re
from collections import defaultdict
from decimal import Decimal

import matplotlib.pyplot as plt
import numpy as np

from analyze_masked_reconstruction import _won, bounded_integer_projection, load_races
from kra.feasible import DISPLAY_CAP, displayed_ticket_interval

DATE = "2018-07-01"
NUMERIC_ODDS = re.compile(r"^[0-9]+\.[0-9]$")


def load_day_grids(data: pathlib.Path, races: dict[str, dict]):
    wanted = {race_id for race_id in races if race_id.startswith(DATE + "_") and race_id.split("_")[1] in {"1", "3"}}
    path = data / "cells" / "page_key=3Both" / "2018-07.csv.gz"
    grids = defaultdict(list)
    seen = defaultdict(set)
    capped = defaultdict(int)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            race_id = row["race_id"]
            if race_id not in wanted or row["section"] != "body" or row["spanned"] != "0":
                continue
            raw = row["cell_raw"]
            if raw == str(DISPLAY_CAP):
                capped[race_id] += 1
            if not NUMERIC_ODDS.fullmatch(raw):
                continue
            axes = (row["page_variant"], row["col_header"], row["row_header"])
            if not all(x.isdigit() for x in axes):
                continue
            combo = tuple(map(int, axes))
            if combo in seen[race_id]:
                raise ValueError(f"{race_id}: duplicate {combo}")
            seen[race_id].add(combo)
            grids[race_id].append((combo, Decimal(raw)))
    missing = wanted - set(grids)
    if missing:
        raise ValueError(f"missing grids: {sorted(missing)}")
    if any(capped.values()):
        raise ValueError(f"unexpected 9999.9 cells: {dict(capped)}")
    for race_id, values in grids.items():
        race = races[race_id]
        n = len(set(race["horses"]) - set(race.get("scratched") or []))
        expected = n * (n - 1) * (n - 2)
        if len(values) != expected:
            raise ValueError(f"{race_id}: got {len(values)}, expected {expected}")
    return dict(grids)


def reconstruct(sales_won: int, values):
    total = sales_won // 100
    lower = np.zeros(len(values), dtype=np.int64)
    upper = np.zeros(len(values), dtype=np.int64)
    target = np.zeros(len(values), dtype=float)
    for i, (_, odds) in enumerate(values):
        candidates = displayed_ticket_interval(sales_won, odds)
        if not candidates:
            raise ValueError(f"incompatible odds {odds}")
        lower[i] = candidates.start
        upper[i] = candidates.stop - 1
        target[i] = 0.73 * total / float(odds)
    return bounded_integer_projection(target, lower, upper, total)


def main() -> int:
    data = pathlib.Path("데이터")
    outdir = pathlib.Path("artifacts/20180701_rank_profiles")
    outdir.mkdir(parents=True, exist_ok=True)
    races = load_races(data / "races.jsonl.gz")
    grids = load_day_grids(data, races)

    profiles = []
    summary = []
    for race_id in sorted(grids):
        sales = _won(races[race_id]["sales"]["삼쌍승식"])
        counts = reconstruct(sales, grids[race_id])
        ordered = np.sort(counts.astype(float))[::-1]
        positions = (np.arange(len(ordered), dtype=float) + 0.5) / len(ordered)
        normalized = ordered / ordered.mean()
        profiles.append((race_id, positions, normalized))
        summary.append((race_id, len(ordered), int(counts.sum()), int(ordered[0]), int(ordered[-1]), int((ordered == 0).sum())))

    common = np.linspace(0.005, 0.995, 300)
    matrix = np.stack([np.interp(common, x, y) for _, x, y in profiles])
    median = np.median(matrix, axis=0)
    q25 = np.quantile(matrix, 0.25, axis=0)
    q75 = np.quantile(matrix, 0.75, axis=0)

    fig, ax = plt.subplots(figsize=(10, 6.2))
    for race_id, x, y in profiles:
        meet = "Seoul" if race_id.split("_")[1] == "1" else "Busan-Gyeongnam"
        ax.plot(x * 100, y, linewidth=0.8, alpha=0.35, label=meet)
    ax.fill_between(common * 100, q25, q75, alpha=0.16, label="Interquartile range")
    ax.plot(common * 100, median, linewidth=2.6, label="Median profile")
    ax.set_yscale("log")
    ax.set_xlabel("Rank percentile (most-bet → least-bet)")
    ax.set_ylabel("Ticket count / race mean ticket count (log scale)")
    ax.set_title("Empirical trifecta rank profiles — 2018-07-01 (17 races, no 9999.9 cap)")
    ax.grid(True, which="both", linewidth=0.35, alpha=0.35)
    handles, labels = ax.get_legend_handles_labels()
    unique = {}
    for h, l in zip(handles, labels):
        if l not in unique:
            unique[l] = h
    ax.legend(unique.values(), unique.keys(), frameon=False)
    fig.tight_layout()
    fig.savefig(outdir / "empirical_rank_profiles_2018-07-01.png", dpi=180)
    plt.close(fig)

    # Log-log rank-size diagnostic, using raw ranks and normalized ticket counts.
    fig, ax = plt.subplots(figsize=(10, 6.2))
    for race_id, x, y in profiles:
        ranks = np.arange(1, len(y) + 1)
        ax.plot(ranks, y, linewidth=0.8, alpha=0.35)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Rank (log scale)")
    ax.set_ylabel("Ticket count / race mean ticket count (log scale)")
    ax.set_title("Log-log rank-size view — 2018-07-01 trifecta")
    ax.grid(True, which="both", linewidth=0.35, alpha=0.35)
    fig.tight_layout()
    fig.savefig(outdir / "rank_size_loglog_2018-07-01.png", dpi=180)
    plt.close(fig)

    with (outdir / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["race_id", "cells", "total_tickets", "max_cell_tickets", "min_cell_tickets", "zero_cells"])
        writer.writerows(summary)

    print(f"races={len(profiles)}")
    print(f"all_uncapped={all(race_id in grids for race_id, *_ in profiles)}")
    for row in summary:
        print(",".join(map(str, row)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
