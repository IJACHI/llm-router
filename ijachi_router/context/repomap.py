"""Repo map: a compact, signature-level outline of a codebase.

Gives the model "where things are" without reading every file. Python is parsed with ``ast``;
other common languages use signature patterns. Results are cached per file by mtime.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".next", "target",
             ".mypy_cache", ".pytest_cache", ".tox", ".idea", ".vscode", "coverage", ".ijachi"}
_CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".swift"}
_MAX_FILE_BYTES = 400_000

_PATTERNS: dict[str, list[re.Pattern]] = {
    "js": [
        re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(([^)]*)\)"),
        re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)"),
        re.compile(r"^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*(?::[^=]+)?=>"),
        re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)"),
    ],
    "go": [re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(([^)]*)\)"), re.compile(r"^type\s+([A-Za-z_]\w*)\s+(?:struct|interface)")],
    "rs": [re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)\s*(?:<[^>]*>)?\(([^)]*)\)"),
           re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|impl)\s+([A-Za-z_][\w<>, ]*)")],
    "java": [re.compile(r"^\s*(?:public|protected|private|static|final|abstract|\s)*(?:class|interface|enum|record)\s+([A-Za-z_]\w*)"),
             re.compile(r"^\s*(?:public|protected|private|static|final|synchronized|abstract|\s)+[\w<>\[\], ?]+\s+([a-z]\w*)\s*\(([^)]*)\)\s*(?:throws [\w., ]+)?\s*\{")],
    "rb": [re.compile(r"^\s*(?:class|module)\s+([A-Z][\w:]*)"), re.compile(r"^\s*def\s+((?:self\.)?[a-z_]\w*[?!=]?)\s*(\(([^)]*)\))?")],
}
_EXT_LANG = {".js": "js", ".jsx": "js", ".ts": "js", ".tsx": "js", ".mjs": "js", ".go": "go", ".rs": "rs",
             ".java": "java", ".kt": "java", ".cs": "java", ".rb": "rb"}

_cache: dict[str, tuple[float, list[str]]] = {}


def _py_symbols(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ["(syntax error: could not parse)"]
    out: list[str] = []

    def args_of(fn) -> str:
        names = [a.arg for a in fn.args.posonlyargs + fn.args.args]
        if fn.args.vararg:
            names.append("*" + fn.args.vararg.arg)
        names += [a.arg for a in fn.args.kwonlyargs]
        if fn.args.kwarg:
            names.append("**" + fn.args.kwarg.arg)
        return ", ".join(names)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            out.append(f"{prefix} {node.name}({args_of(node)})")
        elif isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            out.append(f"class {node.name}" + (f"({bases})" if bases else ""))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and (not sub.name.startswith("_") or sub.name == "__init__"):
                    out.append(f"    def {sub.name}({args_of(sub)})")
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.isupper():
                out.append(f"{name} = ...")
    return out


def _regex_symbols(text: str, lang: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        if len(line) > 300:
            continue
        for pat in _PATTERNS[lang]:
            m = pat.match(line)
            if m:
                out.append(line.strip().rstrip("{").strip()[:160])
                break
    return out


def file_symbols(path: Path) -> list[str]:
    try:
        st = path.stat()
    except OSError:
        return []
    key = str(path)
    hit = _cache.get(key)
    if hit and hit[0] == st.st_mtime:
        return hit[1]
    if st.st_size > _MAX_FILE_BYTES:
        syms = ["(large file: not mapped)"]
    else:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        if path.suffix == ".py":
            syms = _py_symbols(text)
        elif path.suffix in _EXT_LANG:
            syms = _regex_symbols(text, _EXT_LANG[path.suffix])
        else:
            syms = []
    _cache[key] = (st.st_mtime, syms)
    return syms


def iter_source_files(root: Path, start: Path | None = None, limit: int = 5000):
    base = start or root
    count = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix in _CODE_EXT:
                yield p
                count += 1
                if count >= limit:
                    return


def build_repo_map(root: Path, start: Path | None = None, max_chars: int = 12_000) -> str:
    """Outline of source files under *start* (default: the whole workspace), capped in size."""
    root = root.resolve()
    start = start.resolve() if start else None
    lines: list[str] = []
    used = 0
    omitted = 0
    for p in iter_source_files(root, start):
        syms = file_symbols(p)
        rel = p.relative_to(root)
        block = [f"{rel}:"] + [f"  {s}" for s in syms[:40]]
        if len(syms) > 40:
            block.append(f"  ... (+{len(syms) - 40} more)")
        size = sum(len(b) + 1 for b in block)
        if used + size > max_chars:
            omitted += 1
            continue
        lines.extend(block)
        used += size
    if omitted:
        lines.append(f"... {omitted} more files not shown (use RepoMap with a subdirectory path)")
    return "\n".join(lines) if lines else "(no source files found)"
