#!/usr/bin/env python3
"""
Claude DevBrain — Interactive Installer & Project Manager
============================================================
A rich TUI for setting up and managing the Claude DevBrain persistent
memory system. Handles prerequisites, project configuration, MCP server
registration, and ingestion orchestration.

First run:  Sets up everything from scratch.
Re-run:     Shows existing projects, lets you add/remove/modify/re-ingest.

Usage:
    python installer.py
    python installer.py --brain-dir ~/.claude-devbrain
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.table import Table
from rich.text import Text
from rich import box

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VERSION = "2.0.0"
DEFAULT_BRAIN_DIR = Path.home() / ".claude-devbrain"
CONFIG_FILENAME = "config.json"
SCRIPTS = ["ingest.py", "query.py"]

console = Console()


# ---------------------------------------------------------------------------
# Config Management
# ---------------------------------------------------------------------------

def default_config(brain_dir: Path) -> dict:
    """Return a fresh default config."""
    return {
        "version": VERSION,
        "brain_dir": str(brain_dir),
        "chroma_dir": str(brain_dir / "chroma_data"),
        "projects": [],
        "mcp_registered": False,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }


def load_config(brain_dir: Path) -> dict | None:
    """Load existing config or return None."""
    config_path = brain_dir / CONFIG_FILENAME
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_config(config: dict):
    """Save config to disk."""
    config["updated_at"] = datetime.now().isoformat()
    config_path = Path(config["brain_dir"]) / CONFIG_FILENAME
    config_path.write_text(json.dumps(config, indent=2, sort_keys=False))


def project_entry(
    name: str,
    path: str,
    ingest_docs: bool = True,
    ingest_code: bool = True,
    doc_collection: str | None = None,
    code_collection: str | None = None,
    post_commit_hook: bool = False,
) -> dict:
    """Create a project config entry."""
    slug = name.lower().replace(" ", "_").replace("-", "_")
    return {
        "name": name,
        "path": str(path),
        "ingest_docs": ingest_docs,
        "ingest_code": ingest_code,
        "doc_collection": doc_collection or f"{slug}_docs",
        "code_collection": code_collection or f"{slug}_code",
        "post_commit_hook": post_commit_hook,
        "added_at": datetime.now().isoformat(),
        "last_ingested": None,
    }


# ---------------------------------------------------------------------------
# Prerequisites Check
# ---------------------------------------------------------------------------

def check_command(cmd: str) -> str | None:
    """Check if a command is available, return its path or None."""
    return shutil.which(cmd)


def check_prerequisites() -> dict:
    """Check all prerequisites and return status dict."""
    results = {}

    # Python version
    v = sys.version_info
    results["python"] = {
        "available": v.major == 3 and v.minor >= 10,
        "version": f"{v.major}.{v.minor}.{v.micro}",
        "path": sys.executable,
    }

    # pip
    results["pip"] = {
        "available": check_command("pip3") is not None or check_command("pip") is not None,
    }

    # chromadb
    try:
        import chromadb
        results["chromadb"] = {"available": True, "version": getattr(chromadb, "__version__", "unknown")}
    except ImportError:
        results["chromadb"] = {"available": False}

    # sentence-transformers
    try:
        import sentence_transformers
        results["sentence_transformers"] = {"available": True}
    except ImportError:
        results["sentence_transformers"] = {"available": False}

    # uvx
    results["uvx"] = {"available": check_command("uvx") is not None}

    # Claude Code CLI
    results["claude_cli"] = {"available": check_command("claude") is not None}

    # git
    results["git"] = {"available": check_command("git") is not None}

    return results


def display_prerequisites(prereqs: dict) -> bool:
    """Display prerequisite status. Returns True if all critical checks pass."""
    table = Table(title="Prerequisites", box=box.ROUNDED, show_lines=True)
    table.add_column("Component", style="bold")
    table.add_column("Status")
    table.add_column("Notes", style="dim")

    critical_ok = True

    def row(name: str, key: str, critical: bool = False, note: str = ""):
        nonlocal critical_ok
        info = prereqs[key]
        if info["available"]:
            status = "[green]OK[/green]"
            version = info.get("version", "")
            note = version if version else note
        else:
            if critical:
                status = "[red]MISSING[/red]"
                critical_ok = False
            else:
                status = "[yellow]NOT FOUND[/yellow]"
        table.add_row(name, status, note)

    row("Python 3.10+", "python", critical=True)
    row("pip", "pip", critical=True)
    row("chromadb", "chromadb", critical=True)
    row("sentence-transformers", "sentence_transformers", note="For embeddings (will install if missing)")
    row("uvx", "uvx", note="For MCP server (recommended)")
    row("Claude Code CLI", "claude_cli", note="For MCP auto-registration")
    row("git", "git", note="For post-commit hooks")

    console.print()
    console.print(table)
    console.print()

    return critical_ok


def install_missing_deps(prereqs: dict):
    """Install missing Python dependencies."""
    missing = []
    if not prereqs["chromadb"]["available"]:
        missing.append("chromadb")
    if not prereqs["sentence_transformers"]["available"]:
        missing.append("sentence-transformers")

    if missing:
        console.print(f"\n[yellow]Installing missing packages: {', '.join(missing)}[/yellow]")
        pip_cmd = "pip3" if check_command("pip3") else "pip"
        try:
            subprocess.run(
                [pip_cmd, "install", "--quiet", "--upgrade"] + missing,
                check=True,
                capture_output=True,
            )
            console.print("[green]  Packages installed successfully.[/green]")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]  Failed to install packages: {e}[/red]")
            console.print("[dim]  Try manually: pip install " + " ".join(missing) + "[/dim]")


# ---------------------------------------------------------------------------
# Directory & Script Setup
# ---------------------------------------------------------------------------

def setup_brain_directory(brain_dir: Path):
    """Create the brain directory structure and copy scripts."""
    chroma_dir = brain_dir / "chroma_data"
    logs_dir = brain_dir / "logs"
    backups_dir = brain_dir / "backups"

    for d in [brain_dir, chroma_dir, logs_dir, backups_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Copy scripts from the repo
    scripts_dir = Path(__file__).parent / "scripts"
    for script in SCRIPTS:
        src = scripts_dir / script
        dst = brain_dir / script
        if src.exists():
            shutil.copy2(src, dst)
            dst.chmod(0o755)
            console.print(f"  [green]Installed[/green] {script}")
        else:
            console.print(f"  [yellow]Warning:[/yellow] {script} not found at {src}")


# ---------------------------------------------------------------------------
# Project Management
# ---------------------------------------------------------------------------

def browse_for_path() -> str | None:
    """Prompt user to enter a project path with tab-completion hint."""
    console.print("\n[dim]  Enter the full path to your project root.[/dim]")
    console.print("[dim]  Example: /home/user/projects/my-app[/dim]\n")

    while True:
        path_str = Prompt.ask("  Project path").strip()
        if not path_str:
            return None

        path = Path(path_str).expanduser().resolve()
        if path.is_dir():
            return str(path)
        else:
            console.print(f"  [red]Directory not found:[/red] {path}")
            if not Confirm.ask("  Try again?", default=True):
                return None


def add_project_interactive(config: dict) -> dict | None:
    """Interactive wizard to add a new project."""
    console.print(Panel("Add a New Project", style="bold cyan"))

    path = browse_for_path()
    if not path:
        return None

    # Auto-detect project name from directory
    default_name = Path(path).name
    name = Prompt.ask("  Project name", default=default_name)

    # Check for duplicate
    existing = {p["path"] for p in config["projects"]}
    if path in existing:
        console.print(f"  [yellow]This project is already configured.[/yellow]")
        return None

    # Ingestion options
    console.print("\n  [bold]What should DevBrain index?[/bold]")
    ingest_docs = Confirm.ask("  Index documentation (md, mdx, txt, rst)?", default=True)
    ingest_code = Confirm.ask("  Index source code (py, ts, tsx, php, sql)?", default=True)

    if not ingest_docs and not ingest_code:
        console.print("  [yellow]At least one must be selected.[/yellow]")
        return None

    # Collection names
    slug = name.lower().replace(" ", "_").replace("-", "_")
    console.print(f"\n  [dim]Default collection names: {slug}_docs, {slug}_code[/dim]")
    custom = Confirm.ask("  Customize collection names?", default=False)

    doc_col = f"{slug}_docs"
    code_col = f"{slug}_code"
    if custom:
        if ingest_docs:
            doc_col = Prompt.ask("  Docs collection name", default=doc_col)
        if ingest_code:
            code_col = Prompt.ask("  Code collection name", default=code_col)

    # Post-commit hook
    git_dir = Path(path) / ".git"
    install_hook = False
    if git_dir.is_dir():
        install_hook = Confirm.ask(
            "  Install git post-commit hook for auto-ingestion?", default=True
        )

    entry = project_entry(
        name=name,
        path=path,
        ingest_docs=ingest_docs,
        ingest_code=ingest_code,
        doc_collection=doc_col,
        code_collection=code_col,
        post_commit_hook=install_hook,
    )

    return entry


def display_projects(config: dict):
    """Display the current project list as a table."""
    projects = config["projects"]
    if not projects:
        console.print("\n  [dim]No projects configured yet.[/dim]\n")
        return

    table = Table(title="Configured Projects", box=box.ROUNDED, show_lines=True)
    table.add_column("#", style="bold", width=3)
    table.add_column("Name", style="bold cyan")
    table.add_column("Path")
    table.add_column("Docs", justify="center")
    table.add_column("Code", justify="center")
    table.add_column("Hook", justify="center")
    table.add_column("Last Ingested", style="dim")

    for i, p in enumerate(projects, 1):
        docs = "[green]yes[/green]" if p["ingest_docs"] else "[dim]no[/dim]"
        code = "[green]yes[/green]" if p["ingest_code"] else "[dim]no[/dim]"
        hook = "[green]yes[/green]" if p.get("post_commit_hook") else "[dim]no[/dim]"
        ingested = p.get("last_ingested", "never") or "never"
        if ingested != "never":
            # Show just date
            ingested = ingested[:16].replace("T", " ")
        table.add_row(str(i), p["name"], p["path"], docs, code, hook, ingested)

    console.print()
    console.print(table)
    console.print()


def remove_project_interactive(config: dict):
    """Remove a project from the config."""
    if not config["projects"]:
        console.print("  [dim]No projects to remove.[/dim]")
        return

    display_projects(config)
    idx = IntPrompt.ask(
        "  Enter project number to remove (0 to cancel)",
        default=0,
    )
    if idx == 0 or idx > len(config["projects"]):
        return

    project = config["projects"][idx - 1]
    if Confirm.ask(f"  Remove [bold]{project['name']}[/bold]?", default=False):
        config["projects"].pop(idx - 1)
        save_config(config)
        console.print(f"  [green]Removed {project['name']}.[/green]")
        console.print(
            f"  [dim]Note: ChromaDB collections ({project['doc_collection']}, "
            f"{project['code_collection']}) still exist. "
            f"Delete ~/.claude-devbrain/chroma_data to fully reset.[/dim]"
        )


# ---------------------------------------------------------------------------
# Post-Commit Hook Installation
# ---------------------------------------------------------------------------

def generate_hook_script(brain_dir: Path) -> str:
    """Generate a post-commit hook script."""
    return f"""#!/usr/bin/env bash
