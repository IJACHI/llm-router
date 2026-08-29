"""Skills System for ijachi-code.

Inspired by Claude Code and nano-claude-code's skill architecture:
- Loads built-in skills (/commit, /review, /test, /audit)
- Loads user skills from ~/.ijachi-llmr/skills/*.md
- Loads project skills from .ijachi/skills/*.md
- Supports Markdown files with YAML frontmatter or raw prompt templates
- Parameter substitution ($ARGUMENTS, $1, $2, etc.)
- Dynamic registration into the REPL command dispatcher
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_USER_SKILLS_DIR = Path.home() / ".ijachi-llmr" / "skills"


@dataclass
class Skill:
    name: str
    description: str
    template: str
    scope: str = "builtin"
    source_path: Path | None = None

    def render(self, arguments: str = "") -> str:
        """Substitute $ARGUMENTS, $1, $2 into template."""
        args_clean = arguments.strip()
        rendered = self.template

        # Positional arguments: $1, $2, etc.
        parts = args_clean.split()
        for idx, part in enumerate(parts, start=1):
            rendered = re.sub(rf"\${idx}\b", part, rendered)

        # Full arguments string: $ARGUMENTS
        if "$ARGUMENTS" in rendered:
            rendered = rendered.replace("$ARGUMENTS", args_clean)
        elif args_clean:
            # If $ARGUMENTS wasn't in template, append user input
            rendered = f"{rendered.strip()}\n\nUser Arguments / Context:\n{args_clean}"

        return rendered.strip()


# ---------------------------------------------------------------------------
# Built-in Skills
# ---------------------------------------------------------------------------

_BUILTIN_SKILLS: list[Skill] = [
    Skill(
        name="commit",
        description="Inspect git diff and generate a clean Conventional Commit",
        template="""Review the current workspace git diff using git status and git diff.
Formulate a concise, high-quality Conventional Commit message following the format:
<type>(<scope>): <short summary>

Ensure the commit accurately summarizes the changes. Then use run_command to stage and commit the changes if approved.""",
        scope="builtin",
    ),
    Skill(
        name="review",
        description="Perform a thorough code review checking for bugs, security, and performance",
        template="""Perform a comprehensive code review of the workspace:
1. Examine recent modifications or the specified files: $ARGUMENTS
2. Check for security vulnerabilities (e.g. injection, credential leakage, unhandled exceptions)
3. Check for logic edge cases and performance bottlenecks
4. Verify adherence to existing patterns and conventions
Provide a structured, actionable review summary with recommended diffs where appropriate.""",
        scope="builtin",
    ),
    Skill(
        name="test",
        description="Run test suite and automatically repair any failing tests",
        template="""Run the workspace test suite ($ARGUMENTS or default test command).
Inspect any failure tracebacks, identify the root causes in the codebase, apply the minimal correct fixes using edit_file, and re-run tests until 100% pass.""",
        scope="builtin",
    ),
    Skill(
        name="audit",
        description="Security & dependency audit of the project workspace",
        template="""Perform a security and health audit of the project:
1. Inspect dependency manifests (requirements.txt, pyproject.toml, package.json, etc.)
2. Check for unpinned or obsolete packages and known vulnerabilities
3. Check for exposed secrets, hardcoded API keys, or sensitive configs (.env files committed)
4. Report findings with clear severity ratings (High, Medium, Low) and remediation steps.""",
        scope="builtin",
    ),
]


# ---------------------------------------------------------------------------
# Markdown Skill Parser
# ---------------------------------------------------------------------------

def _parse_markdown_skill(path: Path, scope: str) -> Skill | None:
    """Parse a Markdown skill file with optional YAML frontmatter."""
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return None

        name = path.stem.lower()
        description = f"Custom skill from {path.name}"
        template = raw

        # Check for YAML frontmatter: --- ... ---
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.DOTALL)
        if fm_match:
            frontmatter_text = fm_match.group(1)
            template = fm_match.group(2).strip()

            for line in frontmatter_text.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip().lower()
                    val = val.strip().strip("\"'")
                    if key == "name":
                        name = val.lower().lstrip("/")
                    elif key == "description":
                        description = val

        return Skill(
            name=name,
            description=description,
            template=template,
            scope=scope,
            source_path=path,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Discovery & Registry
# ---------------------------------------------------------------------------

def discover_skills(cwd: Path | str | None = None) -> dict[str, Skill]:
    """
    Discover all available skills from:
    1. Built-in skills
    2. User-global skills (~/.ijachi-llmr/skills/*.md)
    3. Project-local skills (.ijachi/skills/*.md)
    """
    skills: dict[str, Skill] = {}

    # 1. Built-in
    for s in _BUILTIN_SKILLS:
        skills[s.name] = s

    # 2. User-global
    if _USER_SKILLS_DIR.exists():
        for f in sorted(_USER_SKILLS_DIR.glob("*.md")):
            skill = _parse_markdown_skill(f, scope="user")
            if skill:
                skills[skill.name] = skill

    # 3. Project-local
    ws = Path(cwd or Path.cwd()).resolve()
    project_skills_dir = ws / ".ijachi" / "skills"
    if project_skills_dir.exists():
        for f in sorted(project_skills_dir.glob("*.md")):
            skill = _parse_markdown_skill(f, scope="project")
            if skill:
                skills[skill.name] = skill

    return skills
