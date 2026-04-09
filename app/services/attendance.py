import time


class AttendanceService:
    def __init__(self, config, storage, camera, vein):
        self.config = config
        self.storage = storage
        self.camera = camera
        self.vein = vein

    def system_status(self):
        return {
            "camera_backend": self.camera.backend,
            "users_enrolled": len(self.storage.list_users()),
            "match_threshold": self.config["MATCH_THRESHOLD"],
            "sample_count": self.config["ENROLLMENT_SAMPLES"],
        }

    def enroll_user(self, user_id, full_name, sample_count):
        try:
            normalized_id = self.vein.normalize_user_id(user_id or full_name)
            if not normalized_id:
                return {"ok": False, "message": "Enter a valid user ID or full name."}
            if not full_name:
                return {"ok": False, "message": "Enter the user's full name."}
            if self.storage.get_user(normalized_id):
                return {
                    "ok": False,
                    "message": f"User '{normalized_id}' already exists. Delete it first if you want to re-enroll.",
                }

            sample_count = max(1, min(sample_count, 6))
            samples = []
            last_template = None
            last_frame = None
            attempts = 0
            last_error = None

            while len(samples) < sample_count and attempts < sample_count * 4:
                attempts += 1
                try:
                    frame = self.camera.capture_frame()
                    template = self.vein.extract_template(frame)
                except Exception as exc:
                    last_error = str(exc)
                    time.sleep(self.config["CAPTURE_DELAY_SECONDS"])
                    continue

                samples.append({"raw": frame, "template": template})
                last_frame = frame
                last_template = template
                if len(samples) < sample_count:
                    time.sleep(self.config["CAPTURE_DELAY_SECONDS"])

            if len(samples) < sample_count:
                message = (
                    "Could not capture enough clean samples. Keep the finger still and improve the NIR lighting."
                )
                if last_error:
                    message = f"{message} Last error: {last_error}"
                return {"ok": False, "message": message}

            user = self.storage.save_user(normalized_id, full_name, samples)
            self.storage.save_last_capture(last_frame, last_template)
            return {
                "ok": True,
                "message": f"Enrollment completed for {full_name}.",
                "user": user,
            }
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def delete_user(self, user_id):
        if not self.storage.delete_user(user_id):
            return {"ok": False, "message": "User not found."}
        return {"ok": True, "message": f"Removed user '{user_id}'."}

    def mark_attendance(self):
        try:
            users = self.storage.list_users()
            if not users:
                return {
                    "ok": False,
                    "message": "No users are enrolled yet. Add a user from the admin page first.",
                }

            frame = self.camera.capture_frame()
            query_template = self.vein.extract_template(frame)
            self.storage.save_last_capture(frame, query_template)

            best_user = None
            best_score = -1.0

            for user in users:
                user_scores = []
                for sample in user.get("samples", []):
                    template = self.storage.load_template(sample["template_path"])
                    if template is None:
                        continue
                    score = self.vein.compare_templates(query_template, template)
                    user_scores.append(score)

                if not user_scores:
                    continue

                top_scores = sorted(user_scores, reverse=True)[
                    : self.config["MATCH_TOP_K"]
                ]
                score = sum(top_scores) / len(top_scores)
                if score > best_score:
                    best_score = score
                    best_user = user

            if best_user is None or best_score < self.config["MATCH_THRESHOLD"]:
                return {
                    "ok": False,
                    "message": "No matching vein template found. Reposition the finger and try again.",
                    "score": round(max(best_score, 0.0), 4),
                }

            existing = self.storage.get_today_record(best_user["user_id"])
            if existing:
                return {
                    "ok": True,
                    "message": f"{best_user['full_name']} has already marked attendance today.",
                    "user": best_user,
                    "score": round(best_score, 4),
                    "record": existing,
                }

            record = self.storage.record_attendance(
                user_id=best_user["user_id"],
                full_name=best_user["full_name"],
                score=best_score,
            )
            return {
                "ok": True,
                "message": f"Attendance marked for {best_user['full_name']}.",
                "user": best_user,
                "score": round(best_score, 4),
                "record": record,
            }
        except Exception as exc:
            return {"ok": False, "message": str(exc)}
