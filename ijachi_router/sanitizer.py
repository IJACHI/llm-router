"""Statistical & Cryptographic Watermark Neutralizer for ijachi-llm-router.

Disrupts Type 1 Statistical Watermarks (e.g., SynthID, Kirchenbauer green/red list biasing)
by breaking the pseudorandom n-gram token hash chains used by detectors.
"""

from __future__ import annotations

import re
from typing import Any

# Lightweight synonym dictionary for perturbing n-gram hash states
_SYNONYM_MAP: dict[str, list[str]] = {
    "important": ["crucial", "vital", "essential", "significant"],
    "quickly": ["swiftly", "rapidly", "promptly"],
    "utilize": ["use", "employ", "apply"],
    "help": ["assist", "support", "aid"],
    "create": ["build", "generate", "produce", "construct"],
    "modify": ["alter", "update", "adjust", "change"],
    "check": ["verify", "inspect", "validate", "ensure"],
    "remove": ["delete", "strip", "eliminate", "clear"],
    "receive": ["get", "obtain", "fetch"],
    "show": ["display", "present", "reveal"],
    "start": ["begin", "launch", "initiate"],
    "stop": ["halt", "end", "terminate"],
    "difficult": ["hard", "challenging", "complex"],
    "easy": ["simple", "straightforward", "effortless"],
}


def _perturb_prose_ngrams(text: str) -> str:
    """Disrupt n-gram token hash chains in prose text via selective synonym substitution."""
    words = text.split()
    if not words:
        return text

    modified = False
    for i in range(len(words)):
        clean_word = re.sub(r"[^\w]", "", words[i].lower())
        if clean_word in _SYNONYM_MAP:
            synonyms = _SYNONYM_MAP[clean_word]
            replacement = synonyms[0]
            # Match capitalization
            if words[i].istitle():
                replacement = replacement.capitalize()
            elif words[i].isupper():
                replacement = replacement.upper()
            # Preserve punctuation
            punctuation = re.findall(r"[^\w]+$", words[i])
            suffix = punctuation[0] if punctuation else ""
            words[i] = replacement + suffix
            modified = True

    return " ".join(words) if modified else text


def _perturb_code_ast(code: str) -> str:
    """Normalize code token sequences to break code-level watermarking."""
    # Normalize extra blank lines
    code = re.sub(r"\n{3,}", "\n\n", code)
    # Normalize inline spacing
    lines = code.splitlines()
    cleaned_lines = []
    for line in lines:
        # Strip trailing whitespace
        line = line.rstrip()
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def neutralize_statistical_watermark(text: str, method: str = "hybrid") -> str:
    """Neutralize Type 1 statistical token probability watermarks.

    Methods:
    - ``synonym_perturber``: Break n-gram hash states in prose via synonym shifts.
    - ``ast_code_perturber``: Normalize code token states.
    - ``hybrid``: Automatically apply appropriate perturbation based on text content.
    """
    if not text or not text.strip():
        return text

    is_code = any(kw in text for kw in ["def ", "class ", "import ", "function ", "const ", "var ", "let ", "fn "])

    if method == "ast_code_perturber" or (method == "hybrid" and is_code):
        return _perturb_code_ast(text)
    elif method == "synonym_perturber" or (method == "hybrid" and not is_code):
        return _perturb_prose_ngrams(text)

    return text
