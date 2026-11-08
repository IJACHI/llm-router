#!/usr/bin/env python3
"""Rebuild the bundled request classifier (ijachi_router/data/classifier_model.json).

    python scripts/train_classifier.py

Trains on data/train_data.csv, chooses the regularisation strength by stratified 5-fold
cross-validation, and reports accuracy on the held-out data/eval_prompts.csv (never used
for training). Requires scikit-learn.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ijachi_router.routing.classifier import _BUNDLED_MODEL_PATH, _DATA_PATH, train_model  # noqa: E402

data = train_model(_DATA_PATH, ROOT / "data" / "eval_prompts.csv")
_BUNDLED_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
_BUNDLED_MODEL_PATH.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
meta = data["meta"]
print(f"examples={meta['n_examples']}  C={meta['C']}  cv_accuracy={meta['cv_accuracy']:.3f}  "
      f"heldout_accuracy={meta.get('eval_accuracy', float('nan')):.3f}")
print(f"wrote {_BUNDLED_MODEL_PATH} ({_BUNDLED_MODEL_PATH.stat().st_size // 1024} KB)")
