import io
import os
import subprocess
import tempfile
import time
from pathlib import Path
from threading import Lock

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - handled gracefully at runtime
    cv2 = None

try:
    from picamera2 import Picamera2
except ImportError:  # pragma: no cover - handled gracefully at runtime
    Picamera2 = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover - handled gracefully at runtime
    Image = None


class CameraService:
    def __init__(self, config):
        self.config = config
        self.mode = config["CAMERA_MODE"].lower()
        self._lock = Lock()
        self._camera = None
        self._rpicam_path = Path("/usr/bin/rpicam-still")
        self._backend = "unavailable"
        self._initialized = False
        self._brightness = 0  # -100 to +100; 0 = no adjustment

    @property
    def backend(self):
        if not self._initialized:
            self._initialize()
        return self._backend

    def set_brightness(self, value):
        """Set brightness offset in the range -100 (darker) to +100 (brighter)."""
        self._brightness = max(-100, min(100, int(value)))

    def _apply_brightness(self, frame):
        if cv2 is None or self._brightness == 0:
            return frame
        beta = int(self._brightness * 1.27)  # map to approx -127..+127
        return cv2.convertScaleAbs(frame, alpha=1.0, beta=beta)

    def get_jpeg_frame(self):
        """Return a single JPEG-encoded frame (brightness applied) as bytes."""
        frame = self.capture_frame()
        if cv2 is not None:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if ok:
                return buf.tobytes()
        if Image is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if cv2 is not None else frame
            img = Image.fromarray(rgb)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            return buf.getvalue()
        raise RuntimeError("Neither cv2 nor Pillow is available for JPEG encoding.")

    def capture_frame(self):
        with self._lock:
            self._initialize()

            if self._backend == "picamera2":
                frame = self._camera.capture_array()
                if frame is None:
                    raise RuntimeError("Pi camera returned an empty frame.")
                if frame.ndim == 3 and frame.shape[2] == 4 and cv2 is not None:
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)
                elif frame.ndim == 3 and frame.shape[2] == 3 and cv2 is not None:
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                return self._apply_brightness(frame)

            if self._backend == "opencv":
                for _ in range(3):
                    self._camera.grab()
                ok, frame = self._camera.read()
                if not ok or frame is None:
                    raise RuntimeError("USB/OpenCV camera capture failed.")
                return self._apply_brightness(frame)

            if self._backend == "rpicam":
                return self._apply_brightness(self._capture_with_rpicam())

            raise RuntimeError(
                "No camera backend is available. Install picamera2 on Raspberry Pi OS "
                "or connect a camera accessible through OpenCV."
            )

    def _apply_picam3_nir_controls(self):
        """Lock AF, AE, and AWB for reproducible NIR finger-vein frames.

        Called once after picamera2 starts.  Controls that are not supported
        by the attached sensor are silently ignored so the method is safe to
        call on any Picamera2 backend.
        """
        controls = {
            # Manual focus — stops the IMX708 AF motor from repositioning
            # between enrollment and later recognition captures.
            "AfMode": self.config["PICAM_AF_MODE"],
            "LensPosition": self.config["PICAM_LENS_POSITION"],
            # Manual exposure — critical for reproducible NIR intensity.
            # Auto-exposure would brighten/darken based on ambient light,
            # making vein templates inconsistent across sessions.
            "AeEnable": False,
            "ExposureTime": self.config["PICAM_EXPOSURE_US"],
            # Higher analogue gain increases NIR sensitivity on the NoIR sensor.
            "AnalogueGain": self.config["PICAM_ANALOGUE_GAIN"],
            # AWB is meaningless for NIR — disable to prevent colour-channel
            # shifts that would alter the grayscale conversion result.
            "AwbEnable": False,
            "ColourGains": (1.0, 1.0),
        }
        try:
            self._camera.set_controls(controls)
        except Exception:
            pass  # Non-fatal: older firmware or non-Pi sensor may not support all keys

    def _initialize(self):
        if self._initialized:
            return

        self._initialized = True

        if self.mode in {"auto", "picamera2"} and Picamera2 is not None:
            try:
                self._camera = Picamera2()
                cam_cfg = self._camera.create_still_configuration(
                    main={
                        "size": (
                            self.config["CAMERA_WIDTH"],
                            self.config["CAMERA_HEIGHT"],
                        )
                    }
                )
                self._camera.configure(cam_cfg)
                self._camera.start()
                # Pi Camera Module 3 NoIR — lock down autofocus, exposure, and
                # white balance so every frame is captured under identical
                # conditions.  Inconsistent AF or AE between enrollment and
                # recognition sessions is a primary cause of match failures.
                self._apply_picam3_nir_controls()
                time.sleep(self.config["CAMERA_WARMUP_SECONDS"])
                self._backend = "picamera2"
                return
            except Exception:
                self._camera = None
                if self.mode == "picamera2":
                    raise RuntimeError(
                        "picamera2 is installed, but the Pi camera could not be started."
                    )

        if self.mode in {"auto", "rpicam"} and self._rpicam_path.exists() and Image is not None:
            self._backend = "rpicam"
            return

        if self.mode in {"auto", "opencv"} and cv2 is not None:
            self._camera = cv2.VideoCapture(0)
            if self._camera is not None and self._camera.isOpened():
                self._camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.config["CAMERA_WIDTH"])
                self._camera.set(
                    cv2.CAP_PROP_FRAME_HEIGHT, self.config["CAMERA_HEIGHT"]
                )
                time.sleep(0.5)
                self._backend = "opencv"
                return

            self._camera = None
            if self.mode == "opencv":
                raise RuntimeError("OpenCV camera backend could not be started.")

        self._backend = "unavailable"

    def _capture_with_rpicam(self):
        if Image is None:
            raise RuntimeError("Pillow is required to read Pi camera captures.")

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            output_path = Path(handle.name)

        command = [
            str(self._rpicam_path),
            "--nopreview",
            "--immediate",
            "--shutter",
            str(self.config["RPICAM_SHUTTER"]),
            "--gain",
            str(self.config["RPICAM_GAIN"]),
            "--width",
            str(self.config["CAMERA_WIDTH"]),
            "--height",
            str(self.config["CAMERA_HEIGHT"]),
            "--output",
            str(output_path),
        ]

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if completed.returncode != 0:
                message = completed.stderr.strip() or "rpicam-still failed."
                raise RuntimeError(message)

            frame = np.array(Image.open(output_path).convert("RGB"))
            if cv2 is not None:
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            return frame
        finally:
            if output_path.exists():
                os.unlink(output_path)

    def close(self):
        with self._lock:
            if self._camera is None:
                return

            if self._backend == "picamera2":
                self._camera.stop()
            elif self._backend == "opencv":
                self._camera.release()

            self._camera = None
            self._backend = "unavailable"
            self._initialized = False
