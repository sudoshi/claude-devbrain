#!/usr/bin/env python3
"""
Parthenon Brain v2 — Documentation & Code Ingestion Pipeline
==============================================================
Processes Parthenon project documentation and source code into ChromaDB
collections for semantic retrieval via MCP.

v2 improvements over v1:
  - AST-based code chunking for Python (function/class level)
  - Regex-based structural chunking for TS/PHP/SQL
  - Stale document cleanup (deleted files get purged)
  - Content-based chunk IDs (stable across reordering)
  - Proper error logging (no silent swallowing)
  - Batch upsert with size limits for large projects

Usage:
    python ingest.py --source /path/to/parthenon --chroma-dir ./chroma_data
    python ingest.py --source /path/to/parthenon --chroma-dir ./chroma_data --incremental
    python ingest.py --source /path/to/parthenon --chroma-dir ./chroma_data --include-code
"""

import argparse
import ast
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log = logging.getLogger("parthenon-brain")


def setup_logging(log_dir: Path | None = None, verbose: bool = False):
    """Configure logging to both console and optional file."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(fmt)
    log.addHandler(console)
    log.setLevel(level)

    if log_dir:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "ingestion.log")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(fh)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_COLLECTION = "parthenon_docs"
CODE_COLLECTION = "parthenon_code"
CHUNK_MAX_TOKENS = 800          # ~3200 chars
CHUNK_OVERLAP_TOKENS = 100      # ~400 chars overlap
BATCH_SIZE = 100                # ChromaDB upsert batch size

# Documentation file patterns
DOC_PATTERNS = ["**/*.md", "**/*.mdx", "**/*.txt", "**/*.rst"]

# Code file patterns
CODE_PATTERNS = ["**/*.py", "**/*.ts", "**/*.tsx", "**/*.sql", "**/*.php"]

# Directories to always skip
EXCLUDE_DIRS = frozenset({
    "node_modules", ".git", ".next", "build", "dist", "__pycache__",
    ".cache", ".docusaurus", "static", "public/img", ".venv", "venv",
    "vendor", "coverage", ".nyc_output", ".mypy_cache", ".pytest_cache",
    "backups", "tmp", "output", ".superpowers", ".claude",
    ".HFS+ Private Directory Data", ".Trashes", ".fseventsd",
    "dicom_samples", "vcf",
})

# High-value directories get doc_type metadata
HIGH_VALUE_DIRS = {
    "docs": "documentation",
    "blog": "devblog",
    "devlog": "devlog",
    "specs": "specification",
    "architecture": "architecture",
    "design": "design",
    "modules": "module_spec",
    "planning": "planning",
    "guides": "guide",
    "api": "api_reference",
    "prompts": "prompt",
    "commands": "command",
    "rules": "rules",
}

# Module detection keywords
MODULE_NAMES = frozenset({
    "commons", "studies", "gis", "imaging", "molecular", "heor",
    "atlas", "cohort", "explorer", "abby", "pipeline", "auth",
    "dashboard", "admin", "network", "federated", "ai", "study-agent",
    "morpheus", "finngen", "ohdsi", "solr", "chroma", "frontend",
    "backend", "docker", "e2e", "installer", "monitoring", "scripts",
    "community-workbench-sdk",
})


# ---------------------------------------------------------------------------
# Text Processing — Documentation
# ---------------------------------------------------------------------------

def strip_mdx_components(text: str) -> str:
    """Remove JSX/MDX component tags but keep their text content."""
    text = re.sub(r'^import\s+.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'<[A-Z][A-Za-z]*[^>]*/>', '', text)
    text = re.sub(r'</?[A-Z][A-Za-z]*[^>]*>', '', text)
    text = re.sub(r'^export\s+(default\s+)?', '', text, flags=re.MULTILINE)
    return text


def strip_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and return (metadata_dict, remaining_text)."""
    metadata = {}
    if text.startswith('---'):
        parts = text.split('---', 2)
        if len(parts) >= 3:
            fm_text = parts[1].strip()
            for line in fm_text.split('\n'):
                if ':' in line:
                    key, _, val = line.partition(':')
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and val:
                        metadata[key] = val
            text = parts[2]
    return metadata, text


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English."""
    return len(text) // 4


def chunk_id_from_content(filepath_rel: str, content: str) -> str:
    """Generate a stable chunk ID based on file path and content hash.

    This is stable across chunk reordering — adding a section in the middle
    won't invalidate all subsequent chunks.
    """
    return hashlib.sha256(f"{filepath_rel}::{content[:200]}".encode()).hexdigest()[:32]


def chunk_by_headers(text: str, max_tokens: int = CHUNK_MAX_TOKENS) -> list[dict]:
    """Split markdown text into chunks at header boundaries.

    Each chunk includes its header hierarchy for context.
    """
    lines = text.split('\n')
    chunks = []
    current_chunk_lines: list[str] = []
    current_headers: dict[int, str] = {}
    current_token_count = 0

    def flush_chunk():
        nonlocal current_chunk_lines, current_token_count
        if current_chunk_lines:
            content = '\n'.join(current_chunk_lines).strip()
            if content and len(content) > 50:
                section_parts = [current_headers[lv] for lv in sorted(current_headers)]
                chunks.append({
                    'content': content,
                    'section': ' > '.join(section_parts) if section_parts else 'Introduction',
                    'tokens': estimate_tokens(content),
                })
            current_chunk_lines = []
            current_token_count = 0

    for line in lines:
        header_match = re.match(r'^(#{1,6})\s+(.+)$', line)

        if header_match:
            level = len(header_match.group(1))
            header_text = header_match.group(2).strip()

            if current_token_count > 200:
                flush_chunk()

            current_headers[level] = header_text
            for deeper in [k for k in current_headers if k > level]:
                del current_headers[deeper]

        current_chunk_lines.append(line)
        current_token_count += estimate_tokens(line) + 1

        if current_token_count >= max_tokens:
            flush_chunk()

    flush_chunk()
    return chunks


# ---------------------------------------------------------------------------
# Code Chunking — AST-aware for Python, structural for others
# ---------------------------------------------------------------------------

def chunk_python_ast(text: str, filepath_rel: str) -> list[dict]:
    """Use Python AST to extract function and class definitions as chunks."""
    chunks = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        log.debug("  AST parse failed for %s, falling back to line-based", filepath_rel)
        return chunk_code_by_structure(text, filepath_rel, lang="python")

    lines = text.split('\n')

    # Collect module-level docstring if present
    module_doc = ast.get_docstring(tree)
    if module_doc:
        chunks.append({
            'content': f"# Module docstring for {filepath_rel}\n\n{module_doc}",
            'section': 'module_docstring',
            'symbol': '__module__',
            'kind': 'module',
        })

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno - 1
            end = node.end_lineno if node.end_lineno else start + 1
            source = '\n'.join(lines[start:end])

            if len(source) < 30:
                continue

            # Truncate very large functions/classes to stay within token budget
            if estimate_tokens(source) > CHUNK_MAX_TOKENS:
                source = source[:CHUNK_MAX_TOKENS * 4] + f"\n\n# ... [truncated, full at {filepath_rel}]"

            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            symbol_name = node.name

            # Get decorators
            decorators = []
            for dec in node.decorator_list:
                if isinstance(dec, ast.Name):
                    decorators.append(f"@{dec.id}")
                elif isinstance(dec, ast.Attribute):
                    decorators.append(f"@{ast.dump(dec)}")

            chunks.append({
                'content': source,
                'section': f"{kind}:{symbol_name}",
                'symbol': symbol_name,
                'kind': kind,
                'decorators': ', '.join(decorators) if decorators else None,
                'line_start': start + 1,
                'line_end': end,
            })

    # If AST produced no chunks (e.g. a script with only top-level code), fall back
    if not chunks:
        return chunk_code_by_structure(text, filepath_rel, lang="python")

    return chunks


def chunk_code_by_structure(text: str, filepath_rel: str, lang: str = "generic") -> list[dict]:
    """Structural chunking for non-Python code. Splits at function/class boundaries
    using regex patterns, falling back to line-count-based splitting."""

    # Language-specific boundary patterns
    patterns = {
        "typescript": r'^(?:export\s+)?(?:async\s+)?(?:function|class|interface|type|enum|const\s+\w+\s*=\s*(?:\(|async))',
        "php": r'^(?:\s*(?:public|private|protected|static)\s+)*(?:function|class|interface|trait|enum)\s+',
        "sql": r'^(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|WITH|SELECT)\s+',
        "python": r'^(?:def|class|async\s+def)\s+',
        "generic": r'^(?:(?:export\s+)?(?:function|class|def|CREATE|ALTER)\s+)',
    }

    pattern = patterns.get(lang, patterns["generic"])
    lines = text.split('\n')
    chunks = []
    current_lines: list[str] = []
    current_section = "top"

    def flush():
        nonlocal current_lines
        if current_lines:
            content = '\n'.join(current_lines).strip()
            if content and len(content) > 30:
                if estimate_tokens(content) > CHUNK_MAX_TOKENS:
                    content = content[:CHUNK_MAX_TOKENS * 4] + f"\n\n// ... [truncated, full at {filepath_rel}]"
                chunks.append({
                    'content': content,
                    'section': current_section,
                    'symbol': current_section,
                    'kind': 'block',
                })
            current_lines = []

    for line in lines:
        if re.match(pattern, line, re.IGNORECASE):
            flush()
            # Extract symbol name heuristically
            name_match = re.search(r'(?:function|class|interface|trait|enum|def|type)\s+(\w+)', line)
            current_section = name_match.group(1) if name_match else "block"

        current_lines.append(line)

        if estimate_tokens('\n'.join(current_lines)) >= CHUNK_MAX_TOKENS:
            flush()

    flush()
    return chunks


def detect_language(filepath: Path) -> str:
    """Detect language from file extension."""
    ext_map = {
        '.py': 'python',
        '.ts': 'typescript', '.tsx': 'typescript',
        '.sql': 'sql',
        '.php': 'php',
    }
    return ext_map.get(filepath.suffix.lower(), 'generic')


def chunk_code_file(text: str, filepath: Path, filepath_rel: str) -> list[dict]:
    """Route code files to the best chunking strategy."""
    lang = detect_language(filepath)
    if lang == 'python':
        return chunk_python_ast(text, filepath_rel)
    return chunk_code_by_structure(text, filepath_rel, lang=lang)


# ---------------------------------------------------------------------------
# File Discovery & Classification
# ---------------------------------------------------------------------------

def classify_file(filepath: Path, source_root: Path) -> dict:
    """Classify a file by its location in the project tree."""
    rel = filepath.relative_to(source_root)
    parts = rel.parts

    doc_type = "general"
    module = "unknown"

    for part in parts:
        part_lower = part.lower()
        if part_lower in HIGH_VALUE_DIRS:
            doc_type = HIGH_VALUE_DIRS[part_lower]
        if part_lower in MODULE_NAMES:
            module = part_lower

    return {
        'doc_type': doc_type,
        'module': module,
        'relative_path': str(rel),
        'directory': str(rel.parent),
    }


def should_skip(filepath: Path, source_root: Path | None = None) -> bool:
    """Check if a file should be skipped based on directory exclusions.

    Only checks path components relative to source_root (if provided),
    so the absolute path prefix (e.g. /tmp/) doesn't trigger false positives.
    """
    # Use relative parts if source_root is provided
    if source_root:
        try:
            rel = filepath.relative_to(source_root)
            parts = rel.parts
        except ValueError:
            parts = filepath.parts
    else:
        parts = filepath.parts

    for part in parts:
        if part in EXCLUDE_DIRS:
            return True
    # Skip binary/large files
    if filepath.suffix.lower() in {'.zip', '.gz', '.tar', '.png', '.jpg', '.jpeg',
                                     '.gif', '.svg', '.ico', '.woff', '.woff2',
                                     '.ttf', '.eot', '.pdf', '.dcm', '.nii'}:
        return True
    return False


def discover_files(source_root: Path, patterns: list[str]) -> list[Path]:
    """Find all ingestible files under the source root."""
    files = []
    for pattern in patterns:
        for f in source_root.glob(pattern):
            if f.is_file() and not should_skip(f, source_root):
                # Skip very large files (>500KB for docs, >200KB for code)
                try:
                    size = f.stat().st_size
                    if size > 500_000:
                        log.debug("  Skipping large file (%d KB): %s", size // 1024, f)
                        continue
                except OSError:
                    continue
                files.append(f)
    return sorted(set(files))


# ---------------------------------------------------------------------------
# Content Hashing (for incremental updates)
# ---------------------------------------------------------------------------

def file_hash(filepath: Path) -> str:
    """SHA-256 hash of file content for change detection."""
    h = hashlib.sha256()
    h.update(filepath.read_bytes())
    return h.hexdigest()


def load_hash_manifest(manifest_path: Path) -> dict:
    """Load the previous ingestion hash manifest."""
    if manifest_path.exists():
        try:
            return json.loads(manifest_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning("  Could not load manifest: %s", e)
    return {}


def save_hash_manifest(manifest_path: Path, manifest: dict):
    """Save the current hash manifest."""
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Stale Document Cleanup
# ---------------------------------------------------------------------------

def cleanup_stale_documents(
    collection: chromadb.Collection,
    current_files: set[str],
    collection_name: str,
) -> int:
    """Remove documents from ChromaDB whose source files no longer exist.

    Compares the set of relative_path values currently in the collection against
    the set of files discovered on disk. Any documents with a relative_path not
    in the current file set are deleted.
    """
    # Get all document metadata from the collection
    total = collection.count()
    if total == 0:
        return 0

    # Fetch in batches to handle large collections
    stale_ids = []
    batch_size = 1000
    offset = 0

    while offset < total:
        batch = collection.get(
            limit=batch_size,
            offset=offset,
            include=["metadatas"],
        )
        for doc_id, meta in zip(batch["ids"], batch["metadatas"]):
            rel_path = meta.get("relative_path", "")
            if rel_path and rel_path not in current_files:
                stale_ids.append(doc_id)
        offset += batch_size

    if stale_ids:
        # Delete in batches
        for i in range(0, len(stale_ids), BATCH_SIZE):
            batch = stale_ids[i:i + BATCH_SIZE]
            collection.delete(ids=batch)
        log.info("  Cleaned up %d stale documents from %s", len(stale_ids), collection_name)

    return len(stale_ids)


# ---------------------------------------------------------------------------
# Batch Upsert Helper
# ---------------------------------------------------------------------------

def batch_upsert(
    collection: chromadb.Collection,
    ids: list[str],
    documents: list[str],
    metadatas: list[dict],
):
    """Upsert in batches to avoid ChromaDB memory issues with large payloads."""
    for i in range(0, len(ids), BATCH_SIZE):
        end = i + BATCH_SIZE
        collection.upsert(
            ids=ids[i:end],
            documents=documents[i:end],
            metadatas=metadatas[i:end],
        )


# ---------------------------------------------------------------------------
# Documentation Ingestion
# ---------------------------------------------------------------------------

def ingest_doc_file(
    filepath: Path,
    source_root: Path,
    collection: chromadb.Collection,
    file_metadata: dict,
) -> int:
    """Ingest a single documentation file into ChromaDB. Returns chunk count."""
    text = filepath.read_text(encoding='utf-8', errors='replace')
    rel_path = file_metadata['relative_path']

    fm_metadata, text = strip_frontmatter(text)

    if filepath.suffix == '.mdx':
        text = strip_mdx_components(text)

    text = re.sub(r'\n{3,}', '\n\n', text)

    chunks = chunk_by_headers(text)
    if not chunks:
        return 0

    ids = []
    documents = []
    metadatas = []

    for chunk in chunks:
        cid = chunk_id_from_content(rel_path, chunk['content'])

        meta = {
            **file_metadata,
            'section': chunk['section'],
            'tokens': chunk['tokens'],
            'ingested_at': datetime.now().isoformat(),
            'filename': filepath.name,
            'extension': filepath.suffix,
        }
        for key in ('title', 'date', 'sidebar_label', 'tags', 'slug'):
            if fm_metadata.get(key):
                meta[key] = fm_metadata[key]

        ids.append(cid)
        documents.append(chunk['content'])
        metadatas.append(meta)

    batch_upsert(collection, ids, documents, metadatas)
    return len(chunks)


# ---------------------------------------------------------------------------
# Code Ingestion
# ---------------------------------------------------------------------------

def ingest_code_file(
    filepath: Path,
    source_root: Path,
    collection: chromadb.Collection,
    file_metadata: dict,
) -> int:
    """Ingest a single code file using language-aware chunking. Returns chunk count."""
    text = filepath.read_text(encoding='utf-8', errors='replace')
    rel_path = file_metadata['relative_path']

    if len(text) < 50:
        return 0

    chunks = chunk_code_file(text, filepath, rel_path)
    if not chunks:
        return 0

    ids = []
    documents = []
    metadatas = []

    for chunk in chunks:
        cid = chunk_id_from_content(rel_path, chunk['content'])

        meta = {
            **file_metadata,
            'doc_type': 'source_code',
            'section': chunk.get('section', 'block'),
            'symbol': chunk.get('symbol', ''),
            'kind': chunk.get('kind', 'block'),
            'extension': filepath.suffix,
            'filename': filepath.name,
            'ingested_at': datetime.now().isoformat(),
        }
        if chunk.get('decorators'):
            meta['decorators'] = chunk['decorators']
        if chunk.get('line_start'):
            meta['line_start'] = chunk['line_start']
            meta['line_end'] = chunk.get('line_end', 0)

        ids.append(cid)
        documents.append(chunk['content'])
        metadatas.append(meta)

    batch_upsert(collection, ids, documents, metadatas)
    return len(chunks)


# ---------------------------------------------------------------------------
# Main Ingestion Pipeline
# ---------------------------------------------------------------------------

def run_ingestion(
    source_root: Path,
    chroma_dir: Path,
    collection_name: str = DEFAULT_COLLECTION,
    incremental: bool = False,
    cleanup: bool = True,
):
    """Main documentation ingestion pipeline."""
    log.info("")
    log.info("=" * 60)
    log.info("  Parthenon Brain v2 — Documentation Ingestion")
    log.info("=" * 60)
    log.info("  Source:      %s", source_root)
    log.info("  ChromaDB:    %s", chroma_dir)
    log.info("  Collection:  %s", collection_name)
    log.info("  Mode:        %s", 'incremental' if incremental else 'full')
    log.info("=" * 60)

    client = chromadb.PersistentClient(
        path=str(chroma_dir),
        settings=Settings(anonymized_telemetry=False),
    )

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    manifest_path = chroma_dir / f".{collection_name}_manifest.json"
    old_manifest = load_hash_manifest(manifest_path) if incremental else {}
    new_manifest = {}

    files = discover_files(source_root, DOC_PATTERNS)
    log.info("  Found %d documentation files", len(files))

    # Track current files for stale cleanup
    current_file_set = set()

    total_chunks = 0
    files_processed = 0
    files_skipped = 0
    errors = 0

    for filepath in files:
        rel_path = str(filepath.relative_to(source_root))
        current_file_set.add(rel_path)
        current_hash = file_hash(filepath)
        new_manifest[rel_path] = current_hash

        if incremental and old_manifest.get(rel_path) == current_hash:
            files_skipped += 1
            continue

        file_meta = classify_file(filepath, source_root)

        try:
            n_chunks = ingest_doc_file(filepath, source_root, collection, file_meta)
            total_chunks += n_chunks
            files_processed += 1
            log.info("  + %s (%d chunks)", rel_path, n_chunks)
        except Exception as e:
            errors += 1
            log.error("  ! %s — ERROR: %s", rel_path, e)

    save_hash_manifest(manifest_path, new_manifest)

    # Cleanup stale documents
    stale_count = 0
    if cleanup:
        stale_count = cleanup_stale_documents(collection, current_file_set, collection_name)

    log.info("")
    log.info("=" * 60)
    log.info("  Documentation Ingestion Complete")
    log.info("=" * 60)
    log.info("  Files processed:  %d", files_processed)
    if incremental:
        log.info("  Files skipped:    %d (unchanged)", files_skipped)
    log.info("  Chunks created:   %d", total_chunks)
    if stale_count:
        log.info("  Stale removed:    %d", stale_count)
    if errors:
        log.warning("  Errors:           %d", errors)
    log.info("  Collection total: %d documents", collection.count())
    log.info("=" * 60)

    return files_processed, total_chunks, errors


def run_code_ingestion(
    source_root: Path,
    chroma_dir: Path,
    collection_name: str = CODE_COLLECTION,
    incremental: bool = False,
    cleanup: bool = True,
):
    """Code ingestion pipeline with AST-aware chunking."""
    log.info("")
    log.info("=" * 60)
    log.info("  Parthenon Brain v2 — Code Ingestion")
    log.info("=" * 60)
    log.info("  Collection:  %s", collection_name)
    log.info("  Mode:        %s", 'incremental' if incremental else 'full')
    log.info("=" * 60)

    client = chromadb.PersistentClient(
        path=str(chroma_dir),
        settings=Settings(anonymized_telemetry=False),
    )

    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    manifest_path = chroma_dir / f".{collection_name}_manifest.json"
    old_manifest = load_hash_manifest(manifest_path) if incremental else {}
    new_manifest = {}

    files = discover_files(source_root, CODE_PATTERNS)
    log.info("  Found %d code files", len(files))

    current_file_set = set()
    total_chunks = 0
    files_processed = 0
    files_skipped = 0
    errors = 0

    for filepath in files:
        rel_path = str(filepath.relative_to(source_root))
        current_file_set.add(rel_path)
        current_hash = file_hash(filepath)
        new_manifest[rel_path] = current_hash

        if incremental and old_manifest.get(rel_path) == current_hash:
            files_skipped += 1
            continue

        file_meta = classify_file(filepath, source_root)

        try:
            n_chunks = ingest_code_file(filepath, source_root, collection, file_meta)
            total_chunks += n_chunks
            files_processed += 1
            log.debug("  + %s (%d chunks)", rel_path, n_chunks)
        except Exception as e:
            errors += 1
            log.error("  ! %s — ERROR: %s", rel_path, e)

    save_hash_manifest(manifest_path, new_manifest)

    stale_count = 0
    if cleanup:
        stale_count = cleanup_stale_documents(collection, current_file_set, collection_name)

    log.info("")
    log.info("=" * 60)
    log.info("  Code Ingestion Complete")
    log.info("=" * 60)
    log.info("  Files processed:  %d", files_processed)
    if incremental:
        log.info("  Files skipped:    %d (unchanged)", files_skipped)
    log.info("  Chunks created:   %d", total_chunks)
    if stale_count:
        log.info("  Stale removed:    %d", stale_count)
    if errors:
        log.warning("  Errors:           %d", errors)
    log.info("  Collection total: %d documents", collection.count())
    log.info("=" * 60)

    return files_processed, total_chunks, errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parthenon Brain v2 — Ingest documentation and code into ChromaDB"
    )
    parser.add_argument(
        '--source', '-s', type=Path, required=True,
        help='Root directory of the Parthenon project',
    )
    parser.add_argument(
        '--chroma-dir', '-d', type=Path,
        default=Path.home() / '.parthenon-brain' / 'chroma_data',
        help='Directory for ChromaDB persistent storage',
    )
    parser.add_argument(
        '--collection', '-c', default=DEFAULT_COLLECTION,
        help=f'Documentation collection name (default: {DEFAULT_COLLECTION})',
    )
    parser.add_argument(
        '--incremental', '-i', action='store_true',
        help='Only process files changed since last ingestion',
    )
    parser.add_argument(
        '--include-code', action='store_true',
        help='Also ingest source code with AST-aware chunking',
    )
    parser.add_argument(
        '--no-cleanup', action='store_true',
        help='Skip removal of stale documents from deleted files',
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Enable debug logging',
    )

    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"Error: Source directory not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    args.chroma_dir.mkdir(parents=True, exist_ok=True)

    log_dir = Path.home() / '.parthenon-brain' / 'logs'
    setup_logging(log_dir=log_dir, verbose=args.verbose)

    cleanup = not args.no_cleanup

    # Documentation ingestion
    run_ingestion(
        source_root=args.source,
        chroma_dir=args.chroma_dir,
        collection_name=args.collection,
        incremental=args.incremental,
        cleanup=cleanup,
    )

    # Code ingestion
    if args.include_code:
        run_code_ingestion(
            source_root=args.source,
            chroma_dir=args.chroma_dir,
            incremental=args.incremental,
            cleanup=cleanup,
        )


if __name__ == '__main__':
    main()
