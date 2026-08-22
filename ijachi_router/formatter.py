"""Code Formatter & Style Enforcement Engine for ijachi-code.

Responsibilities
----------------
1. Detect language from file extension.
2. Apply the configured style guide (pep8/google/airbnb/standard/prettier).
3. Auto-inject missing docstring / JSDoc comment headers.
4. Run a post-write lint gate and surface warnings.
5. Provide a style instruction block to prepend to LLM code-generation prompts.

Supported languages & tools
----------------------------
- Python  : black + isort (subprocess), fallback: indent normalization
- JS/TS   : prettier (subprocess), fallback: whitespace trim
- Go      : gofmt (subprocess)
- Rust    : rustfmt (subprocess, best-effort)
- Other   : trailing-whitespace trim + final-newline guarantee
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FormatResult:
    """Result of a format + lint pass on a single file."""

    path: str
    """Absolute path of the formatted file."""
    changed: bool
    """True if the formatter modified the file content."""
    formatter_used: str
    """Name of the formatter that was applied (e.g. 'black', 'prettier')."""
    lint_warnings: list[str] = field(default_factory=list)
    """Lint warnings discovered after formatting."""
    errors: list[str] = field(default_factory=list)
    """Hard errors that prevented formatting."""

    def summary(self) -> str:
        """Return a human-readable one-line summary of the format result."""
        status = "reformatted" if self.changed else "already clean"
        warn_str = f"  {len(self.lint_warnings)} lint warning(s)" if self.lint_warnings else ""
        err_str = f"  {len(self.errors)} error(s)" if self.errors else ""
        return f"[{self.formatter_used}] {self.path} — {status}{warn_str}{err_str}"

    def is_ok(self) -> bool:
        """Return True if no hard errors occurred."""
        return not self.errors


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

#: Maps file extension → (language name, default formatter key)
_EXT_MAP: dict[str, tuple[str, str]] = {
    ".py": ("python", "pep8"),
    ".pyi": ("python", "pep8"),
    ".js": ("javascript", "prettier"),
    ".jsx": ("javascript", "prettier"),
    ".ts": ("typescript", "prettier"),
    ".tsx": ("typescript", "prettier"),
    ".mjs": ("javascript", "prettier"),
    ".go": ("go", "gofmt"),
    ".rs": ("rust", "rustfmt"),
    ".java": ("java", "google-java-format"),
    ".sh": ("shell", "shfmt"),
    ".yaml": ("yaml", "prettier"),
    ".yml": ("yaml", "prettier"),
    ".json": ("json", "prettier"),
    ".md": ("markdown", "prettier"),
    ".css": ("css", "prettier"),
    ".html": ("html", "prettier"),
}


def _detect_language(path: str | Path) -> tuple[str, str]:
    """Return (language, default_formatter) for *path*, or ('unknown', 'none')."""
    ext = Path(path).suffix.lower()
    return _EXT_MAP.get(ext, ("unknown", "none"))


# ---------------------------------------------------------------------------
# Comment / docstring injection helpers
# ---------------------------------------------------------------------------

def _needs_python_module_docstring(content: str) -> bool:
    """Return True if content has no module-level docstring."""
    stripped = content.lstrip()
    return not (stripped.startswith('"""') or stripped.startswith("'''"))


def _inject_python_docstring(content: str, filename: str) -> str:
    """Prepend a module-level docstring if one is missing."""
    if not _needs_python_module_docstring(content):
        return content
    module_name = Path(filename).stem
    docstring = f'"""{module_name} — [module purpose here].\n\nTODO: Add module description.\n"""\n\n'
    return docstring + content


