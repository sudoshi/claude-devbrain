# Parthenon Brain

**A ChromaDB-powered persistent memory system for Claude Code**

Solves the core problem: Claude Code doesn't remember prior sessions, even when extensive documentation exists. Parthenon Brain indexes all your project documentation into ChromaDB and exposes it via MCP, so every Claude Code session starts with full project context.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Claude Code Session                                     │
│                                                          │
│   CLAUDE.md says:                                        │
│   "Query parthenon-brain before starting any task"       │
│                     │                                    │
│                     ▼                                    │
│   ┌─────────────────────────┐                           │
│   │  chroma-mcp (MCP Server)│ ◄── Official Chroma MCP   │
│   │  stdio transport        │     (uvx chroma-mcp)      │
│   └────────────┬────────────┘                           │
│                │                                         │
└────────────────┼─────────────────────────────────────────┘
                 │
                 ▼
   ┌─────────────────────────────┐
   │  ChromaDB (Persistent)      │
   │  ~/.parthenon-brain/        │
   │    chroma_data/             │
   │                             │
   │  Collections:               │
   │   • parthenon_docs          │
   │     (MD, MDX, specs, blogs) │
   │   • parthenon_code          │
   │     (Python, TS, SQL)       │
   └──────────────▲──────────────┘
                  │
                  │ Ingestion Pipeline
                  │
   ┌──────────────┴──────────────┐
   │  ingest.py                  │
   │  • Header-aware chunking    │
   │  • MDX/frontmatter parsing  │
   │  • Metadata classification  │
   │  • Incremental (hash-based) │
   │  • Git hook auto-trigger    │
   └─────────────────────────────┘
```

## Quick Start

### 1. Install

```bash
# Clone or copy parthenon-brain into your project tooling
cd parthenon-brain
chmod +x setup.sh

# Run setup (optionally pass your project root for immediate ingestion)
./setup.sh /path/to/parthenon
```

### 2. Ingest Your Documentation

```bash
# Full ingestion (first time)
python3 ~/.parthenon-brain/ingest.py \
    --source /path/to/parthenon \
    --chroma-dir ~/.parthenon-brain/chroma_data \
    --include-code

# Incremental (subsequent runs — only processes changed files)
python3 ~/.parthenon-brain/ingest.py \
    --source /path/to/parthenon \
    --chroma-dir ~/.parthenon-brain/chroma_data \
    --incremental
```

### 3. Verify It Works

```bash
# Test a query
python3 ~/.parthenon-brain/query.py "Commons real-time collaboration architecture"

# Check collection stats
python3 -c "
import chromadb
client = chromadb.PersistentClient(path='$HOME/.parthenon-brain/chroma_data')
for c in client.list_collections():
    print(f'{c.name}: {c.count()} documents')
"
```

### 4. Add CLAUDE.md Snippet

Copy the content from `config/CLAUDE-BRAIN-SNIPPET.md` into your project's
`CLAUDE.md` or `.claude/CLAUDE.md`. This tells Claude Code to query the brain
at the start of every session.

### 5. Configure Claude Code MCP

The setup script attempts auto-configuration. If manual setup is needed:

```bash
# Option A: Claude Code CLI (recommended)
claude mcp add parthenon-brain --scope user \
    -- uvx chroma-mcp \
    --client-type persistent \
    --data-dir ~/.parthenon-brain/chroma_data

