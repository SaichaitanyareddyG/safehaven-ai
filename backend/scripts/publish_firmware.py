"""Publish a band firmware build: bands on their charger install it next.

    DATABASE_URL=... .venv/bin/python scripts/publish_firmware.py \\
        --file ../firmware/.pio/build/m5sticks3-lowpower/firmware.bin --version 0.5.0

The version must be exactly what that build reports (FIRMWARE_VERSION in
firmware/src/sticks3_main.cpp), or bands would be offered it again after
installing it.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import models as _models  # noqa: E402,F401  (registers every table)
from app.core.db import SessionLocal  # noqa: E402
from app.wearables.firmware import publish  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--notes")
    args = parser.parse_args()

    image = args.file.read_bytes()
    db = SessionLocal()
    try:
        release = publish(db, args.version, image, args.notes)
    except ValueError as exc:
        sys.exit(f"Not published: {exc}")
    finally:
        db.close()
    print(f"Published {release.version}: {release.size} bytes, sha256 {release.sha256}")


if __name__ == "__main__":
    main()
