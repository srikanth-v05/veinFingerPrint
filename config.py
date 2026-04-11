import secrets
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
USERS_DIR = DATA_DIR / "users"
CAPTURES_DIR = DATA_DIR / "captures"


class Config:
    _env_secret = os.getenv("VEIN_SECRET_KEY")
    SECRET_KEY = _env_secret if _env_secret else secrets.token_hex(32)
    ADMIN_USERNAME = os.getenv("VEIN_ADMIN_USER", "admin")
    ADMIN_PASSWORD = os.getenv("VEIN_ADMIN_PASSWORD", "admin123")

    DATA_DIR = DATA_DIR
    USERS_DIR = USERS_DIR
    CAPTURES_DIR = CAPTURES_DIR
    USERS_FILE = DATA_DIR / "users.json"
    ATTENDANCE_FILE = DATA_DIR / "attendance.csv"

    CAMERA_MODE = os.getenv("VEIN_CAMERA_MODE", "auto")
    CAMERA_WIDTH = int(os.getenv("VEIN_CAMERA_WIDTH", "1280"))
    CAMERA_HEIGHT = int(os.getenv("VEIN_CAMERA_HEIGHT", "720"))
    CAMERA_WARMUP_SECONDS = float(os.getenv("VEIN_CAMERA_WARMUP_SECONDS", "2.0"))
    CAPTURE_DELAY_SECONDS = float(os.getenv("VEIN_CAPTURE_DELAY_SECONDS", "0.8"))
    RPICAM_SHUTTER = int(os.getenv("VEIN_RPICAM_SHUTTER", "3500"))
    RPICAM_GAIN = float(os.getenv("VEIN_RPICAM_GAIN", "1"))

    # Pi Camera Module 3 NoIR controls for NIR finger-vein imaging.
    # AfMode 0 = manual focus (critical — prevents AF hunting between frames).
    # LensPosition is in diopters: 1 / distance_metres.
    #   8 cm finger slot  → 12.5   |  10 cm → 10.0  |  12 cm → 8.3
    # ExposureTime in microseconds — tune so the finger is clearly lit but not blown out.
    # AnalogueGain boosted for NIR sensitivity (no visible-light penalty on NoIR sensor).
    PICAM_AF_MODE = int(os.getenv("VEIN_PICAM_AF_MODE", "0"))          # 0=manual
    PICAM_LENS_POSITION = float(os.getenv("VEIN_PICAM_LENS_POSITION", "10.0"))
    PICAM_EXPOSURE_US = int(os.getenv("VEIN_PICAM_EXPOSURE_US", "10000"))  # 10 ms
    PICAM_ANALOGUE_GAIN = float(os.getenv("VEIN_PICAM_ANALOGUE_GAIN", "6.0"))

    ENROLLMENT_SAMPLES = int(os.getenv("VEIN_ENROLLMENT_SAMPLES", "3"))
    # MATCH_THRESHOLD applies to cosine similarity space [0, 1] when HOG features are used.
    MATCH_THRESHOLD = float(os.getenv("VEIN_MATCH_THRESHOLD", "0.72"))
    MATCH_MARGIN = float(os.getenv("VEIN_MATCH_MARGIN", "0.08"))
    MATCH_TOP_K = int(os.getenv("VEIN_MATCH_TOP_K", "2"))
