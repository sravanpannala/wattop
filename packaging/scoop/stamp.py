"""Stamp the Scoop manifest with a released version and its zipapp hash.

Run from the release workflow: `python packaging/scoop/stamp.py 0.1.0 dist/wattop.pyz`
so the bucket can be updated by copying one file instead of editing it by hand.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

MANIFEST = Path(__file__).with_name("wattop.json")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    version, zipapp = argv[0].lstrip("v"), Path(argv[1])

    digest = hashlib.sha256(zipapp.read_bytes()).hexdigest()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["version"] = version
    manifest["hash"] = digest
    base = manifest["url"].rsplit("/download/", 1)[0]
    manifest["url"] = f"{base}/download/v{version}/{zipapp.name}"

    MANIFEST.write_text(json.dumps(manifest, indent=4) + "\n", encoding="utf-8")
    print(f"{MANIFEST}: version={version} hash={digest[:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
