"""Deterministic rank-profile mixtures for capped ticket imputation.

The model intentionally separates two questions.  A profile type predicts the
multiset of tail counts after tickets are sorted from large to small.  A second
score then assigns those ranked counts to named combinations.  Keeping these
steps separate prevents a good rank-size fit from being mistaken for evidence
that individual capped cells have been identified.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


DEFAULT_GRID = np.linspace(0.02, 0.98, 25)
CLASS_NAMES = ("diffuse", "intermediate", "concentrated")


@dataclass(frozen=True)
class RankProfileMixture:
    """Three ordered empirical rank-profile types."""

    grid: np.ndarray
    centroids: np.ndarray
    scale: np.ndarray
    labels: np.ndarray
    class_sizes: np.ndarray


def rank_profile(counts: np.ndarray, grid: np.ndarray = DEFAULT_GRID) -> np.ndarray:
    """Return a scale-free log rank profile on a common fractional grid."""
    values = np.asarray(counts, dtype=float)
    if values.ndim != 1 or len(values) < 2 or np.any(values < 0):
        raise ValueError("counts must be a non-negative one-dimensional vector")
    mean = float(values.mean())
    if mean <= 0:
        raise ValueError("counts must have a positive mean")
    ordered = np.sort(values)[::-1] / mean
    positions = (np.arange(len(ordered), dtype=float) + 0.5) / len(ordered)
    return np.interp(grid, positions, np.log1p(ordered))


def _deterministic_kmeans(data: np.ndarray, classes: int) -> tuple[np.ndarray, np.ndarray]:
    """Fit k-means with farthest-first initialization and stable tie breaks."""
    if data.ndim != 2 or not 1 <= classes <= len(data):
        raise ValueError("invalid k-means inputs")
    center = data.mean(axis=0)
    first = int(np.argmax(np.square(data - center).sum(axis=1)))
    chosen = [first]
    while len(chosen) < classes:
        distances = np.min(
            np.stack([
                np.square(data - data[index]).sum(axis=1) for index in chosen
            ]),
            axis=0,
        )
        distances[chosen] = -1.0
        chosen.append(int(np.argmax(distances)))
    centroids = data[chosen].copy()
    labels = np.full(len(data), -1, dtype=np.int64)
    for _ in range(200):
        distances = np.stack([
            np.square(data - centroid).sum(axis=1) for centroid in centroids
        ], axis=1)
        updated = np.argmin(distances, axis=1)
        if np.array_equal(updated, labels):
            break
        labels = updated
        for class_index in range(classes):
            members = data[labels == class_index]
            if len(members):
                centroids[class_index] = members.mean(axis=0)
    return centroids, labels


def fit_rank_profile_mixture(
    profiles: np.ndarray,
    *,
    grid: np.ndarray = DEFAULT_GRID,
    classes: int = 3,
) -> RankProfileMixture:
    """Fit and order empirical types from diffuse to concentrated."""
    values = np.asarray(profiles, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(grid):
        raise ValueError("profile matrix does not match the profile grid")
    if classes != 3:
        raise ValueError("the maintained model prespecifies three interpretable types")
    scale = values.std(axis=0)
    scale = np.maximum(scale, 0.05)
    standardized = (values - values.mean(axis=0)) / scale
    standardized_centroids, labels = _deterministic_kmeans(standardized, classes)
    del standardized_centroids  # raw-space centroids are easier to transfer.
    raw_centroids = np.stack([
        values[labels == class_index].mean(axis=0)
        for class_index in range(classes)
    ])
    head = np.asarray(grid) <= 0.10
    order = np.argsort(raw_centroids[:, head].mean(axis=1), kind="stable")
    remap = np.empty(classes, dtype=np.int64)
    remap[order] = np.arange(classes)
    ordered_labels = remap[labels]
    ordered_centroids = raw_centroids[order]
    sizes = np.asarray([
        int((ordered_labels == class_index).sum()) for class_index in range(classes)
    ])
    return RankProfileMixture(
        grid=np.asarray(grid, dtype=float).copy(),
        centroids=ordered_centroids,
        scale=scale,
        labels=ordered_labels,
        class_sizes=sizes,
    )


def partial_class_probabilities(
    visible_counts: np.ndarray,
    *,
    total_cells: int,
    total_tickets: int,
    mixture: RankProfileMixture,
    max_points: int = 64,
) -> tuple[np.ndarray, np.ndarray]:
    """Classify a race using only its observed high-count head."""
    values = np.sort(np.asarray(visible_counts, dtype=float))[::-1]
    if (
        values.ndim != 1 or len(values) == 0 or total_cells < len(values)
        or total_tickets <= 0
    ):
        raise ValueError("invalid partial-profile inputs")
    if len(values) > max_points:
        selected = np.unique(np.linspace(0, len(values) - 1, max_points).round().astype(int))
        values = values[selected]
        ranks = selected
    else:
        ranks = np.arange(len(values))
    positions = (ranks.astype(float) + 0.5) / total_cells
    observed = np.log1p(values / (total_tickets / total_cells))
    scale = np.interp(positions, mixture.grid, mixture.scale)
    distances = []
    for centroid in mixture.centroids:
        expected = np.interp(positions, mixture.grid, centroid)
        distances.append(float(np.mean(np.square((observed - expected) / scale))))
    distances_array = np.asarray(distances)
    logits = -0.5 * (distances_array - distances_array.min())
    probabilities = np.exp(logits - logits.max())
    probabilities /= probabilities.sum()
    return probabilities, distances_array


def tail_rank_scores(
    mixture: RankProfileMixture,
    class_index: int,
    *,
    total_cells: int,
    visible_cells: int,
) -> np.ndarray:
    """Return decreasing relative weights for the unobserved tail ranks."""
    if not 0 <= class_index < len(mixture.centroids):
        raise ValueError("unknown profile class")
    if not 0 <= visible_cells < total_cells:
        raise ValueError("invalid visible/total cell counts")
    ranks = np.arange(visible_cells, total_cells, dtype=float)
    positions = (ranks + 0.5) / total_cells
    log_relative = np.interp(positions, mixture.grid, mixture.centroids[class_index])
    scores = np.maximum(np.expm1(log_relative), 1e-12)
    return np.sort(scores)[::-1]


def bounded_weight_allocation(
    total: int, scores: np.ndarray, upper: int | np.ndarray
) -> np.ndarray:
    """Allocate an integer total proportionally under scalar or cell bounds."""
    weights = np.asarray(scores, dtype=float)
    uppers = np.broadcast_to(np.asarray(upper, dtype=np.int64), weights.shape).copy()
    if (
        total < 0 or weights.ndim != 1 or len(weights) == 0
        or np.any(weights < 0) or not np.isfinite(weights).all()
        or np.any(uppers < 0) or total > int(uppers.sum())
    ):
        raise ValueError("invalid bounded allocation")
    if total == 0:
        return np.zeros(len(weights), dtype=np.int64)
    if weights.sum() <= 0:
        weights = np.ones(len(weights), dtype=float)
    else:
        weights = np.maximum(weights, 1e-12)
    low, high = 0.0, max(1.0, total / max(weights.min(), 1e-12))
    while np.minimum(uppers, high * weights).sum() < total:
        high *= 2.0
    for _ in range(80):
        middle = (low + high) / 2.0
        if np.minimum(uppers, middle * weights).sum() < total:
            low = middle
        else:
            high = middle
    continuous = np.minimum(uppers, ((low + high) / 2.0) * weights)
    result = np.floor(continuous + 1e-12).astype(np.int64)
    remainder = total - int(result.sum())
    if remainder:
        eligible = np.flatnonzero(result < uppers)
        fractions = np.round(continuous[eligible] - result[eligible], 12)
        order = eligible[np.argsort(-fractions, kind="stable")]
        if remainder > len(order):
            raise AssertionError("allocation remainder exceeds eligible cells")
        result[order[:remainder]] += 1
    if int(result.sum()) != total or np.any(result < 0) or np.any(result > uppers):
        raise AssertionError("bounded rank allocation failed")
    return result


def hidden_total_interval(
    total: int,
    visible_lower: np.ndarray,
    visible_upper: np.ndarray,
    hidden_upper: np.ndarray,
) -> tuple[int, int]:
    """Return the feasible hidden-ticket interval using observables only."""
    lower = np.asarray(visible_lower, dtype=np.int64)
    upper = np.asarray(visible_upper, dtype=np.int64)
    hidden = np.asarray(hidden_upper, dtype=np.int64)
    if (
        total < 0 or lower.ndim != 1 or upper.ndim != 1
        or lower.shape != upper.shape or hidden.ndim != 1 or len(hidden) == 0
        or np.any(lower < 0) or np.any(lower > upper) or np.any(hidden < 0)
    ):
        raise ValueError("invalid ticket intervals")
    hidden_capacity = int(hidden.sum())
    residual_lower = max(0, total - int(upper.sum()))
    residual_upper = min(hidden_capacity, total - int(lower.sum()))
    if residual_lower > residual_upper:
        raise ValueError("ticket intervals are infeasible")
    return residual_lower, residual_upper


def bounded_rank_allocation(total: int, scores: np.ndarray, upper: int) -> np.ndarray:
    """Allocate an integer total across ordered ranks with one common bound."""
    return np.sort(bounded_weight_allocation(total, scores, upper))[::-1]


def assign_ranked_counts(rank_counts: np.ndarray, assignment_scores: np.ndarray) -> np.ndarray:
    """Assign largest fitted counts to the strongest named-cell scores."""
    counts = np.sort(np.asarray(rank_counts, dtype=np.int64))[::-1]
    scores = np.asarray(assignment_scores, dtype=float)
    if counts.ndim != 1 or scores.ndim != 1 or len(counts) != len(scores):
        raise ValueError("rank counts and assignment scores must align")
    order = np.argsort(-scores, kind="stable")
    assigned = np.empty(len(counts), dtype=np.int64)
    assigned[order] = counts
    return assigned
