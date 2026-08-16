#!/usr/bin/env python3
"""Plot scale-free trifecta empirical rank profiles for 2018-07-01.

For this historical regime we deliberately avoid converting displayed odds to
integer ticket counts with the maintained 2022+ accounting formula. Within a
race, ticket count is proportional to inverse displayed odds up to a common
pool-wide constant. Normalizing by the relevant race/subset mean removes that
common constant, so inverse odds identify the rank-profile shape (apart from
0.1 display rounding) without imposing a historical takeout/unit convention.
"""
from __future__ import annotations

import csv
import gzip
import pathlib
import re
from collections import defaultdict
from decimal import Decimal

import matplotlib.pyplot as plt
import numpy as np

from analyze_masked_reconstruction import _won, load_races
from kra.feasible import DISPLAY_CAP

DATE = "2018-07-01"
NUMERIC_ODDS = re.compile(r"^[0-9]+\.[0-9]$")
THRESHOLDS = (5000.0, 6000.0, 7000.0, 8000.0, 9000.0)


def load_day_grids(data: pathlib.Path, races: dict[str, dict]):
    wanted = {
        race_id for race_id in races
        if race_id.startswith(DATE + "_") and race_id.split("_")[1] in {"1", "3"}
    }
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


def normalized_inverse_odds(values):
    odds = np.asarray([float(value) for _, value in values], dtype=float)
    if np.any(~np.isfinite(odds)) or np.any(odds <= 0):
        raise ValueError("all uncapped displayed odds must be positive and finite")
    weights = 1.0 / odds
    ordered = np.sort(weights)[::-1]
    return ordered / ordered.mean(), odds


def threshold_profile(values, threshold: float):
    odds = np.asarray([float(value) for _, value in values], dtype=float)
    selected = odds > threshold
    tail_odds = odds[selected]
    if len(tail_odds) < 3:
        return None
    weights = 1.0 / tail_odds
    ordered = np.sort(weights)[::-1]
    normalized = ordered / ordered.mean()
    positions = (np.arange(len(normalized), dtype=float) + 0.5) / len(normalized)
    return positions, normalized, len(tail_odds), len(odds)


def envelope(profiles, common):
    matrix = np.stack([np.interp(common, x, y) for _, x, y in profiles])
    return (
        np.median(matrix, axis=0),
        np.quantile(matrix, 0.25, axis=0),
        np.quantile(matrix, 0.75, axis=0),
        matrix,
    )


