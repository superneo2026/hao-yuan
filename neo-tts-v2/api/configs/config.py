# neo-tts v2 API configuration
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent

HOST = os.environ.get("NEO_TTS_HOST", "127.0.0.1")
PORT = int(os.environ.get("NEO_TTS_PORT", "8002"))
PREFIX = "/api"

LOG_DIR = PROJECT / "logs"
CKPT_DIR = PROJECT / "checkpoints" / "cfm"
DATA_DIR = PROJECT / "data" / "v2"
OUTPUT_DIR = PROJECT / "outputs" / "api"
REPORT_DIR = PROJECT / "reports" / "v2"
WEB_DIST = PROJECT / "web" / "dist"

V1_URL = os.environ.get("NEO_TTS_V1_URL", "http://127.0.0.1:8001")
V2_VERSION = "2.0.0-pilot"
