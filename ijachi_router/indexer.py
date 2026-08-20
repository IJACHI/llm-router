"""Workspace Symbol Indexer for ijachi-code.

Extracts functions, classes, methods, imports, and exports across project code files
into a lightweight symbol map cache (~/.ijachi-llmr/symbols.json).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

_CACHE_DIR = Path.home() / ".ijachi-llmr"
_SYMBOLS_CACHE_FILE = _CACHE_DIR / "symbols.json"


@dataclass
class SymbolInfo:
    name: str
    kind: str  # function | class | method | import
    file_path: str
    line_number: int


class WorkspaceIndexer:
    """Scans and indexes workspace code files into a fast symbol map."""

    SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java", ".cpp", ".c", ".h"}

    def __init__(self, root_dir: Path | str | None = None):
        self.root_dir = Path(root_dir or Path.cwd()).resolve()

    def scan_file(self, file_path: Path) -> list[SymbolInfo]:
        symbols: list[SymbolInfo] = []
        rel_path = str(file_path.relative_to(self.root_dir))
        ext = file_path.suffix.lower()

        try:
            lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return symbols

        for i, line in enumerate(lines, start=1):
            line_str = line.strip()

            # Python
            if ext == ".py":
                m_func = re.match(r"^\s*def\s+([a-zA-Z0-9_]+)\s*\(", line)
                if m_func:
                    symbols.append(SymbolInfo(name=m_func.group(1), kind="function", file_path=rel_path, line_number=i))
                m_cls = re.match(r"^\s*class\s+([a-zA-Z0-9_]+)", line)
                if m_cls:
                    symbols.append(SymbolInfo(name=m_cls.group(1), kind="class", file_path=rel_path, line_number=i))

            # JS / TS
            elif ext in {".js", ".ts", ".jsx", ".tsx"}:
                m_func = re.match(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_]+)", line)
                if m_func:
                    symbols.append(SymbolInfo(name=m_func.group(1), kind="function", file_path=rel_path, line_number=i))
                m_cls = re.match(r"^\s*(?:export\s+)?class\s+([a-zA-Z0-9_]+)", line)
                if m_cls:
                    symbols.append(SymbolInfo(name=m_cls.group(1), kind="class", file_path=rel_path, line_number=i))

            # Go / Rust / Java / C++
            elif ext in {".go", ".rs", ".java", ".cpp", ".c", ".h"}:
                m_func = re.match(r"^\s*(?:pub\s+)?(?:fn|func|void|int|auto|def)\s+([a-zA-Z0-9_]+)\s*\(", line)
                if m_func:
                    symbols.append(SymbolInfo(name=m_func.group(1), kind="function", file_path=rel_path, line_number=i))
                m_cls = re.match(r"^\s*(?:pub\s+)?(?:struct|class|type|interface)\s+([a-zA-Z0-9_]+)", line)
                if m_cls:
                    symbols.append(SymbolInfo(name=m_cls.group(1), kind="class", file_path=rel_path, line_number=i))

        return symbols

    def index_workspace(self) -> list[SymbolInfo]:
        all_symbols: list[SymbolInfo] = []
        for p in self.root_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                if any(part.startswith(".") or part in {"node_modules", "venv", ".venv", "dist", "build"} for part in p.parts):
                    continue
                all_symbols.extend(self.scan_file(p))

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = [asdict(s) for s in all_symbols]
        _SYMBOLS_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return all_symbols

    def get_summary(self) -> str:
        if not _SYMBOLS_CACHE_FILE.exists():
            symbols = self.index_workspace()
        else:
            try:
                data = json.loads(_SYMBOLS_CACHE_FILE.read_text(encoding="utf-8"))
                symbols = [SymbolInfo(**item) for item in data]
            except Exception:
                symbols = self.index_workspace()

        if not symbols:
            return "No workspace symbols found."

        summary_lines = [f"Workspace Symbol Index ({len(symbols)} symbols):"]
        for s in symbols[:50]:
            summary_lines.append(f"  • [{s.kind}] {s.name} -> {s.file_path}:{s.line_number}")
        if len(symbols) > 50:
            summary_lines.append(f"  ... and {len(symbols) - 50} more symbols.")

        return "\n".join(summary_lines)