def plot_profile_bundle(profiles, common, title, ylabel, output):
    median, q25, q75, _ = envelope(profiles, common)
    fig, ax = plt.subplots(figsize=(10, 6.2))
    for race_id, x, y in profiles:
        meet = "Seoul" if race_id.split("_")[1] == "1" else "Busan-Gyeongnam"
        ax.plot(x * 100, y, linewidth=0.8, alpha=0.35, label=meet)
    ax.fill_between(common * 100, q25, q75, alpha=0.16, label="Interquartile range")
    ax.plot(common * 100, median, linewidth=2.6, label="Median profile")
    ax.set_yscale("log")
    ax.set_xlabel("Rank percentile within selected cells (most-bet → least-bet)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, which="both", linewidth=0.35, alpha=0.35)
    handles, labels = ax.get_legend_handles_labels()
    unique = {}
    for h, label in zip(handles, labels):
        if label not in unique:
            unique[label] = h
    ax.legend(unique.values(), unique.keys(), frameon=False)
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main() -> int:
    data = pathlib.Path("데이터")
    outdir = pathlib.Path("artifacts/20180701_rank_profiles")
    outdir.mkdir(parents=True, exist_ok=True)
    races = load_races(data / "races.jsonl.gz")
    grids = load_day_grids(data, races)

    profiles = []
    summary = []
    for race_id in sorted(grids):
        normalized, odds = normalized_inverse_odds(grids[race_id])
        positions = (np.arange(len(normalized), dtype=float) + 0.5) / len(normalized)
        profiles.append((race_id, positions, normalized))
        sales = _won(races[race_id]["sales"]["삼쌍승식"])
        summary.append((
            race_id, len(normalized), sales,
            f"{float(np.min(odds)):.1f}", f"{float(np.max(odds)):.1f}", 0,
        ))

    common = np.linspace(0.005, 0.995, 300)
    plot_profile_bundle(
        profiles, common,
        "Empirical trifecta rank profiles — 2018-07-01 (17 uncapped races)",
        "Relative ticket weight (1/odds, divided by race mean; log scale)",
        outdir / "empirical_rank_profiles_2018-07-01.png",
    )

    fig, ax = plt.subplots(figsize=(10, 6.2))
    for _, _, y in profiles:
        ranks = np.arange(1, len(y) + 1)
        ax.plot(ranks, y, linewidth=0.8, alpha=0.35)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Rank (log scale)")
    ax.set_ylabel("Relative ticket weight (1/odds, divided by race mean; log scale)")
    ax.set_title("Log-log rank-size view — 2018-07-01 trifecta")
    ax.grid(True, which="both", linewidth=0.35, alpha=0.35)
    fig.tight_layout()
    fig.savefig(outdir / "rank_size_loglog_2018-07-01.png", dpi=180)
    plt.close(fig)

    threshold_rows = []
    median_by_threshold = {}
    for threshold in THRESHOLDS:
        tail_profiles = []
        cell_counts = []
        fractions = []
        for race_id in sorted(grids):
            result = threshold_profile(grids[race_id], threshold)
            if result is None:
                continue
            x, y, n_tail, n_total = result
            tail_profiles.append((race_id, x, y))
            cell_counts.append(n_tail)
            fractions.append(n_tail / n_total)
        if not tail_profiles:
            continue

        median, q25, q75, matrix = envelope(tail_profiles, common)
        median_by_threshold[threshold] = median
        plot_profile_bundle(
            tail_profiles, common,
            f"Trifecta tail rank profiles — odds > {threshold:,.0f} — 2018-07-01",
            "Relative ticket weight within selected tail (1/odds ÷ tail mean; log scale)",
            outdir / f"tail_rank_profiles_gt_{int(threshold)}.png",
        )

        for percentile in (0.10, 0.50, 0.90):
            idx = int(np.argmin(np.abs(common - percentile)))
            ratio = float(q75[idx] / q25[idx]) if q25[idx] > 0 else float("nan")
            threshold_rows.append((
                int(threshold), len(tail_profiles), int(sum(cell_counts)),
                float(np.median(cell_counts)), float(np.median(fractions)),
                int(round(percentile * 100)), float(median[idx]), ratio,
            ))

    fig, ax = plt.subplots(figsize=(10, 6.2))
    for threshold in THRESHOLDS:
        if threshold in median_by_threshold:
            ax.plot(common * 100, median_by_threshold[threshold], linewidth=2.0,
                    label=f"> {threshold:,.0f}")
    ax.set_yscale("log")
    ax.set_xlabel("Rank percentile within selected tail (most-bet → least-bet)")
    ax.set_ylabel("Median relative ticket weight within tail (log scale)")
    ax.set_title("Median tail shapes by odds threshold — 2018-07-01")
    ax.grid(True, which="both", linewidth=0.35, alpha=0.35)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(outdir / "tail_threshold_median_comparison.png", dpi=180)
    plt.close(fig)

    with (outdir / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "race_id", "cells", "trifecta_sales_won", "min_displayed_odds",
            "max_displayed_odds", "cap_cells",
        ])
        writer.writerows(summary)

    with (outdir / "threshold_summary.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "threshold", "races", "selected_cells", "median_cells_per_race",
            "median_fraction_of_race_cells", "rank_percentile", "median_relative_weight",
            "iqr_ratio_q75_over_q25",
        ])
        writer.writerows(threshold_rows)

    print(f"races={len(profiles)}")
    print("cap_cells_total=0")
    for threshold in THRESHOLDS:
        rows = [row for row in threshold_rows if row[0] == int(threshold)]
        if rows:
            first = rows[0]
            print(
                f"threshold>{int(threshold)} races={first[1]} cells={first[2]} "
                f"median_cells_per_race={first[3]:.1f} "
                f"median_fraction={first[4]:.4f}"
            )
            for row in rows:
                print(
                    f"  p{row[5]} median={row[6]:.4f} iqr_ratio={row[7]:.4f}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
