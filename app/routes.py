import hmac
import secrets
from functools import wraps
from pathlib import Path

from flask import (
    Response,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)


def register_routes(app):
    def storage_service():
        return current_app.extensions["storage_service"]

    def attendance_service():
        return current_app.extensions["attendance_service"]

    def camera_service():
        return current_app.extensions["camera_service"]

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("admin_authenticated"):
                return redirect(url_for("admin_login"))
            return view(*args, **kwargs)

        return wrapped

    def _get_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)
        return session["csrf_token"]

    def _validate_csrf():
        token = request.headers.get("X-CSRF-Token") or (request.form or {}).get("csrf_token", "")
        if not token or token != session.get("csrf_token"):
            return False
        return True

    @app.context_processor
    def inject_csrf():
        return {"csrf_token": _get_csrf_token()}

    @app.get("/")
    def attendance_home():
        storage = storage_service()
        return render_template(
            "index.html",
            recent_attendance=storage.list_recent_attendance(limit=8),
            status=attendance_service().system_status(),
        )

    @app.post("/api/attendance/mark")
    def mark_attendance():
        if not _validate_csrf():
            return jsonify({"ok": False, "message": "Invalid request."}), 403
        result = attendance_service().mark_attendance()
        return jsonify(result), 200 if result["ok"] else 400

    @app.get("/api/attendance/log")
    def attendance_log():
        limit = request.args.get("limit", default=10, type=int)
        return jsonify({"records": storage_service().list_recent_attendance(limit=limit)})

    @app.get("/admin/login")
    def admin_login():
        if session.get("admin_authenticated"):
            return redirect(url_for("admin_dashboard"))
        return render_template("login.html")

    @app.post("/admin/login")
    def admin_login_post():
        if not _validate_csrf():
            return render_template("login.html", error="Invalid request."), 403

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if (
            hmac.compare_digest(username, current_app.config["ADMIN_USERNAME"])
            and hmac.compare_digest(password, current_app.config["ADMIN_PASSWORD"])
        ):
            session["admin_authenticated"] = True
            return redirect(url_for("admin_dashboard"))

        return render_template(
            "login.html",
            error="Invalid username or password.",
        ), 401

    @app.post("/admin/logout")
    def admin_logout():
        if not _validate_csrf():
            return redirect(url_for("attendance_home"))
        session.clear()
        return redirect(url_for("attendance_home"))

    @app.get("/admin")
    @admin_required
    def admin_dashboard():
        storage = storage_service()
        return render_template(
            "admin.html",
            users=storage.list_users(),
            recent_attendance=storage.list_recent_attendance(limit=12),
            status=attendance_service().system_status(),
            default_samples=current_app.config["ENROLLMENT_SAMPLES"],
        )

    @app.post("/api/admin/enroll")
    @admin_required
    def enroll_user():
        if not _validate_csrf():
            return jsonify({"ok": False, "message": "Invalid request."}), 403

        payload = request.get_json(silent=True) or request.form
        user_id = (payload.get("user_id") or "").strip()
        full_name = (payload.get("full_name") or "").strip()
        sample_count = payload.get(
            "sample_count", current_app.config["ENROLLMENT_SAMPLES"]
        )

        if len(user_id) > 64:
            return jsonify({"ok": False, "message": "User ID too long (max 64 chars)."}), 400
        if len(full_name) > 128:
            return jsonify({"ok": False, "message": "Full name too long (max 128 chars)."}), 400

        try:
            sample_count = int(sample_count)
        except (TypeError, ValueError):
            sample_count = current_app.config["ENROLLMENT_SAMPLES"]

        result = attendance_service().enroll_user(
            user_id=user_id,
            full_name=full_name,
            sample_count=sample_count,
        )
        return jsonify(result), 200 if result["ok"] else 400

    @app.post("/api/admin/users/<user_id>/delete")
    @admin_required
    def delete_user(user_id):
        if not _validate_csrf():
            return jsonify({"ok": False, "message": "Invalid request."}), 403

        result = attendance_service().delete_user(user_id)
        return jsonify(result), 200 if result["ok"] else 404

    @app.get("/api/camera/stream")
    def camera_stream():
        # Stream is intentionally public — it backs the live-feed on the
        # public attendance page.  It only shows NIR finger images.
        # If stricter access control is needed, place the Pi behind a firewall
        # and restrict port 5000 to the local network.
        import time as _time
        cam = camera_service()

        def generate():
            while True:
                if cam.backend == "unavailable":
                    break  # don't spin on a missing camera
                try:
                    frame_bytes = cam.get_jpeg_frame()
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + frame_bytes
                        + b"\r\n"
                    )
                    _time.sleep(0.08)  # ~12 fps cap
                except GeneratorExit:
                    break
                except Exception:
                    _time.sleep(0.15)
                    continue

        return Response(
            generate(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache, no-store"},
        )

    @app.post("/api/camera/focus")
    def set_camera_focus():
        if not _validate_csrf():
            return jsonify({"ok": False, "message": "Invalid request."}), 403
        payload = request.get_json(silent=True) or {}
        try:
            value = float(payload.get("focus", 0))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "message": "Invalid focus value."}), 400
        camera_service().set_focus(value)
        return jsonify({"ok": True})

    @app.post("/api/camera/brightness")
    def set_camera_brightness():
        if not _validate_csrf():
            return jsonify({"ok": False, "message": "Invalid request."}), 403
        payload = request.get_json(silent=True) or {}
        try:
            value = int(payload.get("brightness", 0))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "message": "Invalid brightness value."}), 400
        camera_service().set_brightness(value)
        return jsonify({"ok": True})

    @app.get("/captures/<path:filename>")
    def capture_file(filename):
        capture_dir = Path(current_app.config["CAPTURES_DIR"])
        capture_path = capture_dir / filename
        if not capture_path.exists():
            return redirect(url_for("static", filename="img/preview-placeholder.svg"))
        return send_from_directory(capture_dir, filename)

    @app.get("/health")
    def healthcheck():
        return Response("ok", mimetype="text/plain")