# =============================================================================
# Claude DevBrain — Git Post-Commit Hook
# Auto-ingests changed documentation after each commit.
# Installed by: python installer.py
# =============================================================================

BRAIN_DIR="{brain_dir}"
CHROMA_DATA="$BRAIN_DIR/chroma_data"
INGEST_SCRIPT="$BRAIN_DIR/ingest.py"
LOG_FILE="$BRAIN_DIR/logs/ingestion.log"

CHANGED_DOCS=$(git diff --name-only HEAD~1 HEAD 2>/dev/null | grep -E '\\.(md|mdx|txt|rst)$' || true)

if [ -n "$CHANGED_DOCS" ]; then
    echo "[claude-devbrain] Documentation changed — running incremental ingestion..."

    REPO_ROOT=$(git rev-parse --show-toplevel)

    # Detect collection name from config
    COLLECTION=$(python3 -c "
import json, sys
cfg = json.loads(open('$BRAIN_DIR/config.json').read())
for p in cfg['projects']:
    if '$REPO_ROOT'.startswith(p['path']):
        print(p['doc_collection'])
        sys.exit(0)
print('devbrain_docs')
" 2>/dev/null)

    python3 "$INGEST_SCRIPT" \\
        --source "$REPO_ROOT" \\
        --chroma-dir "$CHROMA_DATA" \\
        --collection "$COLLECTION" \\
        --incremental \\
        >> "$LOG_FILE" 2>&1 &

    echo "[claude-devbrain] Ingestion started in background (log: $LOG_FILE)"
fi
"""


def install_post_commit_hook(project: dict, brain_dir: Path) -> bool:
    """Install a post-commit hook in the project's git repo."""
    git_hooks_dir = Path(project["path"]) / ".git" / "hooks"
    if not git_hooks_dir.exists():
        console.print(f"  [yellow]No .git/hooks in {project['path']} — skipping hook.[/yellow]")
        return False

    hook_path = git_hooks_dir / "post-commit"
    hook_content = generate_hook_script(brain_dir)

    # Check for existing hook
    if hook_path.exists():
        existing = hook_path.read_text()
        if "claude-devbrain" in existing or "parthenon-brain" in existing:
            # Our hook — safe to overwrite
            hook_path.write_text(hook_content)
            hook_path.chmod(0o755)
            console.print(f"  [green]Updated[/green] post-commit hook for {project['name']}")
            return True
        else:
            # Foreign hook — append
            console.print(f"  [yellow]Existing post-commit hook found. Appending DevBrain hook.[/yellow]")
            with open(hook_path, "a") as f:
                f.write("\n\n" + hook_content)
            hook_path.chmod(0o755)
            return True

    hook_path.write_text(hook_content)
    hook_path.chmod(0o755)
    console.print(f"  [green]Installed[/green] post-commit hook for {project['name']}")
    return True


# ---------------------------------------------------------------------------
# MCP Server Registration
# ---------------------------------------------------------------------------

def register_mcp_server(config: dict) -> bool:
    """Register the chroma-mcp server with Claude Code."""
    chroma_dir = config["chroma_dir"]

    if not check_command("claude"):
        console.print("  [yellow]Claude Code CLI not found. Manual MCP setup required.[/yellow]")
        show_manual_mcp_config(chroma_dir)
        return False

    use_uvx = check_command("uvx") is not None

    try:
        if use_uvx:
            cmd = [
                "claude", "mcp", "add", "claude-devbrain", "--scope", "user",
                "--", "uvx", "chroma-mcp",
                "--client-type", "persistent",
                "--data-dir", chroma_dir,
            ]
        else:
            cmd = [
                "claude", "mcp", "add", "claude-devbrain", "--scope", "user",
                "--", "python3", "-m", "chroma_mcp",
                "--client-type", "persistent",
                "--data-dir", chroma_dir,
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            console.print("  [green]MCP server registered with Claude Code.[/green]")
            return True
        else:
            console.print(f"  [yellow]Auto-registration returned: {result.stderr.strip()}[/yellow]")
            show_manual_mcp_config(chroma_dir)
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        console.print(f"  [yellow]Could not register MCP server: {e}[/yellow]")
        show_manual_mcp_config(chroma_dir)
        return False


def show_manual_mcp_config(chroma_dir: str):
    """Display manual MCP configuration instructions."""
    config_json = json.dumps({
        "mcpServers": {
            "claude-devbrain": {
                "command": "uvx",
                "args": [
                    "chroma-mcp",
                    "--client-type", "persistent",
                    "--data-dir", chroma_dir,
                ],
            }
        }
    }, indent=2)

    console.print("\n  [bold]Manual MCP setup:[/bold]")
    console.print("  Add this to your ~/.claude.json or project .mcp.json:\n")
    console.print(Panel(config_json, title="MCP Configuration", border_style="blue"))
    console.print("  Or run:")
    console.print(
        f"  [cyan]claude mcp add claude-devbrain --scope user "
        f"-- uvx chroma-mcp --client-type persistent "
        f"--data-dir {chroma_dir}[/cyan]\n"
    )


# ---------------------------------------------------------------------------
# CLAUDE.md Snippet Generation
# ---------------------------------------------------------------------------

def generate_claude_md_snippet(config: dict) -> str:
    """Generate a CLAUDE.md snippet for a project."""
    projects = config["projects"]
    collections_list = []
    for p in projects:
        if p["ingest_docs"]:
            collections_list.append(f"  - `{p['doc_collection']}`: Documentation for {p['name']}")
        if p["ingest_code"]:
            collections_list.append(f"  - `{p['code_collection']}`: Source code for {p['name']}")

    collections_str = "\n".join(collections_list)

    return f"""
## Project Memory (Claude DevBrain)

This project has a persistent knowledge base stored in ChromaDB, accessible via
the `claude-devbrain` MCP server.

### Always Query Before Working

**Before starting any task**, query the DevBrain to recall relevant context:

1. **At the start of every session**, search for context related to the current task.
2. **Before making architectural decisions**, search for prior design decisions and specs.
3. **Before writing new code**, check if similar patterns already exist.

### Available Collections

{collections_str}

### How to Query

Use the Chroma MCP tools (available as `claude-devbrain` in your MCP server list):

- `chroma_query` — Semantic search across collections
- Filter by metadata: `doc_type`, `module`, `extension`, `symbol`, `kind`
""".strip()


def offer_claude_md_snippet(config: dict, project: dict):
    """Offer to show/install a CLAUDE.md snippet for a project."""
    claude_md_paths = [
        Path(project["path"]) / ".claude" / "CLAUDE.md",
        Path(project["path"]) / "CLAUDE.md",
    ]

    existing_path = None
    for p in claude_md_paths:
        if p.exists():
            existing_path = p
            break

    snippet = generate_claude_md_snippet(config)

    if existing_path:
        existing_content = existing_path.read_text()
        if "DevBrain" in existing_content or "devbrain" in existing_content or "parthenon-brain" in existing_content:
            console.print(f"  [dim]CLAUDE.md already has DevBrain section: {existing_path}[/dim]")
            return

        if Confirm.ask(f"  Append DevBrain instructions to {existing_path}?", default=True):
            with open(existing_path, "a") as f:
                f.write("\n\n" + snippet + "\n")
            console.print(f"  [green]Updated[/green] {existing_path}")
    else:
        console.print(f"\n  [dim]CLAUDE.md snippet for your project:[/dim]")
        console.print(Panel(snippet, title="CLAUDE.md Snippet", border_style="blue"))
        console.print("  [dim]Add this to your project's CLAUDE.md to instruct Claude to query the brain.[/dim]\n")


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

def run_ingestion_for_project(config: dict, project: dict):
    """Run ingestion for a single project."""
    brain_dir = Path(config["brain_dir"])
    chroma_dir = config["chroma_dir"]
    ingest_script = brain_dir / "ingest.py"

    if not ingest_script.exists():
        console.print(f"  [red]ingest.py not found at {ingest_script}[/red]")
        return

    project_path = project["path"]
    if not Path(project_path).is_dir():
        console.print(f"  [red]Project path not found: {project_path}[/red]")
        return

    # Documentation ingestion
    if project["ingest_docs"]:
        console.print(f"\n  [bold]Ingesting documentation for {project['name']}...[/bold]")
        cmd = [
            sys.executable, str(ingest_script),
            "--source", project_path,
            "--chroma-dir", chroma_dir,
            "--collection", project["doc_collection"],
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            # Extract summary from stderr (where logging goes)
            output = result.stderr or result.stdout
            for line in output.split("\n"):
                if any(k in line for k in ["Files processed", "Chunks created", "Collection total", "Errors"]):
                    console.print(f"    {line.strip()}")
        except subprocess.TimeoutExpired:
            console.print("  [yellow]Documentation ingestion timed out (10 min limit).[/yellow]")

    # Code ingestion
    if project["ingest_code"]:
        console.print(f"\n  [bold]Ingesting source code for {project['name']}...[/bold]")
        cmd = [
            sys.executable, str(ingest_script),
            "--source", project_path,
            "--chroma-dir", chroma_dir,
            "--collection", project["code_collection"],
            "--include-code",
            "--code-only",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            output = result.stderr or result.stdout
            for line in output.split("\n"):
                if any(k in line for k in ["Files processed", "Chunks created", "Collection total", "Errors"]):
                    console.print(f"    {line.strip()}")
        except subprocess.TimeoutExpired:
            console.print("  [yellow]Code ingestion timed out (10 min limit).[/yellow]")

    # Update last_ingested
    project["last_ingested"] = datetime.now().isoformat()
    save_config(config)


# ---------------------------------------------------------------------------
# Main Menu
# ---------------------------------------------------------------------------

def show_welcome(is_first_run: bool):
    """Display the welcome banner."""
    title = Text("Claude DevBrain", style="bold cyan")
    subtitle = "Persistent memory for Claude Code" if is_first_run else "Project Manager"
    version_text = f"v{VERSION}"

    banner = Text()
    banner.append("\n")
    banner.append("  ", style="")
    banner.append("Claude DevBrain", style="bold cyan")
    banner.append(f"  {version_text}\n", style="dim")
    banner.append("  ", style="")
    banner.append(subtitle, style="")
    banner.append("\n\n", style="")

    if is_first_run:
        banner.append(
            "  Indexes your project documentation and source code into ChromaDB\n"
            "  for semantic retrieval via MCP. Every Claude Code session starts\n"
            "  with full project context instead of a blank slate.\n",
            style="dim",
        )
    else:
        banner.append("  Manage your indexed projects, add new ones, or re-ingest.\n", style="dim")

    console.print(Panel(banner, border_style="cyan", box=box.DOUBLE))


def main_menu(config: dict) -> str:
    """Display main menu and return the user's choice."""
    console.print("\n  [bold]What would you like to do?[/bold]\n")

    options = [
        ("1", "Add a new project"),
        ("2", "View configured projects"),
        ("3", "Remove a project"),
        ("4", "Run ingestion for a project"),
        ("5", "Run ingestion for ALL projects"),
        ("6", "Register/update MCP server"),
        ("7", "Show CLAUDE.md snippet"),
        ("8", "Show collection statistics"),
        ("q", "Quit"),
    ]

    for key, label in options:
        style = "dim" if key == "q" else ""
        console.print(f"    [{style}]{key}[/{style}]  {label}")

    console.print()
    choice = Prompt.ask("  Choose", choices=[k for k, _ in options], default="1")
    return choice


def select_project(config: dict, prompt: str = "Select project") -> dict | None:
    """Let user pick a project from the list."""
    if not config["projects"]:
        console.print("  [dim]No projects configured.[/dim]")
        return None

    display_projects(config)
    idx = IntPrompt.ask(f"  {prompt} (0 to cancel)", default=0)
    if idx == 0 or idx > len(config["projects"]):
        return None
    return config["projects"][idx - 1]


def show_collection_stats(config: dict):
    """Show ChromaDB collection stats via query.py."""
    brain_dir = Path(config["brain_dir"])
    query_script = brain_dir / "query.py"

    if not query_script.exists():
        console.print("  [red]query.py not found.[/red]")
        return

    result = subprocess.run(
        [sys.executable, str(query_script), "--stats",
         "--chroma-dir", config["chroma_dir"]],
        capture_output=True, text=True, timeout=30,
    )
    console.print(result.stdout)
    if result.stderr:
        console.print(result.stderr)


# ---------------------------------------------------------------------------
# First Run Flow
# ---------------------------------------------------------------------------

def first_run(brain_dir: Path) -> dict:
    """Complete first-run setup wizard."""
    show_welcome(is_first_run=True)

    # Step 1: Prerequisites
    console.print(Panel("[bold]Step 1/4:[/bold] Checking prerequisites", style="blue"))
    prereqs = check_prerequisites()
    all_ok = display_prerequisites(prereqs)

    if not all_ok:
        console.print("[red]Critical prerequisites missing. Please install them first.[/red]")
        sys.exit(1)

    install_missing_deps(prereqs)

    # Step 2: Brain directory
    console.print(Panel("[bold]Step 2/4:[/bold] Setting up DevBrain directory", style="blue"))
    console.print(f"  Default location: [cyan]{brain_dir}[/cyan]")
    custom_dir = Confirm.ask("  Use a different directory?", default=False)
    if custom_dir:
        new_dir = Prompt.ask("  Brain directory", default=str(brain_dir))
        brain_dir = Path(new_dir).expanduser().resolve()

    setup_brain_directory(brain_dir)
    config = default_config(brain_dir)
    console.print(f"  [green]Brain directory ready at {brain_dir}[/green]")

    # Step 3: Add projects
    console.print(Panel("[bold]Step 3/4:[/bold] Add your projects", style="blue"))
    console.print("  [dim]Add at least one project to index. You can add more later.[/dim]\n")

    while True:
        entry = add_project_interactive(config)
        if entry:
            config["projects"].append(entry)
            save_config(config)
            console.print(f"\n  [green]Added {entry['name']}![/green]")

            # Install hook if requested
            if entry.get("post_commit_hook"):
                install_post_commit_hook(entry, brain_dir)

        if not Confirm.ask("\n  Add another project?", default=False):
            break

    # Step 4: MCP + Ingestion
    console.print(Panel("[bold]Step 4/4:[/bold] MCP registration & initial ingestion", style="blue"))

    if Confirm.ask("  Register MCP server with Claude Code?", default=True):
        registered = register_mcp_server(config)
        config["mcp_registered"] = registered
        save_config(config)

    if config["projects"]:
        if Confirm.ask("\n  Run initial ingestion now?", default=True):
            for project in config["projects"]:
                run_ingestion_for_project(config, project)

                # Offer CLAUDE.md snippet
                offer_claude_md_snippet(config, project)

    # Done
    console.print(Panel(
        "[bold green]Setup complete![/bold green]\n\n"
        f"  Brain directory: {brain_dir}\n"
        f"  Projects: {len(config['projects'])}\n"
        f"  MCP registered: {'yes' if config.get('mcp_registered') else 'no'}\n\n"
        "  [dim]Re-run installer.py anytime to add projects or re-ingest.[/dim]\n"
        "  [dim]Restart Claude Code to pick up the new MCP server.[/dim]",
        title="All Done",
        border_style="green",
        box=box.DOUBLE,
    ))

    return config


# ---------------------------------------------------------------------------
# Returning User Flow
# ---------------------------------------------------------------------------

def returning_user(config: dict):
    """Main loop for returning users managing their projects."""
    brain_dir = Path(config["brain_dir"])
    show_welcome(is_first_run=False)
    display_projects(config)

    while True:
        choice = main_menu(config)

        if choice == "1":
            entry = add_project_interactive(config)
            if entry:
                config["projects"].append(entry)
                save_config(config)
                console.print(f"\n  [green]Added {entry['name']}![/green]")
                if entry.get("post_commit_hook"):
                    install_post_commit_hook(entry, brain_dir)
                if Confirm.ask("  Run ingestion now?", default=True):
                    run_ingestion_for_project(config, entry)
                    offer_claude_md_snippet(config, entry)

        elif choice == "2":
            display_projects(config)

        elif choice == "3":
            remove_project_interactive(config)

        elif choice == "4":
            project = select_project(config, "Ingest which project?")
            if project:
                run_ingestion_for_project(config, project)

        elif choice == "5":
            if config["projects"]:
                console.print("\n  [bold]Ingesting all projects...[/bold]")
                for project in config["projects"]:
                    run_ingestion_for_project(config, project)
            else:
                console.print("  [dim]No projects configured.[/dim]")

        elif choice == "6":
            registered = register_mcp_server(config)
            config["mcp_registered"] = registered
            save_config(config)

        elif choice == "7":
            project = select_project(config, "Show snippet for which project?")
            if project:
                snippet = generate_claude_md_snippet(config)
                console.print(Panel(snippet, title="CLAUDE.md Snippet", border_style="blue"))

        elif choice == "8":
            show_collection_stats(config)

        elif choice == "q":
            console.print("\n  [dim]Goodbye![/dim]\n")
            break


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Claude DevBrain — Installer & Project Manager")
    parser.add_argument(
        "--brain-dir", type=Path, default=DEFAULT_BRAIN_DIR,
        help=f"Brain directory (default: {DEFAULT_BRAIN_DIR})",
    )
    args = parser.parse_args()

    brain_dir = args.brain_dir.expanduser().resolve()

    # Check if this is a first run or returning
    config = load_config(brain_dir)

    if config is None:
        config = first_run(brain_dir)
    else:
        returning_user(config)


if __name__ == "__main__":
    main()
