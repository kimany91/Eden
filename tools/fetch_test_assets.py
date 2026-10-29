"""Download the real FL Studio project used by tests/test_real_flp.py.

The file comes from the PyFLP project (GPL-3.0) and is NOT committed to Eden:
it is downloaded into tests/assets/external/ (git-ignored) for local testing.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/demberto/PyFLP/master/tests/assets/FL%2020.8.4.flp"
SHA256 = "60822a9e2fde1397f4287caa56444618d339c0812a40ca86ce090cd1617f51de"
DEST = Path(__file__).resolve().parent.parent / "tests" / "assets" / "external" / "FL 20.8.4.flp"


def main() -> int:
    if DEST.is_file() and hashlib.sha256(DEST.read_bytes()).hexdigest() == SHA256:
        print(f"Déjà présent : {DEST}")
        return 0
    with urllib.request.urlopen(URL, timeout=60) as resp:
        data = resp.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        print(f"Somme de contrôle inattendue ({digest}), fichier refusé", file=sys.stderr)
        return 1
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_bytes(data)
    print(f"Téléchargé : {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