def _inject_jsdoc_for_exports(content: str) -> str:
    """Add a JSDoc comment above each exported function/class that lacks one."""
    pattern = re.compile(
        r"^(export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var)\s+\w+)",
        re.MULTILINE,
    )

    def add_jsdoc(m: re.Match) -> str:
        # Check if the preceding non-empty line is already a JSDoc closer
        start = m.start()
        before = content[:start].rstrip()
        if before.endswith("*/"):
            return m.group(0)
        name_match = re.search(r"(?:function|class|const|let|var)\s+(\w+)", m.group(0))
        name = name_match.group(1) if name_match else "symbol"
        return (
            f"/**\n"
            f" * {name} — [description here].\n"
            f" *\n"
            f" * @param {{*}} - TODO: document parameters\n"
            f" * @returns {{*}} - TODO: document return value\n"
            f" */\n"
            f"{m.group(0)}"
        )

    return pattern.sub(add_jsdoc, content)


def _stub_todo_branches(content: str, language: str) -> str:
    """Insert TODO stubs inside empty function/method bodies."""
    if language == "python":
        # Replace bare `pass` in function bodies with a TODO comment + pass
        pattern = re.compile(
            r"(def \w+\([^)]*\)\s*(?:->[^:]+)?:\s*\n)(\s+)(pass\b)", re.MULTILINE
        )
        return pattern.sub(r"\1\2# TODO: Implement\n\2pass", content)
    if language in ("javascript", "typescript"):
        # Replace empty arrow/regular function bodies
        pattern = re.compile(r"(=>|function\s*\w*\s*\([^)]*\))\s*\{\s*\}", re.MULTILINE)
        return pattern.sub(r"\1 {\n  // TODO: Implement\n}", content)
    return content


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_cmd(
    cmd: list[str],
    input_text: str | None = None,
    cwd: str | None = None,
) -> tuple[bool, str, str]:
    """Run *cmd* and return (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except FileNotFoundError:
        return False, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out: {' '.join(cmd)}"
    except Exception as exc:
        return False, "", str(exc)


def _tool_available(name: str) -> bool:
    """Return True if *name* is on PATH."""
    ok, _, _ = _run_cmd(["which", name])
    return ok


# ---------------------------------------------------------------------------
# Per-language formatters
# ---------------------------------------------------------------------------

def _format_python(path: Path, style_guide: str) -> tuple[str, str]:
    """Format a Python file with isort + black/autopep8. Returns (tool_used, error)."""
    used: list[str] = []
    errors: list[str] = []

    if _tool_available("isort"):
        ok, _, err = _run_cmd(["isort", "--profile", "black", str(path)])
        if ok:
            used.append("isort")
        elif err:
            errors.append(f"isort: {err.strip()}")

    if style_guide in ("pep8", "google", "black") and _tool_available("black"):
        line_len = "88" if style_guide == "black" else "79"
        ok, _, err = _run_cmd(["black", f"--line-length={line_len}", str(path)])
        if ok:
            used.append("black")
# ---------------------------------------------------------------------------
# Pure-Python Beautifiers (Fallback when CLI formatters are not installed)
# ---------------------------------------------------------------------------

def _beautify_json(content: str) -> str:
    """Format JSON content with 2-space indentation."""
    import json
    try:
        data = json.loads(content)
        return json.dumps(data, indent=2) + "\n"
    except Exception:
        return content


def _beautify_css(css_text: str, base_indent: int = 0) -> str:
    """Format CSS code with clean indentation, expanded rules, and aligned properties.

    Args:
        css_text: Raw CSS text (standalone or inside a <style> block).
        base_indent: Indentation spaces to prepend to every line (for embedded CSS).

    Returns:
        Beautifully formatted CSS string.
    """
    lines: list[str] = []
    indent_level = base_indent
    # Normalize newlines and semicolons
    cleaned = re.sub(r"/\*.*?\*/", lambda m: m.group(0), css_text, flags=re.DOTALL)
    
    # Split by blocks or statements
    tokens = re.split(r"([{}])", cleaned)
    buffer = ""
    
    for token in tokens:
        token_str = token.strip()
        if not token_str:
            continue
        if token_str == "{":
            # Opening rule or media query
            selector = buffer.strip()
            indent = " " * indent_level
            if selector:
                lines.append(f"{indent}{selector} {{")
            else:
                lines.append(f"{indent}{{")
            indent_level += 2
            buffer = ""
        elif token_str == "}":
            # Flush any remaining properties before closing
            if buffer.strip():
                for prop in buffer.split(";"):
                    p = prop.strip()
                    if p:
                        if ":" in p:
                            k, v = p.split(":", 1)
                            p = f"{k.strip()}: {v.strip()}"
                        lines.append(f"{' ' * indent_level}{p};")
                buffer = ""
            indent_level = max(base_indent, indent_level - 2)
            lines.append(f"{' ' * indent_level}}}")
        else:
            # Property declarations or selectors
            if indent_level > base_indent:
                # Inside a rule: split on semicolons
                props = token.split(";")
                for prop in props[:-1]:
                    p = prop.strip()
                    if p:
                        if ":" in p:
                            k, v = p.split(":", 1)
                            p = f"{k.strip()}: {v.strip()}"
                        lines.append(f"{' ' * indent_level}{p};")
                buffer = props[-1]  # Partial or next selector
            else:
                buffer += " " + token_str

    if buffer.strip():
        lines.append(f"{' ' * indent_level}{buffer.strip()}")

    # Clean up multiple empty lines
    formatted = "\n".join(lines)
    formatted = re.sub(r"\n{3,}", "\n\n", formatted).strip()
    return formatted + "\n"


_HTML_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr", "!doctype",
}


def _beautify_html(html_text: str) -> str:
    """Format HTML with structured hierarchy, indented nested tags, and embedded CSS/JS formatting.

    Args:
        html_text: Raw HTML string (e.g. from LLM generation).

    Returns:
        Properly structured, beautifully indented HTML document.
    """
    raw = html_text.strip()

    # Extract and format <style> blocks
    style_blocks: list[str] = []
    def _stash_style(m: re.Match) -> str:
        tag_open = m.group(1)
        css_body = m.group(2)
        tag_close = m.group(3)
        formatted_css = _beautify_css(css_body, base_indent=6)
        formatted_block = f"{tag_open}\n{formatted_css}    {tag_close}"
        idx = len(style_blocks)
        style_blocks.append(formatted_block)
        return f"__STYLE_BLOCK_{idx}__"

    raw = re.sub(r"(<style[^>]*>)(.*?)(</style>)", _stash_style, raw, flags=re.DOTALL | re.IGNORECASE)

    # Walk HTML tokens and build structured indentation
    tokens = re.split(r"(<[^>]+>|__STYLE_BLOCK_\d+__)", raw)
    lines: list[str] = []
    indent_level = 0

    for token in tokens:
        t = token.strip()
        if not t:
            continue

        if t.startswith("__STYLE_BLOCK_") and t.endswith("__"):
            idx = int(t.replace("__STYLE_BLOCK_", "").replace("__", ""))
            block = style_blocks[idx]
            lines.append(f"{' ' * (indent_level * 2)}{block}")
            continue

        if t.startswith("<!--"):
            # HTML comment
            lines.append(f"{' ' * (indent_level * 2)}{t}")
            continue

        if t.startswith("</"):
            # Closing tag: decrease indent first
            indent_level = max(0, indent_level - 1)
            lines.append(f"{' ' * (indent_level * 2)}{t}")
        elif t.startswith("<"):
            # Opening tag or void tag
            tag_name = re.sub(r"[^a-zA-Z0-9_!-]", "", t[1:].split()[0]).lower()
            is_void = tag_name in _HTML_VOID_TAGS or t.endswith("/>") or tag_name.startswith("!")
            lines.append(f"{' ' * (indent_level * 2)}{t}")
            if not is_void:
                indent_level += 1
        else:
            # Text content inside tags
            lines.append(f"{' ' * (indent_level * 2)}{t}")

    # Compact inline elements (e.g. <title>Text</title> or <span>Text</span> on one line)
    joined = "\n".join(lines)
    joined = re.sub(
        r"(<(?P<tag>title|h[1-6]|span|strong|em|b|i|a|p|button|label)[^>]*>)\s*\n\s*([^<\n]+)\s*\n\s*(</(?P=tag)>)",
        r"\1\3\4",
        joined,
    )
    # Ensure final newline and no triple blank lines
    joined = re.sub(r"\n{3,}", "\n\n", joined).strip()
    return joined + "\n"


# ---------------------------------------------------------------------------
# Per-language formatters
# ---------------------------------------------------------------------------

def _format_python(path: Path, style_guide: str) -> tuple[str, str]:
    """Format a Python file with isort + black/autopep8. Returns (tool_used, error)."""
    used: list[str] = []
    errors: list[str] = []

    if _tool_available("isort"):
        ok, _, err = _run_cmd(["isort", "--profile", "black", str(path)])
        if ok:
            used.append("isort")
        elif err:
            errors.append(f"isort: {err.strip()}")

    if style_guide in ("pep8", "google", "black") and _tool_available("black"):
        line_len = "88" if style_guide == "black" else "79"
        ok, _, err = _run_cmd(["black", f"--line-length={line_len}", str(path)])
        if ok:
            used.append("black")
        elif err and "reformatted" not in err:
            errors.append(f"black: {err.strip()}")
    elif _tool_available("autopep8"):
        _run_cmd(["autopep8", "--in-place", str(path)])
        used.append("autopep8")

    return ", ".join(used) or "python-basic", "; ".join(errors)


def _format_js_ts(path: Path, style_guide: str) -> tuple[str, str]:
    """Format a JS/TS file using prettier, falling back to clean indentation."""
    parser = "typescript" if path.suffix in (".ts", ".tsx") else "babel"
    if _tool_available("prettier"):
        ok, _, err = _run_cmd([
            "prettier", "--write",
            f"--parser={parser}",
            "--tab-width=2",
            "--trailing-comma=all",
            str(path),
        ])
        if ok:
            return "prettier", ""

    # Fallback: basic whitespace normalization + final newline
    content = path.read_text(encoding="utf-8")
    normalized = "\n".join(line.rstrip() for line in content.splitlines())
    if not normalized.endswith("\n"):
        normalized += "\n"
    path.write_text(normalized, encoding="utf-8")
    return "js-beautify", ""


def _format_html(path: Path) -> tuple[str, str]:
    """Format an HTML file using built-in HTML & CSS beautifier or Prettier."""
    if _tool_available("prettier"):
        ok, _, err = _run_cmd(["prettier", "--write", "--parser=html", str(path)])
        if ok:
            return "prettier", ""

    content = path.read_text(encoding="utf-8", errors="replace")
    formatted = _beautify_html(content)
    path.write_text(formatted, encoding="utf-8")
    return "html-beautifier", ""


def _format_css(path: Path) -> tuple[str, str]:
    """Format a CSS file using built-in CSS beautifier or Prettier."""
    if _tool_available("prettier"):
        ok, _, err = _run_cmd(["prettier", "--write", "--parser=css", str(path)])
        if ok:
            return "prettier", ""

    content = path.read_text(encoding="utf-8", errors="replace")
    formatted = _beautify_css(content)
    path.write_text(formatted, encoding="utf-8")
    return "css-beautifier", ""


def _format_json(path: Path) -> tuple[str, str]:
    """Format a JSON file using json.dumps indent=2."""
    content = path.read_text(encoding="utf-8", errors="replace")
    formatted = _beautify_json(content)
    path.write_text(formatted, encoding="utf-8")
    return "json-beautifier", ""


def _format_go(path: Path) -> tuple[str, str]:
    """Format a Go file using gofmt."""
    if _tool_available("gofmt"):
        ok, formatted, err = _run_cmd(["gofmt", str(path)])
        if ok and formatted:
            path.write_text(formatted, encoding="utf-8")
        return "gofmt", "" if ok else err.strip()
    return "none", "gofmt not available"


def _format_rust(path: Path) -> tuple[str, str]:
    """Format a Rust file using rustfmt."""
    if _tool_available("rustfmt"):
        ok, _, err = _run_cmd(["rustfmt", str(path)])
        return "rustfmt", "" if ok else err.strip()
    return "none", "rustfmt not available"


def _format_generic(path: Path) -> tuple[str, str]:
    """Basic formatter: trailing whitespace trim + final newline guarantee."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        normalized = "\n".join(line.rstrip() for line in content.splitlines())
        if not normalized.endswith("\n"):
            normalized += "\n"
        path.write_text(normalized, encoding="utf-8")
        return "whitespace-trim", ""
    except Exception as exc:
        return "none", str(exc)


