#!/usr/bin/env python3
"""Daily DataLego usage query entry point."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from usage_pipeline import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main("daily"))
