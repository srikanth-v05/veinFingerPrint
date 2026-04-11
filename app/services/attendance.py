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
                    features = self.vein.extract_features(template)
                except Exception as exc:
                    last_error = str(exc)
                    time.sleep(self.config["CAPTURE_DELAY_SECONDS"])
                    continue

                samples.append({"raw": frame, "template": template, "features": features})
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
            query_features = self.vein.extract_features(query_template)
            self.storage.save_last_capture(frame, query_template)

            # Collect (score, user) for every enrolled user
            ranked = []
            for user in users:
                sample_scores = []
                for sample in user.get("samples", []):
                    if "features_path" in sample:
                        ref_features = self.storage.load_features(sample["features_path"])
                        if ref_features is not None:
                            sample_scores.append(
                                self.vein.compare_features(query_features, ref_features)
                            )
                            continue
                    template = self.storage.load_template(sample["template_path"])
                    if template is not None:
                        sample_scores.append(
                            self.vein.compare_templates(query_template, template)
                        )

                if not sample_scores:
                    continue

                top = sorted(sample_scores, reverse=True)[: self.config["MATCH_TOP_K"]]
                ranked.append((sum(top) / len(top), user))

            if not ranked:
                return {
                    "ok": False,
                    "message": "No usable enrolled templates found.",
                    "score": 0.0,
                }

            ranked.sort(key=lambda x: x[0], reverse=True)
            best_score, best_user = ranked[0]

            # Hard threshold — must clear the minimum confidence bar
            if best_score < self.config["MATCH_THRESHOLD"]:
                return {
                    "ok": False,
                    "message": "No matching vein template found. Reposition the finger and try again.",
                    "score": round(best_score, 4),
                }

            # Margin check — best match must be clearly ahead of the runner-up
            # to avoid picking the wrong person when scores are neck-and-neck
            if len(ranked) >= 2:
                second_score = ranked[1][0]
                if (best_score - second_score) < self.config["MATCH_MARGIN"]:
                    return {
                        "ok": False,
                        "message": "Scan is ambiguous — vein pattern too close to multiple users. Reposition and try again.",
                        "score": round(best_score, 4),
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
