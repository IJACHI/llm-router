"""Git workflow helpers: isolated worktrees per task and pull-request creation.

    ijachi-code --worktree fix-login     # work in .ijachi/worktrees/fix-login on branch ijachi/fix-login
    ijachi-code pr                       # commit, push and open a PR (asks before each outward step)
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=120)
    if check and proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout).strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def repo_root(path: Path) -> Path:
    return Path(_git(path, "rev-parse", "--show-toplevel"))


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "task"


def create_worktree(path: Path, name: str) -> Path:
    """New branch ijachi/<name> checked out in <repo>/.ijachi/worktrees/<name> (reused if present)."""
    root = repo_root(path)
    slug = slugify(name)
    target = root / ".ijachi" / "worktrees" / slug
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    gi = root / ".ijachi" / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    if "worktrees/" not in lines:
        gi.write_text("\n".join([*lines, "worktrees/"]) + "\n")
    branch = f"ijachi/{slug}"
    exists = _git(root, "branch", "--list", branch)
    if exists:
        _git(root, "worktree", "add", str(target), branch)
    else:
        _git(root, "worktree", "add", "-b", branch, str(target), "HEAD")
    return target


def default_branch(root: Path) -> str:
    ref = _git(root, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False)
    if ref:
        return ref.rsplit("/", 1)[-1]
    for cand in ("main", "master"):
        if _git(root, "rev-parse", "--verify", "--quiet", cand, check=False):
            return cand
    return "main"


def status(root: Path) -> dict:
    return {
        "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "default": default_branch(root),
        "dirty": bool(_git(root, "status", "--porcelain")),
        "has_remote": bool(_git(root, "remote", check=False)),
        "gh": shutil.which("gh") is not None,
    }


def diff_for_message(root: Path, staged: bool = True, limit: int = 12_000) -> str:
    args = ["diff", "--staged"] if staged else ["diff", "HEAD"]
    stat = _git(root, *args, "--stat", check=False)
    body = _git(root, *args, check=False)
    return (stat + "\n\n" + body)[:limit]


def ensure_feature_branch(root: Path, title: str) -> str:
    st = status(root)
    if st["branch"] in (st["default"], "HEAD"):
        branch = f"ijachi/{slugify(title)}"
        _git(root, "checkout", "-b", branch)
        return branch
    return st["branch"]


def commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)


def push(root: Path, branch: str) -> None:
    _git(root, "push", "-u", "origin", branch)


def create_pr(root: Path, title: str, body: str, base: str, draft: bool = True) -> str:
    cmd = ["gh", "pr", "create", "--title", title, "--body", body, "--base", base]
    if draft:
        cmd.append("--draft")
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout).strip())
    return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
