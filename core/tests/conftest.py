import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def paths(tmp_path):
    from mimi.paths import Paths

    return Paths(data_override=tmp_path / "data")


@pytest.fixture()
def client(paths):
    """API client without the lifespan (no model, no kiwix-serve): fast and hermetic."""
    from fastapi.testclient import TestClient

    from mimi.app import create_app

    app = create_app(paths)
    with_client = TestClient(app)
    return with_client
