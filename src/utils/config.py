"""
Chargement config YAML — singleton.
"""
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Dict
from functools import lru_cache


CONFIG_DIR = Path(__file__).parents[2] / "config"


@lru_cache(maxsize=None)
def load_yaml(filename: str) -> Dict[str, Any]:
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_prop_firm_rules(firm: str, variant: str) -> Dict[str, Any]:
    cfg = load_yaml("prop_firms.yaml")
    if firm not in cfg:
        raise ValueError(f"Unknown prop firm: {firm}")
    if variant not in cfg[firm]["variants"]:
        raise ValueError(f"Unknown variant '{variant}' for {firm}")
    rules = dict(cfg[firm]["variants"][variant])
    # merge safety limits (internal, more strict)
    rules["safety"] = cfg["internal_safety"]
    return rules


def get_instrument(symbol: str) -> Dict[str, Any]:
    cfg = load_yaml("instruments.yaml")
    if symbol not in cfg:
        raise ValueError(f"Unknown instrument: {symbol}")
    return cfg[symbol]


def list_instruments() -> list[str]:
    return list(load_yaml("instruments.yaml").keys())


PROJECT_ROOT = Path(__file__).parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
FEATURES_DIR = DATA_DIR / "features"
REPORTS_DIR = PROJECT_ROOT / "reports"

for _d in (RAW_DIR, PROCESSED_DIR, FEATURES_DIR, REPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
