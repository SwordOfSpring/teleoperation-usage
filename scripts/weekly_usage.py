#!/usr/bin/env python3
"""Weekly DataLego usage entry point; complete weeks validate and backfill daily data."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from usage_pipeline import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main("weekly"))
