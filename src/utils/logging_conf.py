"""
Logging centralisé — horodatage précis + niveau par module.
"""
import logging
import sys
from pathlib import Path
from datetime import datetime


def get_logger(name: str, level: str = "INFO", log_to_file: bool = True) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:                 # already configured
        return logger

    logger.setLevel(getattr(logging, level.upper()))

    fmt = logging.Formatter(
        "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)-30s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stdout_h = logging.StreamHandler(sys.stdout)
    stdout_h.setFormatter(fmt)
    logger.addHandler(stdout_h)

    if log_to_file:
        log_dir = Path(__file__).parents[2] / "reports" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.utcnow().strftime("%Y%m%d")
        fh = logging.FileHandler(log_dir / f"run_{date_str}.log")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    logger.propagate = False
    return logger
