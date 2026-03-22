"""PCA -> UMAP projection pipeline with clustering and quality detection.

Adapted from Parthenon's ai/app/services/projection.py for standalone use
in the DevBrain visualizer.
"""
import hashlib
import logging
import time
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)


@dataclass
class ProjectedPoint:
    id: str
    x: float
    y: float
    z: float
    metadata: dict
    cluster_id: int = 0


@dataclass
class Cluster:
    id: int
    label: str
    centroid: list[float]
    size: int


@dataclass
class QualityReport:
    outlier_ids: list[str]
    duplicate_pairs: list[tuple[str, str]]
    orphan_ids: list[str]


@dataclass
class ProjectionResult:
    points: list[ProjectedPoint]
    clusters: list[Cluster]
    quality: QualityReport
    stats: dict


# ── Cache ────────────────────────────────────────────────────────────────────

_cache: dict[str, tuple[float, ProjectionResult]] = {}
CACHE_TTL = 600  # 10 minutes


def _cache_key(collection_name: str, sample_size: int, total_count: int) -> str:
    return f"{collection_name}:{sample_size}:{total_count}"


def get_cached_projection(
    collection_name: str, sample_size: int, total_count: int
) -> ProjectionResult | None:
    key = _cache_key(collection_name, sample_size, total_count)
    if key in _cache:
        ts, result = _cache[key]
        if time.time() - ts < CACHE_TTL:
            return result
        del _cache[key]
    return None


def cache_result(
    collection_name: str, sample_size: int, total_count: int, result: ProjectionResult
) -> None:
    key = _cache_key(collection_name, sample_size, total_count)
    _cache[key] = (time.time(), result)


# ── Pipeline ─────────────────────────────────────────────────────────────────


def compute_projection(
    ids: list[str],
    embeddings: NDArray[np.float32],
    metadatas: list[dict],
    dimensions: int = 3,
) -> ProjectionResult:
    """Run PCA -> UMAP, cluster, and detect quality issues."""
    start = time.time()
    n_samples, n_features = embeddings.shape

    from sklearn.decomposition import PCA

    pca_dims = min(50, n_features, n_samples)
    pca = PCA(n_components=pca_dims)
    reduced = pca.fit_transform(embeddings)

    import umap as umap_lib

    n_neighbors = min(15, n_samples - 1)
    reducer = umap_lib.UMAP(
        n_components=dimensions,
        n_neighbors=n_neighbors,
        min_dist=0.1,
        metric="cosine",
        random_state=42,
    )
    projected = reducer.fit_transform(reduced)
    projected = _normalize_coordinates(projected)

    clusters = _compute_clusters(projected, ids, metadatas)
    quality = _detect_quality_issues(embeddings, projected, ids, clusters)

    if clusters:
        from sklearn.metrics import pairwise_distances_argmin

        centroids_arr = np.array([c.centroid for c in clusters])
        cluster_labels = pairwise_distances_argmin(projected, centroids_arr)
    else:
        cluster_labels = np.zeros(n_samples, dtype=int)

    points = [
        ProjectedPoint(
            id=ids[i],
            x=float(projected[i, 0]),
            y=float(projected[i, 1]),
            z=float(projected[i, 2]) if dimensions == 3 else 0.0,
            metadata=metadatas[i] if i < len(metadatas) else {},
            cluster_id=int(cluster_labels[i]),
        )
        for i in range(n_samples)
    ]

    elapsed = round((time.time() - start) * 1000)
    return ProjectionResult(
        points=points,
        clusters=clusters,
        quality=quality,
        stats={
            "total_vectors": n_samples,
            "sampled": n_samples,
            "projection_time_ms": elapsed,
        },
    )