# ---------------------------------------------------------------------------
# Lint runners
# ---------------------------------------------------------------------------

def _lint_python(path: Path) -> list[str]:
    """Run flake8 on *path* and return warning strings."""
    if not _tool_available("flake8"):
        return []
    _, out, _ = _run_cmd(["flake8", "--max-line-length=100", str(path)])
    return [line.strip() for line in out.splitlines() if line.strip()]


def _lint_js_ts(path: Path) -> list[str]:
    """Run eslint on *path* and return warning strings (capped at 20)."""
    if not _tool_available("eslint"):
        return []
    _, out, err = _run_cmd(["eslint", "--format=compact", str(path)])
    lines = [l.strip() for l in (out + err).splitlines() if l.strip()]
    return lines[:20]


def _run_lint(path: Path, language: str) -> list[str]:
    """Dispatch to the correct linter for *language*."""
    if language == "python":
        return _lint_python(path)
    if language in ("javascript", "typescript"):
        return _lint_js_ts(path)
    return []


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class CodeFormatter:
    """Language-aware code formatter, style enforcer, and lint gate.

    Usage
    -----
    ::

        formatter = CodeFormatter(style_guide="pep8", auto_format=True, require_comments=True)
        result = formatter.format("/path/to/file.py")
        if result.lint_warnings:
            print(result.summary())
    """

    #: Maps style guide key → human-readable description shown in LLM prompts
    STYLE_DESCRIPTIONS: ClassVar[dict[str, str]] = {
        "pep8":     "PEP 8 (Python official style guide, 79-char lines)",
        "google":   "Google Python Style Guide (black-formatted, 80-char lines)",
        "black":    "Black (opinionated Python formatter, 88-char lines)",
        "airbnb":   "Airbnb JavaScript Style Guide (2-space indent, no semicolons)",
        "standard": "Standard JS (no semicolons, 2-space indent)",
        "prettier": "Prettier (opinionated JS/TS/JSON/YAML formatter)",
    }

    def __init__(
        self,
        style_guide: str = "pep8",
        auto_format: bool = True,
        require_comments: bool = True,
    ) -> None:
        """Initialise the formatter.

        Args:
            style_guide: Style guide key to apply. See ``STYLE_DESCRIPTIONS``.
            auto_format: If True, actually run the formatter tool on disk.
            require_comments: If True, inject missing docstrings/JSDoc headers.
        """
        self.style_guide = style_guide
        self.auto_format = auto_format
        self.require_comments = require_comments

    def format(self, path: str | Path) -> FormatResult:
        """Format and lint the file at *path*.

        Reads the file, optionally injects missing comment headers, runs the
        language-appropriate formatter, then lints and returns a FormatResult.

        Does NOT raise — all errors are captured in the result object.

        Args:
            path: Absolute or relative path to the source file.

        Returns:
            :class:`FormatResult` describing what changed and any lint issues.
        """
        path = Path(path)
        language, _ = _detect_language(path)

        if language == "unknown":
            return FormatResult(
                path=str(path), changed=False, formatter_used="none",
                errors=["Unknown file type — skipping formatter"],
            )

        try:
            original_content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return FormatResult(
                path=str(path), changed=False, formatter_used="none",
                errors=[f"Cannot read file: {exc}"],
            )

        # Step 1 — inject missing comment headers before running the formatter
        if self.require_comments:
            modified = original_content
            if language == "python":
                modified = _inject_python_docstring(modified, str(path))
                modified = _stub_todo_branches(modified, language)
            elif language in ("javascript", "typescript"):
                modified = _inject_jsdoc_for_exports(modified)
                modified = _stub_todo_branches(modified, language)
            if modified != original_content:
                try:
                    path.write_text(modified, encoding="utf-8")
                    original_content = modified
                except Exception:
                    pass  # Non-fatal: proceed to formatter regardless

        # Step 2 — run the language-appropriate formatter
        formatter_used = "none"
        fmt_error = ""
        if self.auto_format:
            if language == "python":
                formatter_used, fmt_error = _format_python(path, self.style_guide)
            elif language in ("javascript", "typescript"):
                formatter_used, fmt_error = _format_js_ts(path, self.style_guide)
            elif language == "html":
                formatter_used, fmt_error = _format_html(path)
            elif language == "css":
                formatter_used, fmt_error = _format_css(path)
            elif language == "json":
                formatter_used, fmt_error = _format_json(path)
            elif language == "go":
                formatter_used, fmt_error = _format_go(path)
            elif language == "rust":
                formatter_used, fmt_error = _format_rust(path)
            else:
                formatter_used, fmt_error = _format_generic(path)

        # Step 3 — detect whether the file actually changed
        try:
            new_content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            new_content = original_content
        changed = new_content != original_content

        # Step 4 — lint gate
        lint_warnings = _run_lint(path, language)

        return FormatResult(
            path=str(path),
            changed=changed,
            formatter_used=formatter_used,
            lint_warnings=lint_warnings,
            errors=[fmt_error] if fmt_error else [],
        )

    def format_content(self, content: str, filename: str) -> str:
        """Format *content* string without writing to the real path.

        Writes to a temp file, formats in-place, reads back.
        Useful for pre-processing content before a write_file tool call.

        Args:
            content: Source code string to format.
            filename: Reference filename used for language detection (not written).

        Returns:
            Formatted source code string (original if formatting fails).
        """
        ext = Path(filename).suffix
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=ext, delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        try:
            self.format(tmp_path)
            return tmp_path.read_text(encoding="utf-8")
        except Exception:
            return content
        finally:
            tmp_path.unlink(missing_ok=True)

    def get_style_prompt(self, language: str | None = None) -> str:
        """Return a style instruction block to prepend to LLM code-generation prompts.

        Args:
            language: Optional language hint (e.g. 'python', 'typescript').

        Returns:
            Multi-line string instructing the LLM to follow the configured style guide.
        """
        guide_desc = self.STYLE_DESCRIPTIONS.get(self.style_guide, self.style_guide)
        lang_hint = f" ({language})" if language else ""
        return (
            f"## Code Style & Quality Requirements{lang_hint}\n"
            f"- **Style guide**: {guide_desc}\n"
            f"- **Mandatory comments**: Every module, class, and public function/method "
            f"MUST have a docstring (Python) or JSDoc block (JS/TS) explaining its purpose, "
            f"parameters, and return value.\n"
            f"- **Inline comments**: Add inline `#` / `//` comments for non-obvious logic.\n"
            f"- **TODOs**: Mark unimplemented stubs with `# TODO: <description>` / `// TODO:`.\n"
            f"- **Naming**: Use descriptive, idiomatic names — no single-letter variables "
            f"outside loop counters.\n"
            f"- **Error handling**: Always include appropriate try/except or error-checking.\n"
            f"- **No magic numbers**: Extract literals into named constants.\n"
            f"- **Type hints**: Include type annotations for all function signatures.\n"
            f"\nGenerate clean, production-ready code that follows these requirements exactly.\n"
        )
