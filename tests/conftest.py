import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

REAL_FLP = Path(__file__).parent / "assets" / "external" / "FL 20.8.4.flp"


@pytest.fixture(autouse=True)
def _isolated_eden_home(tmp_path, monkeypatch):
    """Never write into the developer's real Eden workspace during tests."""
    monkeypatch.setenv("EDEN_HOME", str(tmp_path / "eden_home"))


@pytest.fixture
def real_flp():
    if not REAL_FLP.is_file():
        pytest.skip("Projet FL réel absent : lancer `python tools/fetch_test_assets.py`")
    return REAL_FLP
