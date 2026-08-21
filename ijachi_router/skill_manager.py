"""Skills System for ijachi-code.

Discovers, loads, and activates pluggable skill instruction sets that extend
the agent's capabilities for specific workflows.

Skill Discovery Roots (highest priority first)
----------------------------------------------
1. ``<workspace>/.ijachi/skills/``   — workspace-local skills
2. ``~/.ijachi-llmr/skills/``        — global user skills
3. ``ijachi_router/skills/builtin/`` — built-in packaged skills (lowest priority)

Skill Format
------------
Each skill is a directory containing a ``SKILL.md`` file with YAML frontmatter::

    ---
    name: my-skill
    description: "What this skill does"
    trigger_keywords:
      - "keyword one"
      - "another phrase"
    version: "1.0"
    ---

    # Skill Title

    Markdown instruction body — prepended to the agent system prompt when activated.

Activation
----------
Skills are activated when any of their ``trigger_keywords`` appear in the user
prompt (case-insensitive substring match). Multiple skills can be active at once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

#: Built-in skills shipped with the package
_BUILTIN_SKILLS_DIR = Path(__file__).parent / "skills" / "builtin"

#: Global user skill root
_GLOBAL_SKILLS_DIR = Path.home() / ".ijachi-llmr" / "skills"


# ---------------------------------------------------------------------------
# Skill dataclass
# ---------------------------------------------------------------------------

@dataclass
class Skill:
    """Represents a single loaded skill."""

    name: str
    """Unique skill identifier (directory name)."""
    description: str
    """One-line description shown in skill listings."""
    trigger_keywords: list[str]
    """Lowercase substrings that activate this skill."""
    instructions: str
    """Full markdown instruction body loaded from SKILL.md."""
    version: str
    """Version string from frontmatter."""
    source_path: Path
    """Absolute path to the SKILL.md file."""
    source: str = "builtin"
    """Origin: 'builtin', 'global', or 'workspace'."""

    def matches(self, text: str) -> bool:
        """Return True if any trigger keyword appears in *text* (case-insensitive).

        Args:
            text: The user prompt or task description to match against.

        Returns:
            True if at least one trigger keyword is found in *text*.
        """
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in self.trigger_keywords)

    def to_system_prompt_block(self) -> str:
        """Return the skill instructions formatted as a system prompt injection block.

        Returns:
            A string that can be prepended to an agent system prompt.
        """
        return (
            f"\n\n---\n"
            f"## Active Skill: {self.name} (v{self.version})\n"
            f"_{self.description}_\n\n"
            f"{self.instructions}\n"
            f"---\n"
        )


# ---------------------------------------------------------------------------
# SKILL.md parser
# ---------------------------------------------------------------------------

def _parse_skill_md(path: Path, source: str = "builtin") -> Skill | None:
    """Parse a SKILL.md file and return a :class:`Skill`, or None on error.

    Args:
        path: Absolute path to the SKILL.md file.
        source: Origin label ('builtin', 'global', 'workspace').

    Returns:
        A populated :class:`Skill` or None if parsing fails.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None

    # Split YAML frontmatter from markdown body
    frontmatter: dict[str, Any] = {}
    body = raw

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", raw, re.DOTALL)
    if fm_match:
        try:
            frontmatter = yaml.safe_load(fm_match.group(1)) or {}
            body = fm_match.group(2).strip()
        except yaml.YAMLError:
            body = raw  # Fall back to treating the whole file as the body

    name = frontmatter.get("name") or path.parent.name
    description = frontmatter.get("description", "No description provided.")
    # Flatten description if it's a multi-line YAML scalar
    if isinstance(description, str):
        description = " ".join(description.split())
    trigger_keywords = frontmatter.get("trigger_keywords") or []
    if isinstance(trigger_keywords, str):
        trigger_keywords = [trigger_keywords]
    version = str(frontmatter.get("version", "1.0"))

    return Skill(
        name=name,
        description=description,
        trigger_keywords=[str(k).strip() for k in trigger_keywords],
        instructions=body,
        version=version,
        source_path=path,
        source=source,
    )


# ---------------------------------------------------------------------------
# SkillManager
# ---------------------------------------------------------------------------

