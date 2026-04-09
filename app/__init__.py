from pathlib import Path

from flask import Flask

from config import Config
from .routes import register_routes
from .services.attendance import AttendanceService
from .services.camera import CameraService
from .services.storage import StorageService
from .services.vein import VeinRecognitionService


def create_app():
    base_dir = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    app.config.from_object(Config)

    storage = StorageService(app.config)
    camera = CameraService(app.config)
    vein = VeinRecognitionService()
    biometric = AttendanceService(app.config, storage, camera, vein)

    app.extensions["storage_service"] = storage
    app.extensions["camera_service"] = camera
    app.extensions["vein_service"] = vein
    app.extensions["attendance_service"] = biometric

    register_routes(app)
    return app