# Option B: Edit ~/.claude.json directly
```

Add to your `~/.claude.json` or project `.mcp.json`:

```json
{
  "mcpServers": {
    "parthenon-brain": {
      "command": "uvx",
      "args": [
        "chroma-mcp",
        "--client-type", "persistent",
        "--data-dir", "/home/YOUR_USER/.parthenon-brain/chroma_data"
      ]
    }
  }
}
```

### 6. (Optional) Auto-Ingest on Git Commits

```bash
cp config/post-commit-hook.sh /path/to/parthenon/.git/hooks/post-commit
chmod +x /path/to/parthenon/.git/hooks/post-commit
```

This runs incremental ingestion in the background after every commit that
touches documentation files.

---

## How It Works

### Ingestion Pipeline (`ingest.py`)

The ingestion script processes your project documentation intelligently:

1. **Discovery**: Scans for `.md`, `.mdx`, `.txt`, `.rst` files, skipping
   `node_modules`, `.git`, `build`, etc.

2. **Frontmatter Extraction**: Parses YAML frontmatter for metadata like
   title, date, tags, and slug.

3. **MDX Handling**: Strips JSX components and import statements while
   preserving content text.

4. **Header-Aware Chunking**: Splits at markdown headers, maintaining
   section hierarchy context (e.g., "Architecture > Database > Schema").
   Chunks target ~800 tokens with overlap for continuity.

5. **Metadata Classification**: Each chunk gets tagged with:
   - `doc_type`: documentation, devblog, devlog, specification, etc.
   - `module`: commons, studies, gis, imaging, abby, etc.
   - `relative_path`, `section`, `filename`, `extension`
   - Frontmatter fields (title, date, tags)

6. **Incremental Updates**: SHA-256 hash manifest tracks which files have
   changed since the last ingestion. Unchanged files are skipped entirely.

7. **Upsert**: ChromaDB's upsert operation ensures idempotent ingestion.
   Re-running is always safe.

### MCP Integration

The official `chroma-mcp` server (from Chroma themselves) exposes ChromaDB
collections as MCP tools. Claude Code can then:

- **Search semantically**: "Find documentation about federated study execution"
- **Filter by metadata**: Only search specs, only search the GIS module, etc.
- **List collections**: See what knowledge bases are available
- **Get collection info**: Check document counts and metadata

### CLAUDE.md Instructions

The CLAUDE.md snippet creates a behavioral contract: Claude Code will query
the brain before starting work, similar to how a developer would check the
wiki before making changes. This eliminates the "blank slate" problem that
wastes the first 10 minutes of every session re-discovering project context.

---

## Collections

| Collection | Contents | Best For |
|---|---|---|
| `parthenon_docs` | Markdown, MDX, specs, devlogs, blogs | Architecture questions, design decisions, module specs |
| `parthenon_code` | Python, TypeScript, SQL source files | Implementation patterns, API contracts, schema details |

---

## Advanced Usage

### Custom Collections

You can create separate collections for different knowledge domains:

```bash
# Ingest only OHDSI/OMOP documentation
python3 ~/.parthenon-brain/ingest.py \
    --source /path/to/ohdsi-docs \
    --collection ohdsi_reference

# Ingest Abby training corpus
python3 ~/.parthenon-brain/ingest.py \
    --source /path/to/abby-corpus \
    --collection abby_training_corpus
```

### Filtered Queries

```bash
# Only search specifications
python3 ~/.parthenon-brain/query.py "federated architecture" --type specification

# Only search the Commons module
python3 ~/.parthenon-brain/query.py "WebSocket presence" --module commons

# Search code specifically
python3 ~/.parthenon-brain/query.py "FastAPI router" --collection parthenon_code
```

### Backup & Restore

```bash
# Backup
cp -r ~/.parthenon-brain/chroma_data ~/.parthenon-brain/backups/$(date +%Y%m%d)

# Restore
cp -r ~/.parthenon-brain/backups/20260319 ~/.parthenon-brain/chroma_data
```

### Re-Index from Scratch

```bash
# Delete and re-create
rm -rf ~/.parthenon-brain/chroma_data
python3 ~/.parthenon-brain/ingest.py \
    --source /path/to/parthenon \
    --chroma-dir ~/.parthenon-brain/chroma_data \
    --include-code
```

---

## File Structure

```
~/.parthenon-brain/
├── chroma_data/           # ChromaDB persistent storage
│   └── .parthenon_docs_manifest.json  # Hash manifest for incremental
├── ingest.py              # Ingestion pipeline
├── query.py               # CLI query tool
├── logs/
│   └── ingestion.log      # Auto-ingestion logs
└── backups/               # Manual backups
```

---

## Prerequisites

- Python 3.10+
- `chromadb` (pip install chromadb)
- `uvx` recommended (for MCP server: `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)

---

## Troubleshooting

**"Collection not found"**: Run the ingestion pipeline first.

**MCP server not appearing**: Check `claude mcp list` and verify the server
is registered. Restart Claude Code after adding MCP configuration.

**Slow ingestion**: Use `--incremental` flag for subsequent runs. First
ingestion of a large project may take a few minutes.

**Embedding errors**: The default ChromaDB embedding function uses
`all-MiniLM-L6-v2` from sentence-transformers. If you get import errors,
install it: `pip install sentence-transformers`.

**Token limit warnings**: The `chroma-mcp` server may warn about large
outputs. Set `MAX_MCP_OUTPUT_TOKENS=50000` in your environment if needed.
