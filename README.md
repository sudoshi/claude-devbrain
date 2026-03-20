# Claude DevBrain

**Persistent memory for Claude Code — index your projects into ChromaDB for semantic retrieval via MCP.**

Every Claude Code session starts with a blank slate. DevBrain fixes this by indexing your documentation and source code into ChromaDB, then exposing it via MCP so Claude can search your project's full context before writing a single line of code.

---

## Quick Start

```bash
git clone https://github.com/sudoshi/claude-devbrain.git
cd claude-devbrain
pip install chromadb sentence-transformers
python installer.py
```

The installer walks you through everything: prerequisites, adding projects, MCP registration, and initial ingestion.

---

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│  Claude Code Session                                     │
│                                                          │
│   CLAUDE.md says:                                        │
│   "Query devbrain before starting any task"              │
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
   │  ~/.claude-devbrain/        │
   │    chroma_data/             │
   │                             │
   │  Collections per project:   │
   │   • myproject_docs          │
   │   • myproject_code          │
   └──────────────▲──────────────┘
                  │
                  │ Ingestion Pipeline
                  │
   ┌──────────────┴──────────────┐     ┌──────────────────┐
   │  ingest.py                  │     │  installer.py     │
   │  • Header-aware doc chunks  │◄────│  • Rich TUI       │
   │  • AST-based Python chunks  │     │  • Multi-project  │
   │  • Structural TS/PHP/SQL    │     │  • MCP setup      │
   │  • Incremental (hash-based) │     │  • Git hooks      │
   │  • Stale document cleanup   │     └──────────────────┘
   └─────────────────────────────┘
```

## Features

### Intelligent Ingestion

- **Documentation**: Header-aware chunking that preserves section hierarchy (e.g., `Architecture > Database > Schema`)
- **Python**: AST-based chunking — extracts individual functions and classes with their docstrings
- **TypeScript/PHP/SQL**: Structural regex chunking at function/class boundaries
- **Incremental updates**: SHA-256 hash manifest skips unchanged files
- **Stale cleanup**: Automatically removes chunks from deleted files
- **Content-based IDs**: Chunk IDs are stable across reordering (no orphaned documents)

### Interactive Installer

- Rich TUI with prerequisites checking
- Multi-project support — index as many codebases as you want
- Per-project collection names (no collisions)
- MCP server auto-registration with Claude Code
- Git post-commit hooks for automatic re-ingestion
- CLAUDE.md snippet generation
- Re-runnable: add/remove projects anytime

### MCP Integration

The official `chroma-mcp` server exposes ChromaDB collections as MCP tools. Claude Code can:

- **Search semantically**: "Find documentation about federated study execution"
- **Filter by metadata**: `doc_type`, `module`, `extension`, `symbol`, `kind`
- **Search code**: Find functions, classes, and API patterns by description
- **List collections**: See all indexed projects

---

## Usage

### Installer (Recommended)

```bash
# First run — full setup wizard
python installer.py

# Re-run — manage projects, add new ones, re-ingest
python installer.py
```

### Direct CLI

```bash
# Ingest documentation
python scripts/ingest.py --source /path/to/project --chroma-dir ~/.claude-devbrain/chroma_data

# Ingest documentation + code
python scripts/ingest.py --source /path/to/project --chroma-dir ~/.claude-devbrain/chroma_data --include-code

# Incremental (fast — only changed files)
python scripts/ingest.py --source /path/to/project --chroma-dir ~/.claude-devbrain/chroma_data --incremental

# Custom collection name
python scripts/ingest.py --source /path/to/project --collection myproject_docs --code-collection myproject_code --include-code

# Query
python scripts/query.py "How does auth work?"
python scripts/query.py "FastAPI endpoint" --collection myproject_code --n 10
python scripts/query.py --stats
python scripts/query.py --collections
```

### MCP Registration

```bash
# Auto (via Claude Code CLI)
claude mcp add claude-devbrain --scope user \
    -- uvx chroma-mcp \
    --client-type persistent \
    --data-dir ~/.claude-devbrain/chroma_data

# Manual (add to ~/.claude.json)
{
  "mcpServers": {
    "claude-devbrain": {
      "command": "uvx",
      "args": ["chroma-mcp", "--client-type", "persistent",
               "--data-dir", "/home/YOU/.claude-devbrain/chroma_data"]
    }
  }
}
```

---

## Auto-Ingestion

### Git Post-Commit Hook

The installer can set up a post-commit hook that runs incremental ingestion in the background whenever documentation files change. This keeps your brain fresh with zero effort.

### Manual Re-Ingestion

```bash
# Re-run installer
python installer.py
# Choose option 4 (ingest one project) or 5 (ingest all)
```

---

## Collections & Metadata

Each project gets two collections:

| Collection | Contents | Best For |
|---|---|---|
| `{project}_docs` | Markdown, MDX, specs, devlogs | Architecture, design decisions, module specs |
| `{project}_code` | Python, TypeScript, PHP, SQL | Implementation patterns, API contracts, schemas |

### Metadata Fields

| Field | Values | Filterable |
|---|---|---|
| `doc_type` | documentation, devblog, specification, architecture, source_code, ... | Yes |
| `module` | Auto-detected from directory structure | Yes |
| `section` | Header hierarchy or function name | Yes |
| `symbol` | Function/class name (code only) | Yes |
| `kind` | function, class, module, block (code only) | Yes |
| `extension` | .md, .py, .ts, .php, .sql, ... | Yes |

---

## File Structure

```
claude-devbrain/
├── installer.py           # Interactive TUI installer & project manager
├── scripts/
│   ├── ingest.py          # Ingestion pipeline (docs + AST-aware code)
│   ├── query.py           # CLI query tool + stats
│   └── test_ingest.py     # 39 unit tests
├── config/
│   ├── CLAUDE-BRAIN-SNIPPET.md   # CLAUDE.md template
│   ├── post-commit-hook.sh       # Git hook template
│   └── mcp.json.template         # MCP config template
├── requirements.txt
├── setup.sh               # Legacy bash setup (use installer.py instead)
└── README.md

~/.claude-devbrain/        # Created by installer
├── config.json            # Project configuration
├── chroma_data/           # ChromaDB persistent storage
├── ingest.py              # Deployed ingestion script
├── query.py               # Deployed query tool
├── logs/
│   └── ingestion.log
└── backups/
```

---

## Prerequisites

- Python 3.10+
- `chromadb` (pip install chromadb)
- `sentence-transformers` (for embeddings)
- `uvx` recommended (for MCP server)
- Claude Code CLI (for MCP auto-registration)

---

## Troubleshooting

**"Collection not found"**: Run ingestion first, or check collection names with `python scripts/query.py --collections`.

**MCP server not appearing**: Run `claude mcp list` and verify registration. Restart Claude Code after adding MCP config.

**Slow first ingestion**: Normal for large projects. Subsequent runs with `--incremental` are fast (seconds, not minutes).

**Embedding errors**: Install sentence-transformers: `pip install sentence-transformers`.

---

## License

MIT
