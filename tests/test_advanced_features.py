"""Tests for Advanced Features learned from Claude Code architecture teardown:
1. Multi-strategy fuzzy file editing (exact, line-endings, indentation-tolerant)
2. Tool result micro-compaction (list_dir, grep_search, read_file collapsing)
3. Dual-scope memory (user-global preferences vs project-workspace memory)
4. Custom Markdown skill loader & execution
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from ijachi_router.agent import WorkspaceTools, AgenticRouter, load_memory, save_memory
from ijachi_router.skills_loader import Skill, discover_skills, _parse_markdown_skill


# ---------------------------------------------------------------------------
# 1. Multi-Strategy Fuzzy File Editing
# ---------------------------------------------------------------------------

def test_fuzzy_edit_exact_match(tmp_path):
    f = tmp_path / "hello.py"
    f.write_text("def foo():\n    return 42\n")
    tools = WorkspaceTools(root_dir=tmp_path)
    res = tools.edit_file("hello.py", "return 42", "return 100", require_approval=False)
    assert "Successfully applied" in res
    assert "return 100" in f.read_text()


def test_fuzzy_edit_line_endings(tmp_path):
    f = tmp_path / "windows.py"
    f.write_bytes(b"line1\r\nline2\r\nline3\r\n")
    tools = WorkspaceTools(root_dir=tmp_path)
    res = tools.edit_file("windows.py", "line2", "replaced_line", require_approval=False)
    assert "Successfully applied" in res
    assert "replaced_line" in f.read_text()


def test_fuzzy_edit_indentation_tolerant(tmp_path):
    """Even if LLM provides different indentation or trailing space, it matches the target block."""
    f = tmp_path / "indent.py"
    f.write_text(
        "class Greeter:\n"
        "    def say_hi(self):\n"
        "        msg = 'hello'\n"
        "        print(msg)\n"
    )
    tools = WorkspaceTools(root_dir=tmp_path)
    # Target provided with 2 spaces instead of 4 spaces
    target = "  msg = 'hello'\n  print(msg)"
    replacement = "        msg = 'hi there'\n        print(msg)"
    res = tools.edit_file("indent.py", target, replacement, require_approval=False)
    assert "Successfully applied" in res
    assert "indentation/whitespace tolerant" in res
    assert "hi there" in f.read_text()


# ---------------------------------------------------------------------------
# 2. Tool Result Micro-Compaction
# ---------------------------------------------------------------------------

def test_micro_compact_list_dir():
    long_list = "Tool Output (list_dir):\n" + "\n".join([f"  📄 file_{i}.py" for i in range(25)])
    compacted = AgenticRouter._micro_compact_turn(long_list)
    assert "additional directory items collapsed" in compacted
    assert len(compacted) < len(long_list)


def test_micro_compact_grep_search():
    long_grep = "Tool Output (grep_search):\n" + "\n".join([f"  src/app.py:{i}: match {i}" for i in range(20)])
    compacted = AgenticRouter._micro_compact_turn(long_grep)
    assert "additional grep matches collapsed" in compacted
    assert len(compacted) < len(long_grep)


def test_micro_compact_read_file():
    long_read = "Tool Output (read_file):\n" + "\n".join([f"{i:3d} | code line {i}" for i in range(60)])
    compacted = AgenticRouter._micro_compact_turn(long_read)
    assert "lines collapsed to save context" in compacted
    assert len(compacted) < len(long_read)


# ---------------------------------------------------------------------------
# 3. Dual-Scope Memory (User vs Project)
# ---------------------------------------------------------------------------

def test_dual_scope_memory(tmp_path):
    with tempfile.TemporaryDirectory() as mem_tmp:
        import ijachi_router.agent as agent_mod
        orig_mem_dir = agent_mod._MEMORY_DIR
        orig_user_file = agent_mod._USER_MEMORY_FILE
        try:
            agent_mod._MEMORY_DIR = Path(mem_tmp)
            agent_mod._USER_MEMORY_FILE = Path(mem_tmp) / "user_preferences.txt"

            # 1. Save global user preference
            save_memory(tmp_path, "Prefers pytest and black", scope="user")

            # 2. Save project-specific memory
            save_memory(tmp_path, "Backend is FastAPI, uses SQLite database", scope="project")

            # 3. Load combined memory
            combined = load_memory(tmp_path, scope="all")
            assert combined is not None
            assert "[Global Developer Preferences]" in combined
            assert "Prefers pytest and black" in combined
            assert "[Project Workspace Memory]" in combined
            assert "FastAPI" in combined

            # 4. Load only user scope
            user_only = load_memory(tmp_path, scope="user")
            assert "Prefers pytest" in user_only
            assert "FastAPI" not in user_only

            # 5. Load only project scope
            proj_only = load_memory(tmp_path, scope="project")
            assert "FastAPI" in proj_only
            assert "pytest" not in proj_only

        finally:
            agent_mod._MEMORY_DIR = orig_mem_dir
            agent_mod._USER_MEMORY_FILE = orig_user_file


# ---------------------------------------------------------------------------
# 4. Skills System
# ---------------------------------------------------------------------------

def test_builtin_skills_discovered():
    skills = discover_skills()
    for name in ("commit", "review", "test", "audit"):
        assert name in skills
        assert skills[name].scope == "builtin"


def test_custom_markdown_skill_parsing(tmp_path):
    skill_file = tmp_path / "deploy.md"
    skill_file.write_text(
        "---\n"
        "name: deploy\n"
        "description: Deploy service to cloud environment\n"
        "---\n"
        "Build the Docker container and deploy to $1 environment using flags: $ARGUMENTS\n"
    )
    skill = _parse_markdown_skill(skill_file, scope="project")
    assert skill is not None
    assert skill.name == "deploy"
    assert skill.description == "Deploy service to cloud environment"

    # Test parameter substitution
    rendered = skill.render("staging --tag v1.2")
    assert "deploy to staging environment" in rendered
    assert "flags: staging --tag v1.2" in rendered


def test_project_skills_discovery(tmp_path):
    project_skills = tmp_path / ".ijachi" / "skills"
    project_skills.mkdir(parents=True, exist_ok=True)
    (project_skills / "benchmark.md").write_text("Run performance benchmarks on $ARGUMENTS")

    skills = discover_skills(cwd=tmp_path)
    assert "benchmark" in skills
    assert skills["benchmark"].scope == "project"
    assert "Run performance benchmarks on tests/" in skills["benchmark"].render("tests/")
