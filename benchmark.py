#!/usr/bin/env python3
"""
Claude DevBrain — Benchmark Tool
===================================
Compares Claude Code responses with and without the DevBrain MCP server
on project-specific questions with verifiable ground truth.

Runs each question through:
  1. Claude with NO MCP (blank slate) — uses --bare --tools ""
  2. Claude WITH DevBrain MCP — uses --mcp-config with chroma-mcp

Then scores each response against known ground truth keywords/facts.

Usage:
    python benchmark.py
    python benchmark.py --brain-dir ~/.claude-devbrain
    python benchmark.py --questions questions.json
    python benchmark.py --quick          # Run only 3 questions
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import box

console = Console()

DEFAULT_BRAIN_DIR = Path.home() / ".claude-devbrain"
TIMEOUT_SECONDS = 120


# ---------------------------------------------------------------------------
# Built-in Questions — Parthenon-specific with verifiable ground truth
# ---------------------------------------------------------------------------

BUILTIN_QUESTIONS = [
    {
        "id": "q1",
        "question": "What web framework does the Parthenon backend use and what version?",
        "ground_truth_keywords": ["laravel", "11"],
        "ground_truth_description": "Laravel 11",
        "category": "tech_stack",
    },
    {
        "id": "q2",
        "question": "What database does Parthenon use and how is it organized — separate databases or schema isolation?",
        "ground_truth_keywords": ["postgresql", "schema", "single", "parthenon"],
        "ground_truth_description": "Single PostgreSQL database named 'parthenon' with schema isolation (app, omop, results, gis, eunomia)",
        "category": "architecture",
    },
    {
        "id": "q3",
        "question": "What is the Commons module in Parthenon and what technology powers its real-time features?",
        "ground_truth_keywords": ["real-time", "collaboration", "websocket"],
        "ground_truth_description": "Real-time collaborative workspace using Laravel Reverb (WebSocket), Redis, and PostgreSQL",
        "category": "module_knowledge",
    },
    {
        "id": "q4",
        "question": "What AI assistant is built into Parthenon and what LLM does it use?",
        "ground_truth_keywords": ["abby", "ollama"],
        "ground_truth_description": "Abby — a FastAPI service using Ollama with MedGemma for medical AI",
        "category": "module_knowledge",
    },
    {
        "id": "q5",
        "question": "What is the OMOP CDM and which version does Parthenon implement?",
        "ground_truth_keywords": ["omop", "common data model", "5.4"],
        "ground_truth_description": "OMOP Common Data Model v5.4 — a standardized healthcare data schema from OHDSI",
        "category": "domain_knowledge",
    },
    {
        "id": "q6",
        "question": "What frontend framework and state management library does Parthenon use?",
        "ground_truth_keywords": ["react", "zustand"],
        "ground_truth_description": "React 19 with TypeScript, Zustand for state management, TanStack Query for data fetching",
        "category": "tech_stack",
    },
    {
        "id": "q7",
        "question": "How does Parthenon handle search functionality — what search engine and how many configsets?",
        "ground_truth_keywords": ["solr"],
        "ground_truth_description": "Solr 9.7 with 9 configsets: vocabulary, cohorts, analyses, mappings, clinical, imaging, claims, gis_spatial, vector_explorer",
        "category": "architecture",
    },
    {
        "id": "q8",
        "question": "What is the study-agent submodule in Parthenon and what does it do?",
        "ground_truth_keywords": ["study", "agent", "ohdsi"],
        "ground_truth_description": "An OHDSI StudyAgent that automates network study execution — phenotype recommendations, cohort building, analysis orchestration",
        "category": "module_knowledge",
    },
    {
        "id": "q9",
        "question": "What Python AI service framework does Parthenon use and what vector database for embeddings?",
        "ground_truth_keywords": ["fastapi", "pgvector"],
        "ground_truth_description": "FastAPI with Pydantic v2, pgvector for concept embeddings, ChromaDB for Abby's memory",
        "category": "tech_stack",
    },
    {
        "id": "q10",
        "question": "What R packages does Parthenon integrate for observational health studies?",
        "ground_truth_keywords": ["hades"],
        "ground_truth_description": "HADES packages via R 4.4 Plumber API — CohortMethod, PatientLevelPrediction, etc.",
        "category": "domain_knowledge",
    },
]


# ---------------------------------------------------------------------------
# MCP Config Generation
# ---------------------------------------------------------------------------

def create_mcp_config(brain_dir: Path) -> str:
    """Create a temporary MCP config file for the devbrain server."""
    chroma_dir = brain_dir / "chroma_data"
    config = {
        "mcpServers": {
            "claude-devbrain": {
                "command": "uvx",
                "args": [
                    "chroma-mcp",
                    "--client-type", "persistent",
                    "--data-dir", str(chroma_dir),
                ],
            }
        }
    }

    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, prefix="devbrain-mcp-")
    json.dump(config, tmp)
    tmp.close()
    return tmp.name


# ---------------------------------------------------------------------------
# Claude Invocation
# ---------------------------------------------------------------------------

def run_claude_without_brain(question: str, project_hint: str = "Parthenon") -> tuple[str, float]:
    """Run claude -p with no MCP, no tools, no project context (bare mode)."""
    prompt = (
        f"Answer this question about the {project_hint} software project. "
        f"Be specific and concise.\n\n{question}"
    )

    start = time.time()
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--tools", ""],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        elapsed = time.time() - start
        return (result.stdout.strip() or result.stderr.strip()), elapsed
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]", TIMEOUT_SECONDS
    except Exception as e:
        return f"[ERROR: {e}]", 0.0


def run_claude_with_brain(question: str, mcp_config_path: str, project_hint: str = "Parthenon") -> tuple[str, float]:
    """Run claude -p with the DevBrain MCP server available."""
    prompt = (
        f"You have access to a ChromaDB MCP server called 'claude-devbrain' that contains "
        f"indexed documentation and source code for the {project_hint} project. "
        f"Use the chroma tools to search for relevant context before answering. "
        f"Search the docs and code collections. "
        f"Then answer this question concisely and specifically:\n\n{question}"
    )

    start = time.time()
    try:
        result = subprocess.run(
            [
                "claude", "-p", prompt,
                "--mcp-config", mcp_config_path,
                "--allowedTools", "mcp__claude-devbrain__*",
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        elapsed = time.time() - start
        return (result.stdout.strip() or result.stderr.strip()), elapsed
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]", TIMEOUT_SECONDS
    except Exception as e:
        return f"[ERROR: {e}]", 0.0


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_response(response: str, keywords: list[str]) -> tuple[float, list[str], list[str]]:
    """Score a response against ground truth keywords.

    Returns (score 0.0-1.0, found_keywords, missing_keywords).
    """
    response_lower = response.lower()
    found = []
    missing = []

    for kw in keywords:
        if kw.lower() in response_lower:
            found.append(kw)
        else:
            missing.append(kw)

    score = len(found) / len(keywords) if keywords else 0.0
    return score, found, missing


# ---------------------------------------------------------------------------
# Benchmark Runner
# ---------------------------------------------------------------------------

def run_benchmark(
    questions: list[dict],
    brain_dir: Path,
    project_hint: str = "Parthenon",
) -> dict:
    """Run the full benchmark and return results."""
    mcp_config_path = create_mcp_config(brain_dir)

    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for i, q in enumerate(questions):
            qid = q["id"]
            question = q["question"]
            keywords = q["ground_truth_keywords"]

            # --- Without brain ---
            task = progress.add_task(f"[{i+1}/{len(questions)}] Without brain: {qid}", total=None)
            response_without, time_without = run_claude_without_brain(question, project_hint)
            score_without, found_without, missing_without = score_response(response_without, keywords)
            progress.remove_task(task)

            # --- With brain ---
            task = progress.add_task(f"[{i+1}/{len(questions)}] With brain: {qid}", total=None)
            response_with, time_with = run_claude_with_brain(question, mcp_config_path, project_hint)
            score_with, found_with, missing_with = score_response(response_with, keywords)
            progress.remove_task(task)

            result = {
                "id": qid,
                "question": question,
                "category": q.get("category", "general"),
                "ground_truth": q["ground_truth_description"],
                "keywords": keywords,
                "without_brain": {
                    "response": response_without[:500],
                    "score": score_without,
                    "found": found_without,
                    "missing": missing_without,
                    "time_seconds": round(time_without, 1),
                },
                "with_brain": {
                    "response": response_with[:500],
                    "score": score_with,
                    "found": found_with,
                    "missing": missing_with,
                    "time_seconds": round(time_with, 1),
                },
            }
            results.append(result)

            # Live update
            emoji_without = "x" if score_without < 0.5 else ("~" if score_without < 1.0 else "ok")
            emoji_with = "x" if score_with < 0.5 else ("~" if score_with < 1.0 else "ok")
            console.print(
                f"  {qid}: without={score_without:.0%} [{emoji_without}]  "
                f"with={score_with:.0%} [{emoji_with}]  "
                f"({time_without:.0f}s / {time_with:.0f}s)"
            )

    # Cleanup
    try:
        os.unlink(mcp_config_path)
    except OSError:
        pass

    return {
        "timestamp": datetime.now().isoformat(),
        "brain_dir": str(brain_dir),
        "project": project_hint,
        "num_questions": len(questions),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Display Results
# ---------------------------------------------------------------------------

def display_results(benchmark: dict):
    """Display benchmark results as a rich table."""
    results = benchmark["results"]

    # Summary table
    table = Table(
        title="DevBrain Benchmark Results",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("#", style="bold", width=4)
    table.add_column("Category", style="dim", width=16)
    table.add_column("Question", width=40)
    table.add_column("Without\nBrain", justify="center", width=10)
    table.add_column("With\nBrain", justify="center", width=10)
    table.add_column("Delta", justify="center", width=8)

    total_without = 0.0
    total_with = 0.0

    for r in results:
        sw = r["without_brain"]["score"]
        swd = r["with_brain"]["score"]
        total_without += sw
        total_with += swd
        delta = swd - sw

        # Color coding
        without_str = f"[red]{sw:.0%}[/red]" if sw < 0.5 else (f"[yellow]{sw:.0%}[/yellow]" if sw < 1.0 else f"[green]{sw:.0%}[/green]")
        with_str = f"[red]{swd:.0%}[/red]" if swd < 0.5 else (f"[yellow]{swd:.0%}[/yellow]" if swd < 1.0 else f"[green]{swd:.0%}[/green]")

        if delta > 0:
            delta_str = f"[green]+{delta:.0%}[/green]"
        elif delta < 0:
            delta_str = f"[red]{delta:.0%}[/red]"
        else:
            delta_str = f"[dim]0%[/dim]"

        q_short = r["question"][:38] + "..." if len(r["question"]) > 40 else r["question"]
        table.add_row(r["id"], r["category"], q_short, without_str, with_str, delta_str)

    console.print()
    console.print(table)

    # Aggregate scores
    n = len(results)
    avg_without = total_without / n if n else 0
    avg_with = total_with / n if n else 0
    improvement = avg_with - avg_without

    time_without = sum(r["without_brain"]["time_seconds"] for r in results)
    time_with = sum(r["with_brain"]["time_seconds"] for r in results)

    summary = (
        f"\n"
        f"  [bold]Aggregate Scores[/bold]\n\n"
        f"  Without DevBrain:  {avg_without:.0%}  ({time_without:.0f}s total)\n"
        f"  With DevBrain:     {avg_with:.0%}  ({time_with:.0f}s total)\n"
        f"  Improvement:       [bold {'green' if improvement > 0 else 'red'}]"
        f"{'+' if improvement > 0 else ''}{improvement:.0%}[/bold {'green' if improvement > 0 else 'red'}]\n\n"
        f"  Questions: {n}  |  "
        f"Perfect (with): {sum(1 for r in results if r['with_brain']['score'] == 1.0)}/{n}  |  "
        f"Perfect (without): {sum(1 for r in results if r['without_brain']['score'] == 1.0)}/{n}"
    )

    console.print(Panel(summary, title="Summary", border_style="cyan"))


def display_detailed_results(benchmark: dict):
    """Show detailed per-question results with response excerpts."""
    for r in benchmark["results"]:
        console.print(f"\n{'=' * 70}")
        console.print(f"  [bold]{r['id']}[/bold]: {r['question']}")
        console.print(f"  [dim]Ground truth: {r['ground_truth']}[/dim]")
        console.print(f"  [dim]Keywords: {', '.join(r['keywords'])}[/dim]")

        console.print(f"\n  [red]Without Brain[/red] (score: {r['without_brain']['score']:.0%}):")
        console.print(f"  Found: {r['without_brain']['found']}")
        console.print(f"  Missing: {r['without_brain']['missing']}")
        response = r["without_brain"]["response"][:300]
        console.print(Panel(response, border_style="red", width=68))

        console.print(f"  [green]With Brain[/green] (score: {r['with_brain']['score']:.0%}):")
        console.print(f"  Found: {r['with_brain']['found']}")
        console.print(f"  Missing: {r['with_brain']['missing']}")
        response = r["with_brain"]["response"][:300]
        console.print(Panel(response, border_style="green", width=68))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Claude DevBrain — Benchmark Tool")
    parser.add_argument(
        "--brain-dir", type=Path, default=DEFAULT_BRAIN_DIR,
        help=f"Brain directory (default: {DEFAULT_BRAIN_DIR})",
    )
    parser.add_argument(
        "--questions", type=Path, default=None,
        help="Custom questions JSON file",
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Run only 3 questions for a quick test",
    )
    parser.add_argument(
        "--detailed", action="store_true",
        help="Show detailed per-question results with response excerpts",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Save full results as JSON",
    )
    parser.add_argument(
        "--project", default="Parthenon",
        help="Project name hint for the prompts (default: Parthenon)",
    )

    args = parser.parse_args()

    # Validate brain dir
    chroma_dir = args.brain_dir / "chroma_data"
    if not chroma_dir.exists():
        console.print(f"[red]ChromaDB data not found at {chroma_dir}[/red]")
        console.print("Run the installer and ingest a project first.")
        sys.exit(1)

    # Load questions
    if args.questions:
        questions = json.loads(args.questions.read_text())
    else:
        questions = BUILTIN_QUESTIONS

    if args.quick:
        questions = questions[:3]

    # Banner
    console.print(Panel(
        f"  [bold cyan]Claude DevBrain Benchmark[/bold cyan]\n\n"
        f"  Questions: {len(questions)}\n"
        f"  Brain: {args.brain_dir}\n"
        f"  Project: {args.project}\n\n"
        f"  Each question runs twice: once without MCP, once with DevBrain.\n"
        f"  Responses are scored against known ground truth keywords.",
        border_style="cyan",
        box=box.DOUBLE,
    ))

    if not Confirm.ask("\n  Ready to start?", default=True):
        return

    console.print()

    # Run benchmark
    benchmark = run_benchmark(questions, args.brain_dir, args.project)

    # Display results
    display_results(benchmark)

    if args.detailed:
        display_detailed_results(benchmark)

    # Save results
    if args.output:
        args.output.write_text(json.dumps(benchmark, indent=2, default=str))
        console.print(f"\n  [dim]Full results saved to {args.output}[/dim]")
    else:
        # Auto-save to brain dir
        output_path = args.brain_dir / f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        output_path.write_text(json.dumps(benchmark, indent=2, default=str))
        console.print(f"\n  [dim]Full results saved to {output_path}[/dim]")


if __name__ == "__main__":
    main()
