from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_DATA = tempfile.mkdtemp(prefix="haoyuan-test-")
os.environ["HAOYUAN_DATA_DIR"] = _DATA
os.environ["HAOYUAN_AUTO_APPROVE"] = "0"
os.environ["HAOYUAN_AUTO_RESUME"] = "0"
os.environ["HAOYUAN_SUPERVISOR_INTERVAL"] = "3600"
os.environ["HAOYUAN_SUPERVISOR_AUTO_CANCEL_SEC"] = "0"
os.environ["HAOYUAN_FORCE_MOCK"] = "1"

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture(scope="session")
def client():
    with TestClient(main.app) as test_client:
        yield test_client
