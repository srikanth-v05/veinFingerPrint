import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from threading import RLock

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - handled gracefully at runtime
    cv2 = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover - handled gracefully at runtime
    Image = None


class StorageService:
    def __init__(self, config):
        self.config = config
        self.users_file = Path(config["USERS_FILE"])
        self.attendance_file = Path(config["ATTENDANCE_FILE"])
        self.users_dir = Path(config["USERS_DIR"])
        self.captures_dir = Path(config["CAPTURES_DIR"])
        self._lock = RLock()
        self._ensure_layout()

    def _ensure_layout(self):
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.captures_dir.mkdir(parents=True, exist_ok=True)
        self.users_file.parent.mkdir(parents=True, exist_ok=True)

        if not self.users_file.exists():
            self.users_file.write_text(json.dumps({"users": []}, indent=2))

        if not self.attendance_file.exists():
            with self.attendance_file.open("w", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["timestamp", "user_id", "name", "status", "score"],
                )
                writer.writeheader()

    def list_users(self):
        payload = self._read_users_payload()
        return sorted(payload["users"], key=lambda item: item["full_name"].lower())

    def get_user(self, user_id):
        for user in self.list_users():
            if user["user_id"] == user_id:
                return user
        return None

    def save_user(self, user_id, full_name, samples):
        timestamp = datetime.utcnow().isoformat()
        user_dir = self.users_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)

        sample_entries = []
        for index, sample in enumerate(samples, start=1):
            raw_name = f"raw_{index:03d}.png"
            template_name = f"template_{index:03d}.png"
            features_name = f"features_{index:03d}.npy"

            raw_path = user_dir / raw_name
            template_path = user_dir / template_name
            features_path = user_dir / features_name

            self._save_image(raw_path, sample["raw"])
            self._save_image(template_path, sample["template"])

            entry = {
                "captured_at": timestamp,
                "raw_path": str(raw_path.relative_to(self.users_file.parent)),
                "template_path": str(template_path.relative_to(self.users_file.parent)),
            }

            if "features" in sample and sample["features"] is not None:
                self._save_features(features_path, sample["features"])
                entry["features_path"] = str(features_path.relative_to(self.users_file.parent))

            sample_entries.append(entry)

        with self._lock:
            payload = self._read_payload_nolock()
            payload["users"] = [u for u in payload["users"] if u["user_id"] != user_id]
            payload["users"].append({
                "user_id": user_id,
                "full_name": full_name,
                "created_at": timestamp,
                "samples": sample_entries,
            })
            self._write_payload_nolock(payload)

        return self.get_user(user_id)

    def delete_user(self, user_id):
        with self._lock:
            payload = self._read_payload_nolock()
            original_count = len(payload["users"])
            payload["users"] = [u for u in payload["users"] if u["user_id"] != user_id]
            if len(payload["users"]) == original_count:
                return False
            self._write_payload_nolock(payload)
        user_dir = self.users_dir / user_id
        if user_dir.exists():
            shutil.rmtree(user_dir)
        return True

    def list_recent_attendance(self, limit=10):
        if not self.attendance_file.exists():
            return []

        with self.attendance_file.open(newline="") as handle:
            rows = list(csv.DictReader(handle))

        rows.reverse()
        return rows[:limit]

    def get_today_record(self, user_id):
        today = datetime.utcnow().date().isoformat()
        if not self.attendance_file.exists():
            return None
        with self.attendance_file.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in reversed(rows):
            if not row["timestamp"].startswith(today):
                break
            if row["user_id"] == user_id:
                return row
        return None

    def record_attendance(self, user_id, full_name, score, status="marked"):
        row = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
            "user_id": user_id,
            "name": full_name,
            "status": status,
            "score": f"{score:.3f}",
        }
        with self._lock:
            with self.attendance_file.open("a", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["timestamp", "user_id", "name", "status", "score"],
                )
                writer.writerow(row)
        return row

    def load_template(self, relative_path):
        image_path = self.users_file.parent / relative_path
        return self._load_image(image_path, grayscale=True)

    def load_features(self, relative_path):
        path = self.users_file.parent / relative_path
        if not path.exists():
            return None
        return np.load(str(path))

    def save_last_capture(self, raw_image=None, template_image=None):
        if raw_image is not None:
            self._save_image(self.captures_dir / "last_capture.png", raw_image)
        if template_image is not None:
            self._save_image(self.captures_dir / "last_template.png", template_image)

    def _read_payload_nolock(self):
        return json.loads(self.users_file.read_text())

    def _write_payload_nolock(self, payload):
        self.users_file.write_text(json.dumps(payload, indent=2))

    def _read_users_payload(self):
        with self._lock:
            return self._read_payload_nolock()

    def _save_features(self, path, feature_array):
        np.save(str(path), feature_array.astype(np.float32))

    def _save_image(self, path, image_array):
        if cv2 is not None:
            cv2.imwrite(str(path), image_array)
            return

        if Image is None:
            raise RuntimeError("Pillow is required to save enrollment images.")

        array = np.asarray(image_array)
        if array.ndim == 3 and array.shape[2] == 3:
            Image.fromarray(array.astype("uint8"), mode="RGB").save(path)
        else:
            Image.fromarray(array.astype("uint8"), mode="L").save(path)

    def _load_image(self, path, grayscale=False):
        if cv2 is not None:
            flag = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
            return cv2.imread(str(path), flag)

        if Image is None:
            raise RuntimeError("Pillow is required to load enrollment images.")

        image = Image.open(path)
        if grayscale:
            image = image.convert("L")
        else:
            image = image.convert("RGB")
        return np.array(image)
