"""Unit tests for Statistical & Cryptographic Watermark Neutralizer."""

from __future__ import annotations

import pytest

from ijachi_router.sanitizer import neutralize_statistical_watermark, _perturb_prose_ngrams
from ijachi_router.humanizer import humanize


def test_perturb_prose_ngrams():
    text = "It is important to quickly check and receive the result to show user."
    perturbed = _perturb_prose_ngrams(text)
    # Check that n-gram synonym shifts occurred
    assert "crucial" in perturbed or "vital" in perturbed or "essential" in perturbed
    assert "verify" in perturbed or "inspect" in perturbed or "validate" in perturbed


def test_neutralize_statistical_watermark_code():
    code = "def process():\n    pass\n\n\n\nprint('done')\n"
    neutralized = neutralize_statistical_watermark(code, method="ast_code_perturber")
    # Check normalization of consecutive blank lines
    assert "\n\n\n" not in neutralized
    assert "def process" in neutralized


def test_humanize_with_statistical_stripping():
    text = "Certainly! It is important to quickly receive the output."
    cleaned = humanize(text, mode="light", strip_statistical=True)
    assert "Certainly" not in cleaned
    assert ("crucial" in cleaned or "vital" in cleaned or "essential" in cleaned)
