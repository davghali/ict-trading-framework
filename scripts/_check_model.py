"""Helper : validate the production ML model pickle (called by DEPLOY_ONE_CLICK.ps1)"""
from __future__ import annotations
import os
import sys
import pickle
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

model_path_arg = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    "MODEL_PATH", str(ROOT / "models" / "production_model.pkl")
)
model_path = Path(model_path_arg)

if not model_path.exists():
    print("FAIL: model not found at {0}".format(model_path))
    sys.exit(1)

try:
    with open(model_path, "rb") as f:
        m = pickle.load(f)
    threshold = m.get("threshold", "?")
    samples = m.get("training_samples", "?")
    auc = m.get("in_sample_auc", 0.0)
    try:
        auc_str = "{0:.3f}".format(float(auc))
    except Exception:
        auc_str = str(auc)
    print("Threshold: {0} | Samples: {1} | AUC: {2}".format(threshold, samples, auc_str))
    sys.exit(0)
except Exception as e:
    print("FAIL: {0}".format(e))
    sys.exit(1)
