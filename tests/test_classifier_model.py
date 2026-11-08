"""The bundled request classifier: data hygiene, accuracy, safety and sklearn parity."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from ijachi_router.routing import classifier as rc

ROOT = Path(__file__).resolve().parent.parent
TRAIN = ROOT / "data" / "train_data.csv"
EVAL = ROOT / "data" / "eval_prompts.csv"
VALID = {"code", "math", "creative", "summarization", "reasoning", "long-context", "simple-qa"}


def _rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_training_data_is_well_formed_and_disjoint_from_eval():
    train, ev = _rows(TRAIN), _rows(EVAL)
    assert len(train) >= 400
    for r in train + ev:
        assert None not in r, f"unquoted comma split a row: {r}"
        assert r["category"] in VALID, r
    overlap = {r["prompt"].lower() for r in train} & {r["prompt"].lower() for r in ev}
    assert not overlap


def test_bundled_model_is_used_and_accurate_on_held_out_prompts():
    model = rc.SafeModel.load(rc._BUNDLED_MODEL_PATH)
    assert model is not None and set(model.classes) == VALID
    ev = _rows(EVAL)
    correct = sum(rc.predict_base_category(r["prompt"])[0] == r["category"] for r in ev)
    assert correct / len(ev) >= 0.85, f"held-out accuracy dropped to {correct / len(ev):.1%}"


@pytest.mark.parametrize("prompt,expected", [
    ("Solve for x: 4x - 7 = 13", "math"),
    ("Fix the failing test in test_api.py", "code"),
    ("Go through the whole codebase and list every TODO", "long-context"),
    ("Should we pick Kafka or RabbitMQ for our event bus?", "reasoning"),
])
def test_representative_prompts(prompt, expected):
    assert rc.predict_base_category(prompt)[0] == expected


def test_tampered_model_is_refused(tmp_path):
    data = json.loads(rc._BUNDLED_MODEL_PATH.read_text())
    data["weights"][0][0] += 1.0
    bad = tmp_path / "m.json"
    bad.write_text(json.dumps(data))
    assert rc.SafeModel.load(bad) is None


def test_stale_user_model_is_ignored(tmp_path, monkeypatch):
    data = json.loads(rc._BUNDLED_MODEL_PATH.read_text())
    data["meta"]["data_sha256"] = "not-the-current-data"
    user = tmp_path / "classifier_model.json"
    user.write_text(json.dumps(data))
    monkeypatch.setattr(rc, "_SAFE_MODEL_PATH", user)
    monkeypatch.setattr(rc, "_safe_model", None)
    assert rc.get_safe_model().meta.get("data_sha256") != "not-the-current-data"
    monkeypatch.setattr(rc, "_safe_model", None)


def test_json_inference_matches_sklearn():
    pytest.importorskip("sklearn")
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    model = rc.SafeModel.load(rc._BUNDLED_MODEL_PATH)
    prompts, labels = rc._read_csv(TRAIN)
    pipe = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), lowercase=False),
        LogisticRegression(C=model.meta["C"], max_iter=2000, class_weight="balanced"),
    ).fit([rc.preprocess(p) for p in prompts], labels)
    sample = [r["prompt"] for r in _rows(EVAL)][::7]
    for p, row in zip(sample, pipe.predict_proba([rc.preprocess(p) for p in sample])):
        assert max(abs(a - b) for a, b in zip(row, model.predict_proba(p))) < 1e-9


def test_bundled_model_is_current_with_training_data():
    model = rc.SafeModel.load(rc._BUNDLED_MODEL_PATH)
    assert model.meta["data_sha256"] == rc._data_sha256(TRAIN), (
        "data/train_data.csv changed: run `python scripts/train_classifier.py`"
    )
