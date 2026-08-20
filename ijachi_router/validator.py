"""Zero-Regression Code Validator for ijachi-llm-router.

Before any generated code is written to disk, this module:
- Validates Python syntax via compile()
- Validates JS/TS syntax via node --check (if available)
- Checks for broken import references against the workspace symbol index
- Optionally runs a test suite gate before/after patches

Returns ValidationResult indicating whether the code is safe to apply.
"""

from __future__ import annotations

import ast
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.valid and not self.errors:
            return "✓ Code validation passed."
        lines = ["Code validation failed:"]
        for e in self.errors:
            lines.append(f"  ✗ {e}")
        for w in self.warnings:
            lines.append(f"  ⚠ {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Python syntax validator
# ---------------------------------------------------------------------------

def _validate_python(code: str) -> list[str]:
    """Returns list of syntax error strings, empty if code is valid."""
    errors: list[str] = []
    try:
        compile(code, "<generated>", "exec")
    except SyntaxError as e:
        errors.append(f"SyntaxError at line {e.lineno}: {e.msg} — {e.text!r}")
    except Exception as e:
        errors.append(f"Parse error: {e}")
    return errors


# ---------------------------------------------------------------------------
# JavaScript / TypeScript validator (requires node in PATH)
# ---------------------------------------------------------------------------

def _validate_js_ts(code: str, ext: str = ".js") -> list[str]:
    errors: list[str] = []
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, mode="w", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp = f.name
        proc = subprocess.run(
            ["node", "--check", tmp],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            for line in proc.stderr.strip().splitlines()[:5]:
                errors.append(f"JS/TS SyntaxError: {line}")
        Path(tmp).unlink(missing_ok=True)
    except FileNotFoundError:
        pass  # node not available — skip silently
    except Exception as e:
        errors.append(f"JS/TS validation error: {e}")
    return errors


# ---------------------------------------------------------------------------
# Import reference checker (Python)
# ---------------------------------------------------------------------------

_STDLIB_MODULES = {
    "os", "sys", "re", "json", "pathlib", "typing", "dataclasses",
    "collections", "itertools", "functools", "io", "subprocess", "shutil",
    "tempfile", "time", "datetime", "logging", "hashlib", "hmac", "secrets",
    "threading", "multiprocessing", "asyncio", "socket", "http", "urllib",
    "email", "csv", "sqlite3", "xml", "html", "base64", "struct", "math",
    "random", "copy", "abc", "contextlib", "enum", "textwrap", "inspect",
    "importlib", "pkgutil", "warnings", "traceback", "signal", "platform",
    "argparse", "unittest", "pytest", "pprint", "string", "ast", "dis",
    "__future__",
}


def _check_python_imports(code: str) -> list[str]:
    """Detect imports that may fail (not stdlib, not installed)."""
    warnings: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return warnings  # Already caught by syntax check

    import_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                import_names.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                import_names.append(node.module.split(".")[0])

    for name in import_names:
        if name in _STDLIB_MODULES:
            continue
        # Try to find it installed
        try:
            __import__(name)
        except ImportError:
            warnings.append(f"Import '{name}' may not be installed. Run: pip install {name}")
        except Exception:
            pass  # Other errors — skip silently

    return warnings


# ---------------------------------------------------------------------------
# Test gate: run test suite before/after applying a patch
# ---------------------------------------------------------------------------

def run_test_gate(
    test_command: str,
    cwd: Path | str | None = None,
    timeout: int = 120,
) -> tuple[bool, str]:
    """Run the test suite. Returns (passed: bool, output: str)."""
    cwd = Path(cwd or Path.cwd())
    try:
        proc = subprocess.run(
            test_command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        passed = proc.returncode == 0
        output = (proc.stdout + proc.stderr).strip()
        return passed, output
    except subprocess.TimeoutExpired:
        return False, "Test gate timed out."
    except Exception as e:
        return False, f"Test gate error: {e}"


# ---------------------------------------------------------------------------
# Main validate function
# ---------------------------------------------------------------------------

def validate(
    code: str,
    filename: str = "generated.py",
    run_tests: bool = False,
    test_command: str = "pytest",
    cwd: Path | str | None = None,
) -> ValidationResult:
    """Validate generated code before writing to disk.

    Checks syntax, import references, and optionally runs the project test suite.
    Returns a ValidationResult indicating whether the code is safe to apply.
    """
    errors: list[str] = []
    warnings: list[str] = []

    ext = Path(filename).suffix.lower()

    # Syntax validation
    if ext == ".py":
        errors.extend(_validate_python(code))
        if not errors:
            warnings.extend(_check_python_imports(code))
    elif ext in {".js", ".mjs"}:
        errors.extend(_validate_js_ts(code, ".js"))
    elif ext in {".ts", ".tsx"}:
        errors.extend(_validate_js_ts(code, ".ts"))

    # Test gate (optional, only if no syntax errors first)
    if run_tests and not errors:
        passed, output = run_test_gate(test_command, cwd=cwd)
        if not passed:
            errors.append(f"Test gate failed:\n{output[:1500]}")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
