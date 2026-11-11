"""Reset the demo database: void any open sandbox authorizations, clear everything, seed Margaret's history.

Usage (from the repo root; use the same DATABASE_PATH as the running backend):
  .venv/Scripts/python scripts/reset_demo.py
  DATABASE_PATH=data/demo.db .venv/Scripts/python scripts/reset_demo.py

Safe to run while the backend is running. Seeds 3 payees (Leo Martin and City Water Utility trusted) and
7 past payments (typical amount about $50). Seeded rows never touched PayPal and are excluded from Insights.

If an open sandbox authorization cannot be voided, nothing is deleted (the payment records are the only way to
find it again): fix the cause and run again, or add --force to delete anyway.
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
    parser.add_argument("--force", action="store_true", help="delete records even if a void failed")
    args = parser.parse_args()

    settings = get_settings()
    path = settings.database_file
    print(f"database: {path}")
    gateway = build_gateway(settings) if settings.paypal_mode == "sandbox" and not args.no_void else None
    try:
        result = demo.reset_safely(path, gateway, force=args.force)
    except demo.ResetBlocked as blocked:
        print("NOT reset: these open sandbox authorizations could not be voided, so their records were kept:")
        for line in blocked.failures:
            print(f"  {line}")
        print("Fix the cause (credentials, network) and run again, or use --force to delete anyway.")
        sys.exit(1)
    if gateway is not None:
        print(f"voided {len(result['voided'])} open sandbox authorization(s)")
        for line in result["failed"]:
            print(f"  could not void {line} (deleted anyway because of --force)")
    print(f"seeded {result['payees']} payees and {result['past_payments']} past payments")


if __name__ == "__main__":
    main()
