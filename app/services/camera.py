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

    def set_focus(self, diopters):
        """Adjust lens focus live.

        diopters = 0  → continuous AF (AfMode 2, camera tracks automatically).
        diopters > 0  → manual focus (AfMode 0, LensPosition = diopters).
                        Useful range: 5 (20 cm) … 20 (5 cm).
        Only has effect on the picamera2 backend — ignored on others.

        NOTE: self._camera is assigned before the warmup sleep, so it is
        available even while self._backend is still "unavailable".  Checking
        _camera is not None is therefore the correct guard here — NOT _backend.
        """
        diopters = max(0.0, min(20.0, float(diopters)))
        if self._camera is None:
            return
        try:
            if diopters == 0.0:
                # AfMode must be applied before the trigger (separate calls).
                # Some firmware versions ignore AfTrigger when bundled with
                # AfMode, leaving the lens frozen at the last manual position.
                self._camera.set_controls({"AfMode": 2})
                self._camera.set_controls({"AfTrigger": 0})
            else:
                self._camera.set_controls({
                    "AfMode": 0,
                    "LensPosition": diopters,
                })
        except Exception:
            pass

    def _apply_brightness(self, frame):
        if cv2 is None or self._brightness == 0:
            return frame
        beta = int(self._brightness * 1.27)  # map to approx -127..+127
        return cv2.convertScaleAbs(frame, alpha=1.0, beta=beta)

    def get_jpeg_frame(self):
        """Capture one frame, crop to the finger region, return JPEG bytes."""
        frame = self.capture_frame()
        frame = self._crop_to_finger(frame)
        if cv2 is not None:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if ok:
                return buf.tobytes()
        if Image is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if cv2 is not None else frame
            img = Image.fromarray(rgb)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            return buf.getvalue()
        raise RuntimeError("Neither cv2 nor Pillow is available for JPEG encoding.")

    def _crop_to_finger(self, frame):
        """Crop the frame to the finger region for the live preview.

        Uses the same red-channel + Otsu + contour approach as the vein
        pipeline's ROI extractor, but without resizing — the crop is returned
        at its natural resolution so the live feed shows just the finger.
        Falls back to the full frame if no region can be detected.
        """
        if cv2 is None or frame is None or frame.size == 0:
            return frame

        # NIR signal lives in the red channel (BGR index 2)
        gray = frame[:, :, 2] if frame.ndim == 3 else frame
        blurred = cv2.GaussianBlur(gray, (15, 15), 0)
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Invert if the finger is darker than the background
        if np.count_nonzero(thresh) < thresh.size * 0.15:
            thresh = cv2.bitwise_not(thresh)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return frame

        h_img, w_img = frame.shape[:2]
        cx_img, cy_img = w_img / 2.0, h_img / 2.0

        def contour_score(c):
            x, y, w, h = cv2.boundingRect(c)
            area = float(w * h)
            dist = ((x + w / 2.0 - cx_img) ** 2 + (y + h / 2.0 - cy_img) ** 2) ** 0.5
            return area - dist * 3.0

        best = max(contours, key=contour_score)
        x, y, w, h = cv2.boundingRect(best)

        # Reject tiny detections (noise)
        if w < w_img * 0.08 or h < h_img * 0.08:
            return frame

        pad = 30
        x0 = max(x - pad, 0)
        y0 = max(y - pad, 0)
        x1 = min(x + w + pad, w_img)
        y1 = min(y + h + pad, h_img)
        return frame[y0:y1, x0:x1]

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
        """Apply Pi Cam 3 NoIR controls for reproducible NIR finger-vein frames.

        Focus strategy
        ──────────────
        AfMode 2 (Continuous, default): camera continuously focuses on whatever
        is in the slot.  Works without knowing the exact finger distance and
        is robust to small placement variations.

        AfMode 0 (Manual): user supplies VEIN_PICAM_LENS_POSITION in diopters
        (1/distance_m).  Only use this if continuous AF causes visible hunting.

        Exposure / gain are always set to fixed values so every frame has
        identical illumination — essential for reproducible vein templates.
        """
        af_mode = self.config["PICAM_AF_MODE"]

        controls = {
            "AfMode": af_mode,
            # Manual exposure — fixed so enrollment and recognition frames have
            # the same pixel intensity.  AE would drift with ambient light.
            "AeEnable": False,
            "ExposureTime": self.config["PICAM_EXPOSURE_US"],
            # Higher gain for NIR sensitivity on the NoIR sensor.
            "AnalogueGain": self.config["PICAM_ANALOGUE_GAIN"],
            # AWB is irrelevant for NIR but can shift channel gains — disable.
            "AwbEnable": False,
            "ColourGains": (1.0, 1.0),
        }

        # LensPosition only applies in manual mode (AfMode=0).
        # Sending it in continuous/auto mode has no effect and some firmware
        # versions reject the control outright, causing the whole set_controls
        # call to fail silently and leaving the camera at infinity focus.
        if af_mode == 0:
            controls["LensPosition"] = self.config["PICAM_LENS_POSITION"]

        self._camera.set_controls(controls)

        # AfTrigger must be sent in a separate call after AfMode is applied.
        # Some firmware versions ignore it when bundled with other controls.
        if af_mode != 0:
            self._camera.set_controls({"AfTrigger": 0})

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
