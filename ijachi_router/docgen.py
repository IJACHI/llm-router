"""Automated Architecture & Diagram Generator for ijachi-code.

Uses workspace symbol maps to generate ARCHITECTURE.md with interactive
Mermaid.js sequence and class diagrams.
"""

from __future__ import annotations

from pathlib import Path
from ijachi_router.indexer import WorkspaceIndexer, SymbolInfo


class DocGenerator:
    """Auto-generates ARCHITECTURE.md with Mermaid.js diagrams from workspace symbols."""

    def __init__(self, root_dir: Path | str | None = None):
        self.root_dir = Path(root_dir or Path.cwd()).resolve()
        self.indexer = WorkspaceIndexer(root_dir=self.root_dir)

    def generate_architecture_md(self) -> str:
        symbols = self.indexer.index_workspace()
        classes = [s for s in symbols if s.kind == "class"]
        functions = [s for s in symbols if s.kind == "function"]

        md_lines = [
            f"# Architecture Overview - {self.root_dir.name}\n",
            "Auto-generated architecture documentation and structural diagrams powered by **`ijachi-code`**.\n",
            "## 📐 Class Diagram\n",
            "```mermaid",
            "classDiagram",
        ]

        for c in classes[:15]:
            md_lines.append(f"    class {c.name} {{")
            # Find methods defined in same file
            file_methods = [f for f in functions if f.file_path == c.file_path and abs(f.line_number - c.line_number) < 50]
            for m in file_methods[:5]:
                md_lines.append(f"        +{m.name}()")
            md_lines.append("    }")

        md_lines.extend([
            "```\n",
            "## 🔄 Component Interaction Sequence\n",
            "```mermaid",
            "sequenceDiagram",
            "    autonumber",
            "    actor User",
            "    participant CLI as ijachi-code CLI",
            "    participant Router as Router Engine",
            "    participant Provider as LLM Provider Matrix",
            "    User->>CLI: Prompt execution request",
            "    CLI->>Router: Classify & score models",
            "    Router->>Provider: Generate response + fallback",
            "    Provider-->>Router: Response payload",
            "    Router-->>CLI: Humanized & security-scanned output",
            "    CLI-->>User: Clean response",
            "```\n",
            "## 🗂️ Indexed Workspace Symbols\n",
            f"Total indexed symbols: **{len(symbols)}**\n",
        ])

        for s in symbols[:30]:
            md_lines.append(f"- **`{s.name}`** (`{s.kind}`) in `{s.file_path}:{s.line_number}`")

        content = "\n".join(md_lines) + "\n"
        output_file = self.root_dir / "ARCHITECTURE.md"
        output_file.write_text(content, encoding="utf-8")

        return f"Successfully generated ARCHITECTURE.md with Mermaid diagrams ({len(symbols)} symbols)."