class SkillManager:
    """Discovers, loads, lists, and activates ijachi-code skills.

    Workspace-local skills take priority over global skills, which take
    priority over built-in skills. Skills with the same ``name`` from a
    higher-priority source shadow lower-priority ones.

    Usage
    -----
    ::

        manager = SkillManager(workspace_root="/path/to/project")
        active = manager.get_active_skills("fix failing tests")
        system_prompt = manager.build_skill_prompt(active)
    """

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        """Initialise and discover all available skills.

        Args:
            workspace_root: Root of the current workspace. Used to locate
                ``.ijachi/skills/`` local overrides. Defaults to ``cwd``.
        """
        self._workspace_root = Path(workspace_root or Path.cwd()).resolve()
        self._skills: dict[str, Skill] = {}
        self._discover()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover(self) -> None:
        """Scan all skill roots and populate the internal registry.

        Discovery order (last-wins, so workspace overrides global overrides builtin):
        1. Built-in skills
        2. Global user skills (~/.ijachi-llmr/skills/)
        3. Workspace-local skills (<workspace>/.ijachi/skills/)
        """
        for root, source_label in [
            (_BUILTIN_SKILLS_DIR, "builtin"),
            (_GLOBAL_SKILLS_DIR, "global"),
            (self._workspace_root / ".ijachi" / "skills", "workspace"),
        ]:
            self._load_root(root, source_label)

    def _load_root(self, root: Path, source: str) -> None:
        """Load all SKILL.md files found directly under *root*.

        Args:
            root: Directory to scan for skill subdirectories.
            source: Source label to attach to loaded skills.
        """
        if not root.is_dir():
            return
        for skill_dir in sorted(root.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            skill = _parse_skill_md(skill_md, source=source)
            if skill:
                self._skills[skill.name] = skill  # Higher-priority source wins

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_skills(self) -> list[Skill]:
        """Return all discovered skills sorted by name.

        Returns:
            List of :class:`Skill` objects sorted alphabetically by name.
        """
        return sorted(self._skills.values(), key=lambda s: s.name)

    def get_skill(self, name: str) -> Skill | None:
        """Return the skill with the given *name*, or None.

        Args:
            name: Skill name to look up (exact match).

        Returns:
            The :class:`Skill` or None if not found.
        """
        return self._skills.get(name)

    def get_active_skills(self, prompt: str) -> list[Skill]:
        """Return skills whose trigger keywords match *prompt*.

        Args:
            prompt: User message / task description to match against.

        Returns:
            List of matching :class:`Skill` objects.
        """
        return [s for s in self._skills.values() if s.matches(prompt)]

    def build_skill_prompt(self, skills: list[Skill]) -> str:
        """Concatenate the instruction blocks for *skills* into a single string.

        Args:
            skills: List of active skills to include.

        Returns:
            Combined system prompt injection string, or empty string if no skills.
        """
        if not skills:
            return ""
        return "".join(s.to_system_prompt_block() for s in skills)

    def install_skill(self, source_dir: Path | str) -> str:
        """Copy a skill directory into the global skills root.

        Args:
            source_dir: Path to the skill directory (must contain SKILL.md).

        Returns:
            Status message describing the result.
        """
        import shutil

        source_dir = Path(source_dir).resolve()
        skill_md = source_dir / "SKILL.md"
        if not skill_md.exists():
            return f"✗ No SKILL.md found in '{source_dir}'."

        skill = _parse_skill_md(skill_md, source="global")
        if not skill:
            return f"✗ Failed to parse SKILL.md in '{source_dir}'."

        dest = _GLOBAL_SKILLS_DIR / source_dir.name
        _GLOBAL_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, dest, dirs_exist_ok=True)

        # Refresh registry
        self._skills.pop(skill.name, None)
        self._load_root(_GLOBAL_SKILLS_DIR, "global")

        return f"✓ Skill '{skill.name}' installed to {dest}."

    def print_skills_table(self) -> None:
        """Print a Rich table of all discovered skills to stdout."""
        try:
            from rich.console import Console
            from rich.table import Table
            from rich import box
        except ImportError:
            for s in self.list_skills():
                print(f"  [{s.source}] {s.name:<20} — {s.description}")
            return

        console = Console()
        table = Table(
            title="[bold cyan]⚡ Available ijachi-code Skills[/bold cyan]",
            box=box.ROUNDED,
            header_style="bold magenta",
            show_lines=True,
        )
        table.add_column("Name", style="bold cyan", width=18)
        table.add_column("Source", style="dim", width=10)
        table.add_column("Version", width=8)
        table.add_column("Trigger Keywords", style="dim yellow", width=35)
        table.add_column("Description", style="italic white")

        source_icon = {"builtin": "📦", "global": "🌐", "workspace": "📁"}
        for skill in self.list_skills():
            icon = source_icon.get(skill.source, "•")
            keywords = ", ".join(skill.trigger_keywords[:4])
            if len(skill.trigger_keywords) > 4:
                keywords += f" (+{len(skill.trigger_keywords) - 4} more)"
            table.add_row(
                skill.name,
                f"{icon} {skill.source}",
                skill.version,
                keywords,
                skill.description[:80],
            )

        console.print()
        console.print(table)
        console.print()
        console.print(
            "[dim cyan]💡 Add custom skills: ijachi-router skills add <path_to_skill_dir>[/dim cyan]"
        )
        console.print(
            "[dim cyan]💡 Workspace skills: create <project>/.ijachi/skills/<name>/SKILL.md[/dim cyan]\n"
        )
