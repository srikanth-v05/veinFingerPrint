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

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("admin_authenticated"):
                return redirect(url_for("admin_login"))
            return view(*args, **kwargs)

        return wrapped

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
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if (
            username == current_app.config["ADMIN_USERNAME"]
            and password == current_app.config["ADMIN_PASSWORD"]
        ):
            session["admin_authenticated"] = True
            return redirect(url_for("admin_dashboard"))

        return render_template(
            "login.html",
            error="Invalid username or password.",
        ), 401

    @app.get("/admin/logout")
    def admin_logout():
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
        payload = request.get_json(silent=True) or request.form
        user_id = (payload.get("user_id") or "").strip()
        full_name = (payload.get("full_name") or "").strip()
        sample_count = payload.get(
            "sample_count", current_app.config["ENROLLMENT_SAMPLES"]
        )

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
        result = attendance_service().delete_user(user_id)
        return jsonify(result), 200 if result["ok"] else 404

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