def _normalize_coordinates(projected: NDArray[np.float32]) -> NDArray[np.float32]:
    result = projected.copy()
    for axis in range(projected.shape[1]):
        col = projected[:, axis]
        p1, p99 = np.percentile(col, [1, 99])
        clamped = np.clip(col, p1, p99)
        span = p99 - p1
        if span > 1e-8:
            result[:, axis] = 2.0 * (clamped - p1) / span - 1.0
        else:
            result[:, axis] = 0.0
    return result


def _compute_clusters(
    projected: NDArray, ids: list[str], metadatas: list[dict]
) -> list[Cluster]:
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    n = len(ids)
    if n < 4:
        return []

    max_k = min(20, n - 1)
    best_k = 2
    best_score = -1.0

    for k in range(2, min(max_k + 1, 11)):
        km = KMeans(n_clusters=k, random_state=42, n_init=5, max_iter=100)
        labels = km.fit_predict(projected)
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(projected, labels, sample_size=min(2000, n))
        if score > best_score:
            best_score = score
            best_k = k

    km = KMeans(n_clusters=best_k, random_state=42, n_init=10)
    labels = km.fit_predict(projected)

    clusters = []
    for cid in range(best_k):
        mask = labels == cid
        cluster_metas = [metadatas[i] for i in range(n) if mask[i]]
        label = _generate_cluster_label(cluster_metas)
        centroid = km.cluster_centers_[cid].tolist()
        clusters.append(
            Cluster(id=cid, label=label, centroid=centroid, size=int(mask.sum()))
        )

    return clusters


def _generate_cluster_label(metadatas: list[dict]) -> str:
    from collections import Counter

    counter: Counter[str] = Counter()
    for meta in metadatas:
        for v in meta.values():
            if isinstance(v, str) and len(v) < 50:
                counter[v] += 1
    if counter:
        label, _ = counter.most_common(1)[0]
        return label
    return "Unknown"


def _detect_quality_issues(
    embeddings: NDArray,
    projected: NDArray,
    ids: list[str],
    clusters: list[Cluster],
) -> QualityReport:
    from sklearn.ensemble import IsolationForest
    from sklearn.metrics.pairwise import cosine_similarity

    n = len(ids)

    outlier_ids: list[str] = []
    if n >= 10:
        iso = IsolationForest(contamination=0.05, random_state=42)
        preds = iso.fit_predict(projected)
        outlier_ids = [ids[i] for i in range(n) if preds[i] == -1]

    duplicate_pairs: list[tuple[str, str]] = []
    if n <= 5000:
        sim_matrix = cosine_similarity(embeddings)
        np.fill_diagonal(sim_matrix, 0)
        seen: set[tuple[str, str]] = set()
        dup_indices = np.argwhere(sim_matrix > 0.98)
        for i, j in dup_indices:
            if i < j:
                pair = (ids[i], ids[j])
                if pair not in seen:
                    seen.add(pair)
                    duplicate_pairs.append(pair)
                    if len(duplicate_pairs) >= 100:
                        break

    orphan_ids: list[str] = []
    if clusters:
        centroids = np.array([c.centroid for c in clusters])
        distances = np.min(
            np.linalg.norm(projected[:, None] - centroids[None, :], axis=2),
            axis=1,
        )
        threshold = np.mean(distances) + 2 * np.std(distances)
        orphan_ids = [ids[i] for i in range(n) if distances[i] > threshold]

    return QualityReport(
        outlier_ids=outlier_ids,
        duplicate_pairs=duplicate_pairs,
        orphan_ids=orphan_ids,
    )


def sample_deterministic(
    total_ids: list[str], sample_size: int, collection_name: str, total_count: int
) -> list[int]:
    if sample_size == 0 or sample_size >= len(total_ids):
        return list(range(len(total_ids)))
    seed_str = f"{collection_name}:{total_count}"
    seed = int(hashlib.sha256(seed_str.encode()).hexdigest()[:8], 16)
    rng = np.random.RandomState(seed)
    return sorted(rng.choice(len(total_ids), size=sample_size, replace=False).tolist())
