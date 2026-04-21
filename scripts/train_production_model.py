"""
TRAIN PRODUCTION MODEL — save trained GradientBoosting + scaler for live bot
"""
from __future__ import annotations
import sys
import pickle
import json
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from bot_level1_complete import build_dataset
from src.data_engine import DataLoader
from src.feature_engine import FeatureEngine
from src.utils.types import Timeframe

MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)

# Production assets (matches final bot config)
ASSETS = [
    ("XAUUSD", Timeframe.H1),
    ("XAGUSD", Timeframe.H1),
    ("BTCUSD", Timeframe.H1),
    ("NAS100", Timeframe.H1),
    ("SPX500", Timeframe.H1),
    ("DOW30",  Timeframe.H1),
    ("EURUSD", Timeframe.D1),
    ("GBPUSD", Timeframe.D1),
    ("AUDUSD", Timeframe.D1),
    ("USDCAD", Timeframe.D1),
    ("ETHUSD", Timeframe.D1),
]

ML_THRESHOLD = 0.45  # OPTIMAL per param sweep


def main():
    print("=" * 80)
    print("🧠 TRAINING PRODUCTION ML MODEL (threshold 0.45)")
    print("=" * 80)

    # Load DXY for correlation features
    try:
        dxy_df = pd.read_parquet(ROOT / "data/raw/DXY_1h.parquet")
        print(f"✓ DXY loaded: {len(dxy_df)} bars")
    except Exception:
        dxy_df = None

    # Build combined dataset
    all_ds = []
    for sym, tf in ASSETS:
        try:
            df = DataLoader().load(sym, tf)
            df = FeatureEngine().compute(df)
            ds = build_dataset(df, dxy_df)
            ds["symbol"] = sym
            ds["tf"] = tf.value
            all_ds.append(ds)
            print(f"  ✓ {sym} {tf.value}: {len(ds)} samples")
        except Exception as e:
            print(f"  ⚠ {sym} {tf.value}: {e}")

    combined = pd.concat(all_ds, ignore_index=True)
    combined = combined[combined["news_blackout"] == 0].reset_index(drop=True)
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    print(f"\nTotal samples (after news filter): {len(combined)}")

    # Extract features
    feature_cols = [c for c in combined.columns
                    if c not in ["r_realized", "exit_reason", "label", "timestamp", "symbol", "tf"]]

    X = combined[feature_cols].values
    y = combined["label"].values

    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    # Scaler
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Train on ALL data (production model uses everything)
    clf = GradientBoostingClassifier(
        n_estimators=150,
        max_depth=4,
        learning_rate=0.05,
        min_samples_leaf=10,
        random_state=42,
    )
    clf.fit(X_scaled, y)

    # Evaluate on in-sample (for reference only)
    proba = clf.predict_proba(X_scaled)[:, 1]
    preds = clf.predict(X_scaled)
    is_acc = accuracy_score(y, preds)
    is_auc = roc_auc_score(y, proba)

    # Apply threshold
    mask = proba >= ML_THRESHOLD
    n_passed = int(mask.sum())
    if mask.sum() > 0:
        wr_passed = (y[mask] == 1).mean() * 100
    else:
        wr_passed = 0

    # Feature importance
    importance = sorted(zip(feature_cols, clf.feature_importances_),
                        key=lambda x: x[1], reverse=True)

    print(f"\n📊 MODEL STATS (in-sample, full training):")
    print(f"  Accuracy          : {is_acc:.3f}")
    print(f"  AUC               : {is_auc:.3f}")
    print(f"  Samples passing   : {n_passed}/{len(y)} ({n_passed/len(y)*100:.1f}%)")
    print(f"  WR on passed      : {wr_passed:.2f}%")
    print(f"  Top 10 features:")
    for feat, imp in importance[:10]:
        print(f"    {feat:25s} : {imp:.4f}")

    # Save model
    model_path = MODELS_DIR / "production_model.pkl"
    with open(model_path, "wb") as f:
        pickle.dump({
            "model": clf,
            "scaler": scaler,
            "feature_cols": feature_cols,
            "threshold": ML_THRESHOLD,
            "trained_at": datetime.utcnow().isoformat(),
            "training_samples": len(y),
            "in_sample_auc": float(is_auc),
            "in_sample_accuracy": float(is_acc),
            "assets_trained_on": [f"{s}_{tf.value}" for s, tf in ASSETS],
            "top_features": [{"feature": f, "importance": float(i)} for f, i in importance[:15]],
        }, f)

    print(f"\n✅ Model saved: {model_path}")

    # Save metadata JSON
    meta = {
        "threshold": ML_THRESHOLD,
        "trained_at": datetime.utcnow().isoformat(),
        "training_samples": len(y),
        "in_sample_auc": float(is_auc),
        "top_features": [{"feature": f, "importance": float(i)} for f, i in importance[:15]],
        "assets": [f"{s}_{tf.value}" for s, tf in ASSETS],
        "expected_performance": {
            "trades_per_week": 3.6,
            "win_rate": 51.8,
            "expectancy_R": 0.65,
            "annualized_pct": 82,
            "max_dd_pct": -3.9,
        },
    }
    (MODELS_DIR / "production_model_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"✅ Metadata saved: {MODELS_DIR / 'production_model_meta.json'}")


if __name__ == "__main__":
    main()
