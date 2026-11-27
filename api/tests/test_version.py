from __future__ import annotations

import json
from pathlib import Path

from configs.configs import APP_VERSION, _resolve_app_version

ROOT = Path(__file__).resolve().parents[2]


def test_app_version_matches_root_package_json():
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert APP_VERSION == pkg["version"]


def test_package_json_takes_precedence_over_env(monkeypatch):
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    monkeypatch.setenv("HAOYUAN_VERSION", "9.9.9")
    assert _resolve_app_version() == pkg["version"]
