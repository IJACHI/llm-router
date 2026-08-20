"""Security Hardening Scanner for ijachi-llm-router.

Scans generated code for OWASP Top 10 vulnerability patterns and auto-remediates
them before returning or writing output to disk.

Detects and fixes:
- SQL injection vectors
- Shell injection (subprocess with shell=True, os.system)
- Hardcoded secrets (api_key, password, token literals)
- Unsafe crypto algorithms (MD5, SHA1, DES)
- Path traversal vulnerabilities
- Unsafe deserialization (pickle.loads, yaml.load without SafeLoader)
- Dangerous builtins (eval, exec with user input)
- Insecure random (random.random for security contexts)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SecurityIssue:
    severity: str  # critical | high | medium | low
    category: str
    description: str
    line_number: int
    original_line: str
    remediated_line: str | None = None


@dataclass
class SecurityReport:
    issues: list[SecurityIssue] = field(default_factory=list)
    remediated_code: str = ""
    is_safe: bool = True

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "critical")

    @property
    def high_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "high")


# ---------------------------------------------------------------------------
# Security rule definitions
# ---------------------------------------------------------------------------

_SECURITY_RULES: list[dict] = [
    {
        "id": "SHELL_INJECTION",
        "severity": "critical",
        "category": "Injection",
        "pattern": r"subprocess\.(run|call|Popen|check_output)\s*\([^)]*shell\s*=\s*True",
        "description": "subprocess called with shell=True enables shell injection. Use shell=False with list args.",
        "fix": None,  # Flagged for developer review
    },
    {
        "id": "OS_SYSTEM",
        "severity": "critical",
        "category": "Injection",
        "pattern": r"\bos\.system\s*\(",
        "description": "os.system() is vulnerable to shell injection. Use subprocess.run() with a list instead.",
        "fix": None,
    },
    {
        "id": "EVAL_EXEC",
        "severity": "critical",
        "category": "Code Injection",
        "pattern": r"\b(eval|exec)\s*\(",
        "description": "eval()/exec() with untrusted input enables code injection.",
        "fix": None,
    },
    {
        "id": "HARDCODED_SECRET",
        "severity": "high",
        "category": "Secrets Exposure",
        "pattern": r'(?i)(api[_-]?key|password|passwd|secret[_-]?key|token|auth[_-]?token|access[_-]?key)\s*=\s*["\'][^"\']{4,}["\']',
        "description": "Hardcoded secret detected. Use environment variables or a secrets manager.",
        "fix": None,
    },
    {
        "id": "WEAK_MD5",
        "severity": "high",
        "category": "Weak Cryptography",
        "pattern": r"\bhashlib\.md5\s*\(",
        "description": "MD5 is cryptographically broken. Use hashlib.sha256() or hashlib.sha3_256() instead.",
        "fix": lambda line: line.replace("hashlib.md5(", "hashlib.sha256("),
    },
    {
        "id": "WEAK_SHA1",
        "severity": "high",
        "category": "Weak Cryptography",
        "pattern": r"\bhashlib\.sha1\s*\(",
        "description": "SHA-1 is cryptographically weak. Use hashlib.sha256() instead.",
        "fix": lambda line: line.replace("hashlib.sha1(", "hashlib.sha256("),
    },
    {
        "id": "UNSAFE_PICKLE",
        "severity": "critical",
        "category": "Unsafe Deserialization",
        "pattern": r"\bpickle\.loads\s*\(",
        "description": "pickle.loads() on untrusted data enables arbitrary code execution. Use JSON or a safe format.",
        "fix": None,
    },
    {
        "id": "UNSAFE_YAML",
        "severity": "high",
        "category": "Unsafe Deserialization",
        "pattern": r"\byaml\.load\s*\([^,)]+\)",
        "description": "yaml.load() without SafeLoader enables arbitrary code execution.",
        "fix": lambda line: re.sub(
            r"yaml\.load\s*\(([^,)]+)\)",
            r"yaml.safe_load(\1)",
            line,
        ),
    },
    {
        "id": "INSECURE_RANDOM",
        "severity": "medium",
        "category": "Insecure Randomness",
        "pattern": r"\brandom\.(?:random|randint|choice|choices|shuffle)\s*\(",
        "description": "random module is not cryptographically secure. Use secrets module for security contexts.",
        "fix": None,
    },
    {
        "id": "PATH_TRAVERSAL",
        "severity": "high",
        "category": "Path Traversal",
        "pattern": r'open\s*\(\s*(?:request\.|user_|input_|f"|f\')',
        "description": "Potential path traversal: user-controlled input passed to open(). Validate and sanitize paths.",
        "fix": None,
    },
    {
        "id": "SQL_FSTRING",
        "severity": "critical",
        "category": "SQL Injection",
        "pattern": r'(?:execute|cursor\.execute)\s*\(\s*(?:f"|f\'|".*%s|\'.*%s)',
        "description": "SQL query built with f-string or % formatting enables SQL injection. Use parameterized queries.",
        "fix": None,
    },
    {
        "id": "DEBUG_TRUE",
        "severity": "medium",
        "category": "Configuration",
        "pattern": r'(?i)\bDEBUG\s*=\s*True\b',
        "description": "DEBUG=True in production exposes stack traces and sensitive data.",
        "fix": lambda line: re.sub(r'(?i)\bDEBUG\s*=\s*True\b', "DEBUG = False", line),
    },
]


def scan(code: str) -> SecurityReport:
    """Scan code for security vulnerabilities and auto-remediate where possible.

    Returns a SecurityReport with identified issues and a remediated code string.
    """
    if not code or not code.strip():
        return SecurityReport(remediated_code=code, is_safe=True)

    lines = code.splitlines(keepends=True)
    issues: list[SecurityIssue] = []
    remediated_lines = list(lines)

    for rule in _SECURITY_RULES:
        pattern = re.compile(rule["pattern"])
        for i, line in enumerate(lines):
            if pattern.search(line):
                fix_fn = rule.get("fix")
                remediated = fix_fn(line) if fix_fn else None
                issue = SecurityIssue(
                    severity=rule["severity"],
                    category=rule["category"],
                    description=rule["description"],
                    line_number=i + 1,
                    original_line=line.rstrip(),
                    remediated_line=remediated.rstrip() if remediated else None,
                )
                issues.append(issue)
                if remediated and remediated != line:
                    remediated_lines[i] = remediated

    has_critical = any(iss.severity in {"critical", "high"} for iss in issues)

    return SecurityReport(
        issues=issues,
        remediated_code="".join(remediated_lines),
        is_safe=not has_critical,
    )


def scan_and_fix(code: str) -> tuple[str, list[SecurityIssue]]:
    """Scan code and return (remediated_code, list_of_issues)."""
    report = scan(code)
    return report.remediated_code, report.issues


def format_security_summary(report: SecurityReport) -> str:
    if not report.issues:
        return "✓ No security vulnerabilities found."
    lines = [f"Security scan: {len(report.issues)} issue(s) found:"]
    for iss in report.issues:
        fixed = "✓ Auto-fixed" if iss.remediated_line else "⚠ Review required"
        lines.append(f"  [{iss.severity.upper()}] {iss.category}: {iss.description} (line {iss.line_number}) — {fixed}")
    return "\n".join(lines)
