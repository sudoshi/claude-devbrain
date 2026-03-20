#!/usr/bin/env bash
# =============================================================================
# Parthenon Brain — Setup Script
# =============================================================================
# Installs ChromaDB, the chroma-mcp server, and configures Claude Code.
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh /path/to/parthenon-project
# =============================================================================

set -euo pipefail

BRAIN_DIR="$HOME/.parthenon-brain"
CHROMA_DATA="$BRAIN_DIR/chroma_data"
SCRIPTS_DIR="$(cd "$(dirname "$0")" && pwd)/scripts"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         Parthenon Brain — Setup                         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ---------------------------------------------------------------------------
# 1. Check prerequisites
# ---------------------------------------------------------------------------

echo -e "${YELLOW}[1/6] Checking prerequisites...${NC}"

if ! command -v python3 &>/dev/null; then
    echo -e "${RED}  ✗ Python 3 not found. Please install Python 3.10+${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "${GREEN}  ✓ Python $PYTHON_VERSION${NC}"

if ! command -v pip3 &>/dev/null && ! command -v pip &>/dev/null; then
    echo -e "${RED}  ✗ pip not found${NC}"
    exit 1
fi
echo -e "${GREEN}  ✓ pip available${NC}"

# Check for uv/uvx (preferred) or fall back to pip
USE_UVX=false
if command -v uvx &>/dev/null; then
    USE_UVX=true
    echo -e "${GREEN}  ✓ uvx available (will use for MCP server)${NC}"
else
    echo -e "${YELLOW}  ⚠ uvx not found — will install chroma-mcp via pip${NC}"
    echo -e "${YELLOW}    (Install uv for a cleaner setup: curl -LsSf https://astral.sh/uv/install.sh | sh)${NC}"
fi

# Check for Claude Code
if command -v claude &>/dev/null; then
    echo -e "${GREEN}  ✓ Claude Code CLI available${NC}"
else
    echo -e "${YELLOW}  ⚠ Claude Code CLI not found — MCP config will need manual setup${NC}"
fi

# ---------------------------------------------------------------------------
# 2. Install Python dependencies
# ---------------------------------------------------------------------------

echo ""
echo -e "${YELLOW}[2/6] Installing Python dependencies...${NC}"

pip3 install --quiet --upgrade chromadb sentence-transformers 2>/dev/null || pip install --quiet --upgrade chromadb sentence-transformers
echo -e "${GREEN}  ✓ chromadb + sentence-transformers installed${NC}"

# Install chroma-mcp if not using uvx
if [ "$USE_UVX" = false ]; then
    pip3 install --quiet --upgrade chroma-mcp 2>/dev/null || pip install --quiet --upgrade chroma-mcp
    echo -e "${GREEN}  ✓ chroma-mcp installed via pip${NC}"
fi

# ---------------------------------------------------------------------------
# 3. Create brain directory structure
# ---------------------------------------------------------------------------

echo ""
echo -e "${YELLOW}[3/6] Creating directory structure...${NC}"

mkdir -p "$CHROMA_DATA"
mkdir -p "$BRAIN_DIR/logs"
mkdir -p "$BRAIN_DIR/backups"

echo -e "${GREEN}  ✓ $BRAIN_DIR created${NC}"
echo -e "${GREEN}  ✓ $CHROMA_DATA ready${NC}"

# ---------------------------------------------------------------------------
# 4. Copy scripts
# ---------------------------------------------------------------------------

echo ""
echo -e "${YELLOW}[4/6] Installing scripts...${NC}"

if [ -d "$SCRIPTS_DIR" ]; then
    cp "$SCRIPTS_DIR/ingest.py" "$BRAIN_DIR/ingest.py"
    cp "$SCRIPTS_DIR/query.py" "$BRAIN_DIR/query.py"
    chmod +x "$BRAIN_DIR/ingest.py"
    chmod +x "$BRAIN_DIR/query.py"
    echo -e "${GREEN}  ✓ Scripts installed to $BRAIN_DIR${NC}"
