#!/usr/bin/env bash
#
# DevBrain Visualizer — Launch Script
# Starts both the FastAPI backend and Vite frontend dev server.
#
# Usage:
#   ./visualizer/start.sh              # Start both servers
#   ./visualizer/start.sh --backend    # Backend only (port 8100)
#   ./visualizer/start.sh --frontend   # Frontend only (port 5190)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

BACKEND_PORT="${BACKEND_PORT:-8100}"
FRONTEND_PORT="${FRONTEND_PORT:-5190}"
# CHROMA_DIR/CHROMA_DIRS env vars override auto-discovery if set
# Auto-discovery scans ~/.*  for chroma_data/ directories

RED='\033[0;31m'
GREEN='\033[0;32m'
GOLD='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

cleanup() {
    echo -e "\n${GOLD}Shutting down...${NC}"
    kill $(jobs -p) 2>/dev/null || true
    wait 2>/dev/null || true
    echo -e "${GREEN}Done.${NC}"
}
trap cleanup EXIT INT TERM

start_backend() {
    echo -e "${CYAN}Starting backend on port ${BACKEND_PORT}...${NC}"

    if [ ! -d "$BACKEND_DIR/.venv" ]; then
        echo -e "${GOLD}Creating Python virtual environment...${NC}"
        python3 -m venv "$BACKEND_DIR/.venv"
        "$BACKEND_DIR/.venv/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt"
    fi

    "$BACKEND_DIR/.venv/bin/uvicorn" \
        main:app \
        --host 0.0.0.0 \
        --port "$BACKEND_PORT" \
        --reload \
        --app-dir "$BACKEND_DIR" &

    echo -e "${GREEN}Backend:  http://localhost:${BACKEND_PORT}${NC}"
    echo -e "${GREEN}API docs: http://localhost:${BACKEND_PORT}/docs${NC}"
}

start_frontend() {
    echo -e "${CYAN}Starting frontend on port ${FRONTEND_PORT}...${NC}"

    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        echo -e "${GOLD}Installing npm dependencies...${NC}"
        cd "$FRONTEND_DIR" && npm install --legacy-peer-deps
    fi

    cd "$FRONTEND_DIR" && npx vite --port "$FRONTEND_PORT" &

    echo -e "${GREEN}Frontend: http://localhost:${FRONTEND_PORT}${NC}"
}

echo -e "${GOLD}"
echo "  ____             ____            _       "
echo " |  _ \  _____   _| __ ) _ __ __ _(_)_ __  "
echo " | | | |/ _ \ \ / /  _ \| '__/ _\` | | '_ \ "
echo " | |_| |  __/\ V /| |_) | | | (_| | | | | |"
echo " |____/ \___| \_/ |____/|_|  \__,_|_|_| |_|"
echo "                                            "
echo -e "  Visualizer${NC}"
echo ""

case "${1:-}" in
    --backend)
        start_backend
        ;;
    --frontend)
        start_frontend
        ;;
    *)
        start_backend
        echo ""
        start_frontend
        ;;
esac

echo ""
echo -e "${GOLD}Press Ctrl+C to stop all servers.${NC}"
wait
