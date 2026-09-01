#!/usr/bin/env python
"""命令行入口：python scripts/seed_db.py"""

import sys
from pathlib import Path

# 把 src 加到 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from medical_agent.db.seed import seed_all, print_summary  # noqa: E402

if __name__ == "__main__":
    import random

    random.seed(42)
    stats = seed_all(reset=True)
    print_summary(stats)
