from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
USERS_DIR = DATA_DIR / "users"
CAPTURES_DIR = DATA_DIR / "captures"


class Config:
    SECRET_KEY = os.getenv("VEIN_SECRET_KEY", "change-this-secret-before-production")
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

    ENROLLMENT_SAMPLES = int(os.getenv("VEIN_ENROLLMENT_SAMPLES", "3"))
    MATCH_THRESHOLD = float(os.getenv("VEIN_MATCH_THRESHOLD", "0.58"))
    MATCH_TOP_K = int(os.getenv("VEIN_MATCH_TOP_K", "2"))
