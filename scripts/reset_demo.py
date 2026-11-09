"""Reset the demo database: void any open sandbox authorizations, clear everything, seed Margaret's history.

Usage (from the repo root; use the same DATABASE_PATH as the running backend):
  .venv/Scripts/python scripts/reset_demo.py
  DATABASE_PATH=data/demo.db .venv/Scripts/python scripts/reset_demo.py

Safe to run while the backend is running. Seeds 3 payees (Leo Martin and City Water Utility trusted) and
7 past payments (typical amount about $50). Seeded rows never touched PayPal and are excluded from Insights.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import demo  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.paypal import build_gateway  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-void", action="store_true", help="do not void open sandbox authorizations first")
    args = parser.parse_args()

    settings = get_settings()
    path = settings.database_file
    print(f"database: {path}")
    if settings.paypal_mode == "sandbox" and not args.no_void:
        result = demo.void_open_authorizations(path, build_gateway(settings))
        print(f"voided {len(result['voided'])} open sandbox authorization(s)")
        for line in result["failed"]:
            print(f"  could not void {line}")
    counts = demo.reset(path)
    print(f"seeded {counts['payees']} payees and {counts['past_payments']} past payments")


if __name__ == "__main__":
    main()
