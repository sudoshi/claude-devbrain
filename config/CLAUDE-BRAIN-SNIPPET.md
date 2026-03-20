# =============================================================================
# CLAUDE.md — Parthenon Brain Integration
# =============================================================================
# Add this section to your project's CLAUDE.md (or .claude/CLAUDE.md).
# This instructs Claude Code to query the ChromaDB brain before starting work.
# =============================================================================

## Project Memory (Parthenon Brain)

This project has a persistent knowledge base stored in ChromaDB, accessible via
the `parthenon-brain` MCP server. It contains all project documentation, devlogs,
development blogs, architecture specs, module designs, and key code files that
have been created over the course of development.

### CRITICAL: Always Query Before Working

**Before starting any task**, query the Parthenon Brain to recall relevant context:

1. **At the start of every session**, use the Chroma MCP tools to search for
   context related to the current task. Search the `parthenon_docs` collection
   for documentation and specs, and `parthenon_code` for implementation details.

2. **Before making architectural decisions**, search for prior design decisions
   and specs. Many modules have detailed phase specifications, data models, and
   API contracts already documented.

3. **Before writing new code**, check if similar patterns already exist. The
   codebase has established conventions for FastAPI endpoints, React components,
   database migrations, and testing.

### How to Query

Use the Chroma MCP tools (available as `parthenon-brain` in your MCP server list):

- `chroma_query` — Semantic search across collections
  - Collection `parthenon_docs`: Documentation, specs, devlogs, blogs
  - Collection `parthenon_code`: Source code files and patterns

- Filter by metadata when narrowing scope:
  - `doc_type`: documentation, devblog, devlog, specification, architecture, 
    design, module_spec, planning, guide, api_reference, source_code
  - `module`: commons, studies, gis, imaging, molecular, heor, abby, atlas, 
    cohort, explorer, pipeline, auth, dashboard, federated, network

### Key Architecture Context

The Parthenon platform is an open-source replacement for OHDSI/OMOP tools. 
Key architectural patterns to be aware of:

- **Frontend**: React 19 + TypeScript + Inertia.js, served by Laravel
- **Backend**: Laravel (PHP) for web layer, FastAPI (Python) for AI/ML services
- **Database**: PostgreSQL with OMOP CDM schema, PostGIS for spatial
- **AI Assistant**: "Abby" — FastAPI + Ollama/MedGemma, ChromaDB vector memory
- **Federated**: Per-site data sovereignty, federated study execution
- **Modules**: Commons (collaboration), Studies, GIS Explorer, Atlas, Cohort, 
  Imaging, Molecular Diagnostics, HEOR

### Devlog & Blog Convention

Development progress is captured in two formats:
- **Devlogs**: Technical implementation notes (what was built, how, decisions made)
- **Development Blogs**: Higher-level narrative for the Docusaurus site

When creating new devlogs or blogs, also ingest them into the brain:
```bash
python3 ~/.parthenon-brain/ingest.py \
    --source /path/to/parthenon \
    --chroma-dir ~/.parthenon-brain/chroma_data \
    --incremental
```

### Example Queries to Try

- "How does the Commons module handle real-time messaging?"
- "What is the federated architecture for the Studies module?"
- "What are Abby's RAG pipeline collections?"
- "GIS Explorer PostGIS spatial statistics implementation"
- "OMOP CDM schema extensions for oncology"
- "Phase 6 specification for Commons workspace"
- "React component conventions for Parthenon modules"
