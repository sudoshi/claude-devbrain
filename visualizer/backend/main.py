"""DevBrain Visualizer — FastAPI backend for ChromaDB collection inspection.

Connects directly to the DevBrain ChromaDB instance and exposes endpoints for
collection listing, overview, semantic query, and 3D projection.
"""
import logging
import os
import time
from collections import Counter
from pathlib import Path
from typing import Literal

import chromadb
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from projection import (
    ProjectionResult,
    cache_result,
    compute_projection,
    get_cached_projection,
    sample_deterministic,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def _discover_chroma_dirs() -> list[str]:
    """Auto-discover ChromaDB data directories under the user's home."""
    home = Path.home()
    dirs: list[str] = []

    # Explicit env var (comma-separated)
    env_val = os.environ.get("CHROMA_DIRS") or os.environ.get("CHROMA_DIR")
    if env_val:
        for d in env_val.split(","):
            d = d.strip()
            if d and Path(d).is_dir():
                dirs.append(d)

    # Auto-discover: scan ~/.* for chroma_data/ subdirectories
    if not dirs:
        for candidate in sorted(home.glob(".*/chroma_data")):
            if candidate.is_dir() and (candidate / "chroma.sqlite3").exists():
                dirs.append(str(candidate))
        # Fallback default
        default = home / ".claude-devbrain" / "chroma_data"
        if not dirs and default.is_dir():
            dirs.append(str(default))

    return dirs


CHROMA_DIRS = _discover_chroma_dirs()

app = FastAPI(title="DevBrain Visualizer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_clients: dict[str, chromadb.ClientAPI] = {}


def _get_all_clients() -> dict[str, chromadb.ClientAPI]:
    """Return ChromaDB clients for all discovered data directories."""
    for d in CHROMA_DIRS:
        if d not in _clients:
            logger.info("Connecting to ChromaDB at %s", d)
            _clients[d] = chromadb.PersistentClient(
                path=d,
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
    return _clients


def _find_collection(name: str) -> chromadb.Collection:
    """Find a collection by name across all ChromaDB instances."""
    for client in _get_all_clients().values():
        try:
            return client.get_collection(name=name)
        except Exception:
            continue
    raise HTTPException(status_code=404, detail=f"Collection '{name}' not found.")


# ── Projects ─────────────────────────────────────────────────────────────────


@app.get("/api/projects")
async def list_projects() -> list[dict]:
    """Auto-detect projects from collection naming convention ({project}_docs, {project}_code)."""
    all_collections = []
    for client in _get_all_clients().values():
        all_collections.extend(client.list_collections())

    project_map: dict[str, dict] = {}
    standalone: list[dict] = []

    for col in all_collections:
        name = col.name
        try:
            count = col.count()
        except Exception:
            count = 0

        matched = False
        for suffix in ("_docs", "_code"):
            if name.endswith(suffix):
                project_name = name[: -len(suffix)]
                if project_name not in project_map:
                    project_map[project_name] = {
                        "name": project_name,
                        "collections": [],
                        "total_vectors": 0,
                    }
                project_map[project_name]["collections"].append(
                    {"name": name, "type": suffix[1:], "count": count}
                )
                project_map[project_name]["total_vectors"] += count
                matched = True
                break

        if not matched:
            standalone.append({"name": name, "type": "standalone", "count": count})

    projects = list(project_map.values())
    if standalone:
        projects.append(
            {
                "name": "Other",
                "collections": standalone,
                "total_vectors": sum(c["count"] for c in standalone),
            }
        )

    return sorted(projects, key=lambda p: p["total_vectors"], reverse=True)


# ── Collections ──────────────────────────────────────────────────────────────


@app.get("/api/collections")
async def list_collections() -> list[dict]:
    result = []
    for client in _get_all_clients().values():
        for col in client.list_collections():
            try:
                count = col.count()
                error = None
            except Exception as e:
                count = -1
                error = str(e)[:200]
            result.append(
                {"name": col.name, "count": count, "metadata": col.metadata or {}, "error": error}
            )
    return result


SAMPLE_LIMIT = 250


@app.get("/api/collections/{name}/overview")
async def collection_overview(name: str, include_embeddings: bool = False) -> dict:
    col = _find_collection(name)

    count = col.count()
    if count == 0:
        return {
            "name": name,
            "count": 0,
            "dimension": None,
            "metadataKeys": [],
            "facets": [],
            "sampleRecords": [],
            "collectionMetadata": col.metadata or {},
        }

    IncludeType = Literal["documents", "embeddings", "metadatas", "distances", "uris", "data"]
    include: list[IncludeType] = ["documents", "metadatas"]
    if include_embeddings:
        include.append("embeddings")

    sample = col.get(limit=min(count, SAMPLE_LIMIT), include=include)

    ids = sample.get("ids", [])
    documents: list[str | None] = sample.get("documents") or [None] * len(ids)
    metadatas: list[dict | None] = sample.get("metadatas") or [None] * len(ids)
    embeddings = sample.get("embeddings") if include_embeddings else None

    # Detect dimension
    dimension = None
    if embeddings is not None and len(embeddings) > 0:
        first_emb = embeddings[0]
        if first_emb is not None:
            emb_list = first_emb.tolist() if hasattr(first_emb, "tolist") else first_emb
            if isinstance(emb_list, list):
                dimension = len(emb_list)
    elif not include_embeddings and count > 0:
        probe = col.get(limit=1, include=["embeddings"])
        probe_embs = probe.get("embeddings")
        if probe_embs is not None and len(probe_embs) > 0 and probe_embs[0] is not None:
            p = probe_embs[0]
            emb_list = p.tolist() if hasattr(p, "tolist") else p
            if isinstance(emb_list, list):
                dimension = len(emb_list)

    records = []
    for i, doc_id in enumerate(ids):
        record: dict = {
            "id": doc_id,
            "document": documents[i] if documents is not None and i < len(documents) else None,
            "metadata": metadatas[i] if metadatas is not None and i < len(metadatas) else None,
        }
        if include_embeddings and embeddings is not None and i < len(embeddings):
            raw = embeddings[i]
            record["embedding"] = raw.tolist() if hasattr(raw, "tolist") else raw
        records.append(record)

    all_keys: set[str] = set()
    key_counters: dict[str, Counter] = {}
    for meta in metadatas:
        if not meta:
            continue
        for k, v in meta.items():
            all_keys.add(k)
            if k not in key_counters:
                key_counters[k] = Counter()
            key_counters[k][str(v) if not isinstance(v, str) else v] += 1

    facets = []
    for key in sorted(all_keys):
        counter = key_counters.get(key, Counter())
        top_values = counter.most_common(10)
        facets.append(
            {"key": key, "values": [{"label": lbl, "count": cnt} for lbl, cnt in top_values]}
        )

    return {
        "name": name,
        "count": count,
        "dimension": dimension,
        "metadataKeys": sorted(all_keys),
        "facets": facets,
        "sampleRecords": records,
        "collectionMetadata": col.metadata or {},
    }


# ── Query ────────────────────────────────────────────────────────────────────


class QueryInput(BaseModel):
    collectionName: str
    queryText: str
    nResults: int = 8
    where: dict | None = None
    whereDocument: dict | None = None


@app.post("/api/query")
async def query_collection(body: QueryInput) -> dict:
    col = _find_collection(body.collectionName)

    start = time.time()
    kwargs: dict = {
        "query_texts": [body.queryText],
        "n_results": min(body.nResults, col.count() or 1),
        "include": ["documents", "metadatas", "distances"],
    }
    if body.where:
        kwargs["where"] = body.where
    if body.whereDocument:
        kwargs["where_document"] = body.whereDocument

    results = col.query(**kwargs)
    elapsed_ms = round((time.time() - start) * 1000)

    items = []
    result_ids = results.get("ids", [[]])[0]
    result_docs = (results.get("documents") or [[]])[0]
    result_metas = (results.get("metadatas") or [[]])[0]
    result_dists = (results.get("distances") or [[]])[0]

    for i, doc_id in enumerate(result_ids):
        items.append(
            {
                "id": doc_id,
                "document": result_docs[i] if i < len(result_docs) else None,
                "metadata": result_metas[i] if i < len(result_metas) else None,
                "distance": result_dists[i] if i < len(result_dists) else None,
            }
        )

    return {"items": items, "elapsedMs": elapsed_ms}


# ── Projection ───────────────────────────────────────────────────────────────


class ProjectionInput(BaseModel):
    sample_size: int = 5000
    method: str = "pca-umap"
    dimensions: int = 3


@app.post("/api/collections/{name}/project")
async def project_collection(name: str, body: ProjectionInput) -> dict:
    if body.method != "pca-umap":
        raise HTTPException(status_code=400, detail="Only 'pca-umap' method is supported.")
    if body.dimensions not in (2, 3):
        raise HTTPException(status_code=400, detail="Dimensions must be 2 or 3.")
    if body.sample_size != 0 and (body.sample_size < 10 or body.sample_size > 100000):
        raise HTTPException(
            status_code=400, detail="sample_size must be 0 (all) or 10-100000."
        )

    col = _find_collection(name)

    total_count = col.count()
    if total_count == 0:
        raise HTTPException(status_code=400, detail="Collection is empty.")

    cached = get_cached_projection(name, body.sample_size, total_count)
    if cached is not None:
        return _result_to_dict(cached)

    BATCH_SIZE = 500
    effective_sample = body.sample_size if body.sample_size > 0 else total_count

    if total_count > effective_sample * 2:
        ID_BATCH = 10000
        all_ids: list = []
        offset = 0
        while offset < total_count:
            batch = col.get(
                limit=min(ID_BATCH, total_count - offset), offset=offset, include=[]
            )
            batch_ids = batch.get("ids", [])
            if not batch_ids:
                break
            all_ids.extend(batch_ids)
            offset += len(batch_ids)

        if not all_ids:
            raise HTTPException(status_code=400, detail="Collection has no entries.")

        indices = sample_deterministic(all_ids, body.sample_size, name, total_count)
        sampled_ids = [all_ids[i] for i in indices]

        ids: list = []
        raw_embeddings: list = []
        metadatas_list: list = []
        for i in range(0, len(sampled_ids), BATCH_SIZE):
            batch_ids_slice = sampled_ids[i : i + BATCH_SIZE]
            batch = col.get(ids=batch_ids_slice, include=["embeddings", "metadatas"])
            ids.extend(batch.get("ids", []))
            batch_embs = batch.get("embeddings")
            if batch_embs is not None:
                raw_embeddings.extend(batch_embs)
            batch_metas = batch.get("metadatas")
            if batch_metas is not None:
                metadatas_list.extend(batch_metas)
            else:
                metadatas_list.extend([{}] * len(batch_ids_slice))
    else:
        all_ids_full: list = []
        all_embeddings: list = []
        all_metadatas: list = []
        offset = 0
        while offset < total_count:
            batch = col.get(
                limit=min(BATCH_SIZE, total_count - offset),
                offset=offset,
                include=["embeddings", "metadatas"],
            )
            batch_ids = batch.get("ids", [])
            if not batch_ids:
                break
            all_ids_full.extend(batch_ids)
            batch_embs = batch.get("embeddings")
            if batch_embs is not None:
                all_embeddings.extend(batch_embs)
            batch_metas = batch.get("metadatas")
            if batch_metas is not None:
                all_metadatas.extend(batch_metas)
            else:
                all_metadatas.extend([{}] * len(batch_ids))
            offset += len(batch_ids)

        if not all_embeddings:
            raise HTTPException(status_code=400, detail="Collection has no embeddings.")

        indices = sample_deterministic(all_ids_full, body.sample_size, name, total_count)
        ids = [all_ids_full[i] for i in indices]
        raw_embeddings = [all_embeddings[i] for i in indices]
        metadatas_list = [all_metadatas[i] or {} for i in indices]

    if not raw_embeddings:
        raise HTTPException(status_code=400, detail="Collection has no embeddings.")

    embeddings_array = np.array(
        [e.tolist() if hasattr(e, "tolist") else e for e in raw_embeddings],
        dtype=np.float32,
    )

    if len(ids) < 3:
        raise HTTPException(status_code=400, detail="Need at least 3 vectors for projection.")

    result = compute_projection(ids, embeddings_array, metadatas_list, body.dimensions)
    result.stats["total_vectors"] = total_count
    result.stats["sampled"] = len(ids)

    cache_result(name, body.sample_size, total_count, result)
    return _result_to_dict(result)


def _result_to_dict(result: ProjectionResult) -> dict:
    return {
        "points": [
            {
                "id": p.id,
                "x": p.x,
                "y": p.y,
                "z": p.z,
                "metadata": p.metadata,
                "cluster_id": p.cluster_id,
            }
            for p in result.points
        ],
        "clusters": [
            {"id": c.id, "label": c.label, "centroid": c.centroid, "size": c.size}
            for c in result.clusters
        ],
        "quality": {
            "outlier_ids": result.quality.outlier_ids,
            "duplicate_pairs": [list(p) for p in result.quality.duplicate_pairs],
            "orphan_ids": result.quality.orphan_ids,
        },
        "stats": result.stats,
    }


@app.get("/api/health")
async def health() -> dict:
    try:
        clients = _get_all_clients()
        total_collections = sum(
            len(c.list_collections()) for c in clients.values()
        )
        return {
            "status": "healthy",
            "chroma_dirs": CHROMA_DIRS,
            "collections": total_collections,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
