"""GitHub PR Reviewer & Automated Release Manager for ijachi-code.

Performs automated architectural code reviews on Pull Requests and generates
CHANGELOG.md release notes for Git tags.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from ijachi_router.core import route


class GitHubAutomation:
    """Automates GitHub Pull Request reviews and release notes generation."""

    def __init__(self, root_dir: Path | str | None = None):
        self.root_dir = Path(root_dir or Path.cwd()).resolve()

    def review_pr(self, pr_number: int | str) -> str:
        """Fetch PR diff via gh CLI and route code review analysis."""
        try:
            diff_proc = subprocess.run(
                f"gh pr diff {pr_number}",
                shell=True,
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if diff_proc.returncode != 0 or not diff_proc.stdout.strip():
                return f"Error fetching PR #{pr_number} diff: {diff_proc.stderr.strip() or 'No diff found'}"

            diff_text = diff_proc.stdout.strip()[:4000]
            prompt = (
                f"Act as a Senior Code Reviewer. Analyze the following GitHub PR diff and provide:\n"
                f"1. Code Quality & Security Assessment\n"
                f"2. Architectural Suggestions\n"
                f"3. Approval Recommendation\n\n"
                f"Diff:\n{diff_text}"
            )

            res = route(prompt=prompt, priority="quality")
            review_comment = f"## 🤖 ijachi-code Automated PR Review (Model: {res.model})\n\n{res.text}"

            # Post review comment to GitHub PR
            comment_cmd = f"gh pr comment {pr_number} --body {json_escape(review_comment)}"
            subprocess.run(comment_cmd, shell=True, cwd=self.root_dir)

            return review_comment
        except Exception as e:
            return f"Error reviewing PR #{pr_number}: {e}"

    def generate_release_notes(self, tag_name: str) -> str:
        """Auto-generate CHANGELOG.md entry and release notes for a Git tag."""
        try:
            log_proc = subprocess.run(
                "git log -n 15 --oneline",
                shell=True,
                cwd=self.root_dir,
                capture_output=True,
                text=True,
            )
            git_log = log_proc.stdout.strip()

            prompt = (
                f"Generate a professional Markdown Release Changelog for release version {tag_name} "
                f"based on these recent commits:\n\n{git_log}"
            )

            res = route(prompt=prompt, priority="quality")
            notes = f"# Release {tag_name}\n\n{res.text}\n"

            changelog_file = self.root_dir / "CHANGELOG.md"
            existing = changelog_file.read_text(encoding="utf-8") if changelog_file.exists() else ""
            changelog_file.write_text(notes + "\n" + existing, encoding="utf-8")

            return f"Successfully generated CHANGELOG.md release notes for {tag_name}."
        except Exception as e:
            return f"Error generating release notes: {e}"


def json_escape(text: str) -> str:
    import json
    return json.dumps(text)
