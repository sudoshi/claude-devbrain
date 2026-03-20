#!/usr/bin/env python3
"""
Parthenon Brain v2 — Query Tool
==================================
Semantic search and collection management for ingested documentation and code.

Usage:
    python query.py "How does Commons handle real-time collaboration?"
    python query.py "FastAPI router patterns" --collection parthenon_code --n 10
    python query.py "federated architecture" --type specification --module studies
    python query.py --stats
    python query.py --collections
"""

import argparse
import json
import sys
from pathlib import Path

import chromadb
from chromadb.config import Settings


DEFAULT_CHROMA_DIR = Path.home() / '.parthenon-brain' / 'chroma_data'


def get_client(chroma_dir: Path) -> chromadb.PersistentClient:
    """Create a ChromaDB persistent client."""
    return chromadb.PersistentClient(
        path=str(chroma_dir),
        settings=Settings(anonymized_telemetry=False),
    )


def list_collections(chroma_dir: Path):
    """List all collections with document counts."""
    client = get_client(chroma_dir)
    collections = client.list_collections()

    if not collections:
        print("\n  No collections found. Run ingestion first.\n")
        return

    print(f"\n  {'Collection':<30} {'Documents':>10}")
    print(f"  {'─' * 30} {'─' * 10}")
    for col in collections:
        # ChromaDB >= 1.0 returns Collection objects; older versions return strings
        name = col.name if hasattr(col, 'name') else str(col)
        col_obj = col if hasattr(col, 'count') else client.get_collection(name=name)
        print(f"  {name:<30} {col_obj.count():>10}")
    print()


def show_stats(chroma_dir: Path, collection_name: str | None = None):
    """Show detailed statistics for a collection or all collections."""
    client = get_client(chroma_dir)
    collections = client.list_collections()

    if not collections:
        print("\n  No collections found.\n")
        return

    if collection_name:
        target_names = [collection_name]
    else:
        target_names = [
            c.name if hasattr(c, 'name') else str(c) for c in collections
        ]

    for name in target_names:
        try:
            col = client.get_collection(name=name)
        except Exception:
            print(f"\n  Collection '{name}' not found.")
            continue

        total = col.count()
        print(f"\n  Collection: {name}")
        print(f"  Documents:  {total}")

        if total == 0:
            continue

        # Sample metadata to show distribution
        sample_size = min(total, 2000)
        sample = col.get(limit=sample_size, include=["metadatas"])

        # Aggregate stats
        doc_types: dict[str, int] = {}
        modules: dict[str, int] = {}
        extensions: dict[str, int] = {}

        for meta in sample["metadatas"]:
            dt = meta.get("doc_type", "unknown")
            doc_types[dt] = doc_types.get(dt, 0) + 1
            mod = meta.get("module", "unknown")
            modules[mod] = modules.get(mod, 0) + 1
            ext = meta.get("extension", "?")
            extensions[ext] = extensions.get(ext, 0) + 1

        print(f"\n  By doc_type:")
        for k, v in sorted(doc_types.items(), key=lambda x: -x[1]):
            print(f"    {k:<25} {v:>5}")

        print(f"\n  By module:")
        for k, v in sorted(modules.items(), key=lambda x: -x[1]):
            if v > 1 or k != "unknown":
                print(f"    {k:<25} {v:>5}")

        print(f"\n  By extension:")
        for k, v in sorted(extensions.items(), key=lambda x: -x[1]):
            print(f"    {k:<25} {v:>5}")

    print()


def query_brain(
    query: str,
    chroma_dir: Path,
    collection_name: str = "parthenon_docs",
    n_results: int = 5,
    doc_type: str | None = None,
    module: str | None = None,
):
    """Query the Parthenon brain and return relevant chunks."""
    client = get_client(chroma_dir)

    try:
        collection = client.get_collection(name=collection_name)
    except Exception:
        print(f"Error: Collection '{collection_name}' not found.")
        collections = client.list_collections()
        names = [c.name if hasattr(c, 'name') else str(c) for c in client.list_collections()]
        print(f"Available: {names}")
        sys.exit(1)

    where = None
    where_clauses = []
    if doc_type:
        where_clauses.append({"doc_type": doc_type})
    if module:
        where_clauses.append({"module": module})

    if len(where_clauses) == 1:
        where = where_clauses[0]
    elif len(where_clauses) > 1:
        where = {"$and": where_clauses}

    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, collection.count()),
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    return results


def format_results(results: dict, verbose: bool = False) -> str:
    """Format query results for display."""
    if not results['documents'] or not results['documents'][0]:
        return "  No results found.\n"

    output = []
    for i, (doc, meta, dist) in enumerate(zip(
        results['documents'][0],
        results['metadatas'][0],
        results['distances'][0],
    )):
        similarity = 1 - dist
        output.append(f"\n{'─' * 60}")
        output.append(f"  Result {i + 1}  (similarity: {similarity:.3f})")
        output.append(f"  File:    {meta.get('relative_path', 'unknown')}")
        output.append(f"  Section: {meta.get('section', 'N/A')}")
        output.append(f"  Type:    {meta.get('doc_type', 'N/A')}")

        if meta.get('module', 'unknown') != 'unknown':
            output.append(f"  Module:  {meta['module']}")
        if meta.get('title'):
            output.append(f"  Title:   {meta['title']}")
        if meta.get('symbol'):
            output.append(f"  Symbol:  {meta['symbol']} ({meta.get('kind', '')})")
        if meta.get('line_start'):
            output.append(f"  Lines:   {meta['line_start']}-{meta.get('line_end', '?')}")

        output.append(f"{'─' * 60}")

        if verbose:
            output.append(doc)
        else:
            preview = doc[:500]
            if len(doc) > 500:
                preview += "..."
            output.append(preview)

    return '\n'.join(output)


def main():
    parser = argparse.ArgumentParser(description="Parthenon Brain v2 — Query Tool")
    parser.add_argument('query', nargs='?', help='Semantic search query')
    parser.add_argument(
        '--chroma-dir', '-d', type=Path, default=DEFAULT_CHROMA_DIR,
        help=f'ChromaDB directory (default: {DEFAULT_CHROMA_DIR})',
    )
    parser.add_argument(
        '--collection', '-c', default='parthenon_docs',
        help='Collection to search (default: parthenon_docs)',
    )
    parser.add_argument('--n', type=int, default=5, help='Number of results')
    parser.add_argument('--type', dest='doc_type', help='Filter by doc_type')
    parser.add_argument('--module', help='Filter by module name')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show full content')
    parser.add_argument('--json', dest='as_json', action='store_true', help='Output as JSON')
    parser.add_argument('--stats', action='store_true', help='Show collection statistics')
    parser.add_argument('--collections', action='store_true', help='List all collections')

    args = parser.parse_args()

    # Stats mode
    if args.stats:
        show_stats(args.chroma_dir, args.collection if args.collection != 'parthenon_docs' else None)
        return

    # List collections mode
    if args.collections:
        list_collections(args.chroma_dir)
        return

    # Query mode
    if not args.query:
        parser.print_help()
        sys.exit(1)

    print(f"\n  Querying: \"{args.query}\"")
    print(f"  Collection: {args.collection}")
    if args.doc_type:
        print(f"  Filter type: {args.doc_type}")
    if args.module:
        print(f"  Filter module: {args.module}")

    results = query_brain(
        query=args.query,
        chroma_dir=args.chroma_dir,
        collection_name=args.collection,
        n_results=args.n,
        doc_type=args.doc_type,
        module=args.module,
    )

    if args.as_json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print(format_results(results, verbose=args.verbose))


if __name__ == '__main__':
    main()
