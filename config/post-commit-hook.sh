#!/usr/bin/env bash
# =============================================================================
# Parthenon Brain — Git Post-Commit Hook
# =============================================================================
# Automatically re-ingests changed documentation after each commit.
# 
# Installation:
#   cp post-commit-hook.sh /path/to/parthenon/.git/hooks/post-commit
#   chmod +x /path/to/parthenon/.git/hooks/post-commit
#
# Or use a symlink:
#   ln -s ~/.parthenon-brain/post-commit-hook.sh /path/to/parthenon/.git/hooks/post-commit
# =============================================================================

BRAIN_DIR="$HOME/.parthenon-brain"
CHROMA_DATA="$BRAIN_DIR/chroma_data"
INGEST_SCRIPT="$BRAIN_DIR/ingest.py"
LOG_FILE="$BRAIN_DIR/logs/ingestion.log"

# Only run if docs were changed
CHANGED_DOCS=$(git diff --name-only HEAD~1 HEAD 2>/dev/null | grep -E '\.(md|mdx|txt|rst)$' || true)

if [ -n "$CHANGED_DOCS" ]; then
    echo "[parthenon-brain] Documentation changed — running incremental ingestion..."
    
    REPO_ROOT=$(git rev-parse --show-toplevel)
    
    python3 "$INGEST_SCRIPT" \
        --source "$REPO_ROOT" \
        --chroma-dir "$CHROMA_DATA" \
        --incremental \
        >> "$LOG_FILE" 2>&1 &
    
    # Run in background so it doesn't block the commit
    echo "[parthenon-brain] Ingestion started in background (log: $LOG_FILE)"
fi
