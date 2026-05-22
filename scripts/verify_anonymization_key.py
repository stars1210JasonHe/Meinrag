"""Startup-time encryption round-trip check.

Loads ANONYMIZATION_ENCRYPTION_KEY from env, constructs a MappingCrypto,
runs encrypt(sample) → decrypt → equals(sample). Exits 0 on success,
non-zero on any failure path.

Run this as a deployment smoke test before flipping
ANONYMIZATION_ENABLED=true in a real environment.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


# Make the app package importable when this script is run via
# `python scripts/...` rather than `uv run python -m scripts.foo`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    if os.environ.get("ANONYMIZATION_ENABLED", "").lower() != "true":
        print(
            "ERROR: ANONYMIZATION_ENABLED is not 'true' — nothing to verify.",
            file=sys.stderr,
        )
        return 2

    key = os.environ.get("ANONYMIZATION_ENCRYPTION_KEY", "")
    if not key:
        print("ERROR: ANONYMIZATION_ENCRYPTION_KEY is empty.", file=sys.stderr)
        return 3

    try:
        from app.anonymization.crypto import MappingCrypto, EncryptionError
        crypto = MappingCrypto(key)
        if crypto.verify():
            print("OK: encryption key round-trip succeeded.")
            return 0
        print("ERROR: round-trip verification returned False.", file=sys.stderr)
        return 4
    except EncryptionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())
