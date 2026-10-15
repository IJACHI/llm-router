"""Automatic Tech Stack Determination and Architecture Synthesis.

Evaluates user coding requests to automatically determine the optimal modern tech stack
when none is explicitly specified, announcing the choice and recording it in the session ledger.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ijachi_router.session.state import SessionState


@dataclass
class TechStackRecommendation:
    name: str
    category: str
    components: dict[str, str]
    rationale: str

    def format_terminal_card(self) -> str:
        """Format a rich terminal card explaining the chosen tech stack."""
        lines = [
            f"[bold cyan]🏗️  Optimal Tech Stack Determined: {self.name}[/bold cyan]",
            f"[dim]Project Type:[/dim] [white]{self.category}[/white]",
            "",
            "[bold]Components:[/bold]",
        ]
        for comp, desc in self.components.items():
            lines.append(f"  • [bold green]{comp:12s}[/bold green]: {desc}")
        lines.append("")
        lines.append(f"[bold]Rationale:[/bold] [italic]{self.rationale}[/italic]")
        lines.append("[dim]✓ Recorded in session ledger — all code and files will adhere to this stack.[/dim]")
        return "\n".join(lines)


# Common stacks by problem domain
_DOMAIN_STACKS = {
    "medical_newsletter": TechStackRecommendation(
        name="FastAPI + Tailwind SPA + SQLite + APScheduler",
        category="Automated Content Aggregator & Newsletter Website",
        components={
            "Backend": "Python FastAPI (async PubMed API ingestion, automated summarizer, REST API)",
            "Frontend": "Modern responsive HTML5/TailwindCSS single-page dashboard",
            "Database": "SQLite via aiosqlite (zero-config, high-performance local paper cache)",
            "Automation": "APScheduler / Asyncio background worker for weekly cron fetching",
        },
        rationale="Lightweight, fast to run locally with zero cloud database setup, perfect for API aggregation and responsive reading.",
    ),
    "web_app": TechStackRecommendation(
        name="FastAPI + Modern HTML5/Tailwind SPA + SQLite",
        category="Full-Stack Web Application",
        components={
            "Backend": "Python FastAPI (clean REST endpoints, Pydantic validation)",
            "Frontend": "HTML5, TailwindCSS, and Vanilla JS / Alpine for responsive UI",
            "Database": "SQLite with SQLAlchemy / aiosqlite for persistence",
        },
        rationale="Modular architecture, immediate local execution, no complex Node/React build step required unless asked.",
    ),
    "data_pipeline": TechStackRecommendation(
        name="Python + Polars / Pandas + DuckDB",
        category="Data Pipeline & Analytics",
        components={
            "Ingestion": "httpx / requests with retry backoff",
            "Processing": "Polars (high performance, multi-threaded columnar processing)",
            "Storage": "DuckDB / Parquet for embedded analytics",
        },
        rationale="Blazing fast data aggregation, minimal resource overhead, superior memory efficiency.",
    ),
    "cli_tool": TechStackRecommendation(
        name="Python (Click + Rich + Pydantic)",
        category="Terminal Application / Developer Tool",
        components={
            "CLI Engine": "Click for command parsing and nested subcommands",
            "UI / Styling": "Rich for tables, spinners, markdown, and neon styling",
            "Validation": "Pydantic for configuration and data schemas",
        },
        rationale="Standard production toolchain for terminal utilities with beautiful UI and cross-platform reliability.",
    ),
    "api_service": TechStackRecommendation(
        name="FastAPI + Pydantic v2 + Uvicorn",
        category="REST API Microservice",
        components={
            "Framework": "FastAPI with ASGI async request handling",
            "Validation": "Pydantic v2 for sub-millisecond serialization",
            "Testing": "pytest + httpx AsyncClient",
        },
        rationale="Highest throughput Python API framework with automatic OpenAPI docs and type safety.",
    ),
}

_EXPLICIT_STACK_KEYWORDS = {
    "django", "flask", "fastapi", "express", "nestjs", "nextjs", "next.js",
    "react", "vue", "angular", "svelte", "solid", "vite", "spring", "rails",
    "rust", "golang", "go", "gin", "actix", "axum", "laravel", "dotnet",
}


def detect_and_determine_tech_stack(
    prompt: str,
    workspace_dir: Path | str,
    session_state: "SessionState",
) -> TechStackRecommendation | None:
    """Analyze coding prompt and determine optimal tech stack if not specified."""
    p_lower = prompt.lower()
    ws = Path(workspace_dir).resolve()

    # 1. If project already has an established stack in workspace, honor it
    if (ws / "package.json").exists():
        return None
    if (ws / "Cargo.toml").exists():
        return None
    if (ws / "go.mod").exists():
        return None

    # 2. If prompt is not a project creation or scaffolding request, skip
    creation_verbs = ["build", "create", "scaffold", "develop", "implement", "make a", "generate a", "start a new", "code a"]
    if not any(v in p_lower for v in creation_verbs):
        return None

    # Exclude execution, inspection, or running requests
    execution_keywords = ["run", "launch", "serve", "execute", "start the", "test", "debug", "explain", "check", "kill"]
    if any(re.search(r"\b" + re.escape(kw) + r"\b", p_lower) for kw in execution_keywords):
        return None

    # 3. If user explicitly specified a tech stack in their prompt, honor it
    for stack_kw in _EXPLICIT_STACK_KEYWORDS:
        if re.search(r"\b" + re.escape(stack_kw) + r"\b", p_lower):
            return None

    # 4. Check if tech stack was already decided in this session
    for entry in session_state.ledger.entries:
        if "tech stack" in entry.fact.lower():
            return None

    # 5. Determine best fit stack based on domain
    if any(kw in p_lower for kw in ("medical", "newsletter", "paper", "pubmed", "aggregate", "summarize")):
        rec = _DOMAIN_STACKS["medical_newsletter"]
    elif any(kw in p_lower for kw in ("website", "dashboard", "portal", "full-stack", "fullstack")):
        rec = _DOMAIN_STACKS["web_app"]
    elif any(kw in p_lower for kw in ("cli", "terminal", "command-line")):
        rec = _DOMAIN_STACKS["cli_tool"]
    elif any(kw in p_lower for kw in ("pipeline", "etl", "crawl", "scrape", "dataset")):
        rec = _DOMAIN_STACKS["data_pipeline"]
    elif any(kw in p_lower for kw in ("api", "microservice", "backend")):
        rec = _DOMAIN_STACKS["api_service"]
    else:
        rec = _DOMAIN_STACKS["web_app"]

    # Record decision into the Facts and Decisions Ledger
    decision_text = f"Tech stack determined: {rec.name} ({rec.rationale})"
    session_state.ledger.record_decision(decision_text, turn=session_state.turn_count)

    return rec