else
    echo -e "${RED}  ✗ Scripts directory not found at $SCRIPTS_DIR${NC}"
    echo -e "${YELLOW}    Copy ingest.py and query.py to $BRAIN_DIR manually${NC}"
fi

# ---------------------------------------------------------------------------
# 5. Configure Claude Code MCP
# ---------------------------------------------------------------------------

echo ""
echo -e "${YELLOW}[5/6] Configuring Claude Code MCP server...${NC}"

if command -v claude &>/dev/null; then
    if [ "$USE_UVX" = true ]; then
        # Register chroma-mcp via uvx (cleanest approach)
        claude mcp add parthenon-brain \
            --scope user \
            -- uvx chroma-mcp \
            --client-type persistent \
            --data-dir "$CHROMA_DATA" \
            2>/dev/null && echo -e "${GREEN}  ✓ MCP server registered with Claude Code (uvx)${NC}" \
            || echo -e "${YELLOW}  ⚠ Auto-registration failed — see manual config below${NC}"
    else
        # Register via direct python
        claude mcp add parthenon-brain \
            --scope user \
            -- python3 -m chroma_mcp \
            --client-type persistent \
            --data-dir "$CHROMA_DATA" \
            2>/dev/null && echo -e "${GREEN}  ✓ MCP server registered with Claude Code (pip)${NC}" \
            || echo -e "${YELLOW}  ⚠ Auto-registration failed — see manual config below${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠ Skipping auto-registration (Claude Code CLI not found)${NC}"
fi

# Show manual config as fallback
echo ""
echo -e "${BLUE}  Manual MCP configuration (add to .mcp.json or ~/.claude.json):${NC}"
echo ""
if [ "$USE_UVX" = true ]; then
    cat <<EOF
  {
    "mcpServers": {
      "parthenon-brain": {
        "command": "uvx",
        "args": [
          "chroma-mcp",
          "--client-type", "persistent",
          "--data-dir", "$CHROMA_DATA"
        ]
      }
    }
  }
EOF
else
    cat <<EOF
  {
    "mcpServers": {
      "parthenon-brain": {
        "command": "python3",
        "args": [
          "-m", "chroma_mcp",
          "--client-type", "persistent",
          "--data-dir", "$CHROMA_DATA"
        ]
      }
    }
  }
EOF
fi

# ---------------------------------------------------------------------------
# 6. Initial ingestion (if source provided)
# ---------------------------------------------------------------------------

echo ""
echo -e "${YELLOW}[6/6] Initial ingestion...${NC}"

if [ "${1:-}" != "" ] && [ -d "${1:-}" ]; then
    SOURCE_DIR="$1"
    echo -e "  Ingesting from: $SOURCE_DIR"
    python3 "$BRAIN_DIR/ingest.py" \
        --source "$SOURCE_DIR" \
        --chroma-dir "$CHROMA_DATA" \
        --include-code
else
    echo -e "${YELLOW}  ⚠ No source directory provided. Run manually:${NC}"
    echo ""
    echo "    python3 $BRAIN_DIR/ingest.py --source /path/to/parthenon --chroma-dir $CHROMA_DATA"
    echo ""
    echo "  For incremental updates (faster, only changed files):"
    echo ""
    echo "    python3 $BRAIN_DIR/ingest.py --source /path/to/parthenon --chroma-dir $CHROMA_DATA --incremental"
    echo ""
    echo "  To include source code:"
    echo ""
    echo "    python3 $BRAIN_DIR/ingest.py --source /path/to/parthenon --chroma-dir $CHROMA_DATA --include-code"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Setup Complete!                                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Brain directory:  $BRAIN_DIR"
echo "  ChromaDB data:    $CHROMA_DATA"
echo ""
echo "  Next steps:"
echo "    1. Run ingestion if you haven't already"
echo "    2. Add the CLAUDE.md snippet to your project"
echo "    3. Start Claude Code — it will auto-query the brain"
echo ""
echo "  Test with:"
echo "    python3 $BRAIN_DIR/query.py \"How does Commons handle real-time messaging?\""
echo ""
