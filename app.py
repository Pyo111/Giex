"""
app.py
GIEX Builders Database Management System - browser interface (Flask + MySQL).
Theme: black & yellow.
Run:  python app.py    then open http://127.0.0.1:5000
"""

import io
import os
import re
from datetime import date, timedelta

from flask import (Flask, flash, redirect, render_template, request,
                   send_file, session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import database as db

IS_VERCEL = bool(os.environ.get("VERCEL"))

app = Flask(__name__, static_folder="public/static")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.secret_key = os.environ.get("GIEX_SECRET_KEY", "giex-builders-dbms-local")
app.permanent_session_lifetime = timedelta(hours=8)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_VERCEL or os.environ.get("GIEX_HTTPS") == "1",
)

if IS_VERCEL and app.secret_key == "giex-builders-dbms-local":
    app.logger.warning(
        "GIEX_SECRET_KEY is not set. Add a long random value in Vercel "
        "environment variables so sessions cannot be forged.")

# Account created automatically the first time the app starts.
DEFAULT_ADMIN_USERNAME = os.environ.get("GIEX_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("GIEX_ADMIN_PASSWORD", "admin123")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,50}$")


# ---------------------------------------------------------------------
# Sign-in helpers
# ---------------------------------------------------------------------
PUBLIC_ENDPOINTS = {"login", "static", "healthz"}


def init_auth():
    """Create the admin table and seed the default account if it is missing."""
    db.ensure_admin_table()
    if not db.get_admin_by_username(DEFAULT_ADMIN_USERNAME):
        db.create_admin(DEFAULT_ADMIN_USERNAME,
                        generate_password_hash(DEFAULT_ADMIN_PASSWORD),
                        "Administrator")
        print(f"Default admin account created: {DEFAULT_ADMIN_USERNAME} "
              "(change the password after signing in)")


def safe_next_url(value):
    """Only allow redirects to local paths, never to another site."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return None


@app.before_request
def require_admin_sign_in():
    if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
        return None
    if not session.get("admin_id"):
        next_url = request.path if request.method == "GET" else None
        return redirect(url_for("login", next=next_url) if next_url
                        else url_for("login"))
    return None


try:
    init_auth()
    db.ensure_assignment_rules()
except db.errors.Error as exc:
    print(f"Database setup skipped (database unavailable): {exc}")


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def db_message(exc):
    return getattr(exc, "msg", str(exc))


def form_value(name, default=""):
    return request.form.get(name, default).strip()


def query_date(name):
    value = request.args.get(name, "").strip()
    return value if db.valid_date(value) else None


def query_int(name):
    value = request.args.get(name, "").strip()
    return int(value) if value.isdigit() else None


@app.context_processor
def inject_globals():
    return {
        "today_label": date.today().strftime("%B %d, %Y"),
        "today_iso": date.today().isoformat(),
        "is_site_engineer": db.is_site_engineer,
        "worker_roles": db.WORKER_ROLES,
        "db_name": db.DB_CONFIG.get("database", "giex_builders"),
        "server_label": ("Vercel cloud" if IS_VERCEL
                         else "Local server · 127.0.0.1:5000"),
    }


@app.get("/healthz")
def healthz():
    """Small public endpoint used to confirm the deployment can reach the DB."""
    try:
        db.test_connection()
    except db.errors.Error as exc:
        return {"status": "error", "detail": db_message(exc)}, 500
    return {"status": "ok", "database": db.server_flavor()}


# ---------------------------------------------------------------------
# Sign in / sign out
# ---------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_id"):
        return redirect(url_for("dashboard"))

    next_url = safe_next_url(request.values.get("next", ""))

    if request.method == "POST":
        username = form_value("username")
        password = request.form.get("password", "")
        try:
            admin = db.get_admin_by_username(username) if username else None
        except db.errors.Error as e:
            flash(f"Cannot reach the database: {db_message(e)}", "error")
            return render_template("login.html", next_url=next_url)

        if admin and check_password_hash(admin["password_hash"], password):
            session.clear()                       # new session on sign-in
            session.permanent = True
            session["admin_id"] = admin["admin_id"]
            session["admin_username"] = admin["username"]
            session["admin_name"] = admin["full_name"] or admin["username"]
            flash(f"Welcome back, {session['admin_name']}.", "success")
            return redirect(next_url or url_for("dashboard"))

        flash("Invalid username or password.", "error")

    return render_template("login.html", next_url=next_url)


@app.post("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


@app.get("/settings")
def settings():
    return redirect(url_for("settings_admins"))


@app.route("/settings/admins", methods=["GET", "POST"])
def settings_admins():
    if request.method == "POST":
        username = form_value("username")
        full_name = form_value("full_name")
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not USERNAME_PATTERN.fullmatch(username):
            flash("Username must be 3-50 characters using letters, numbers, "
                  "dots, dashes or underscores.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
        elif password != confirm:
            flash("The passwords do not match.", "error")
        elif db.get_admin_by_username(username):
            flash("That username is already taken.", "error")
        else:
            try:
                db.create_admin(username, generate_password_hash(password),
                                full_name or None)
                flash(f"Administrator '{username}' added. They can sign in now.",
                      "success")
            except db.errors.IntegrityError:
                flash("That username is already taken.", "error")
            except db.errors.Error as e:
                flash(f"Database error: {db_message(e)}", "error")
        return redirect(url_for("settings_admins"))

    return render_template("settings.html", active="settings", tab="admins",
                           admins=db.list_admins())


@app.route("/settings/password", methods=["GET", "POST"])
def settings_password():
    admin = db.get_admin(session["admin_id"])
    if not admin:
        session.clear()
        flash("Your account no longer exists. Please sign in again.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if not check_password_hash(admin["password_hash"], current):
            flash("Your current password is incorrect.", "error")
        elif len(new) < 8:
            flash("The new password must be at least 8 characters long.", "error")
        elif new != confirm:
            flash("The new passwords do not match.", "error")
        elif new == current:
            flash("The new password must be different from the current one.", "error")
        else:
            db.update_admin_password(admin["admin_id"],
                                     generate_password_hash(new))
            flash("Password updated successfully.", "success")
        return redirect(url_for("settings_password"))

    return render_template("settings.html", active="settings", tab="password",
                           admin=admin)


# ---------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------
@app.route("/")
def dashboard():
    dtr = db.get_dtr()
    recent = list(reversed(dtr))[:8]
    stats = [
        ("Workers", len(db.list_workers()), "Registered workers"),
        ("Projects", len(db.list_projects()), "Construction projects"),
        ("Assignments", len(db.list_assignments()), "Worker-project links"),
        ("DTR Records", len(dtr), "Attendance entries"),
    ]
    return render_template("dashboard.html", active="dashboard",
                           stats=stats, recent=recent)


# ---------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------
@app.route("/workers")
def workers():
    q = request.args.get("q", "").strip()
    rows = db.search_workers(q) if q else db.list_workers()
    return render_template("workers.html", active="workers",
                           workers=rows, q=q)


@app.post("/workers/add")
def worker_add():
    first, last = form_value("first_name"), form_value("last_name")
    role, rate_text = form_value("role"), form_value("worker_rate")
    if not (first and last and role and rate_text):
        flash("Please fill in all worker fields.", "error")
        return redirect(url_for("workers"))
    if role not in db.WORKER_ROLES:
        flash("Choose a valid worker role from the list.", "error")
        return redirect(url_for("workers"))
    try:
        rate = float(rate_text)
        if rate < 0:
            raise ValueError
        wid = db.add_worker(first, last, role, rate)
        flash(f"Worker added with ID {wid}.", "success")
    except ValueError:
        flash("Daily rate must be a non-negative number.", "error")
    except db.errors.IntegrityError as e:
        flash(f"Database rule violated: {db_message(e)}", "error")
    except db.errors.Error as e:
        flash(f"Database error: {db_message(e)}", "error")
    return redirect(url_for("workers"))


@app.route("/workers/<int:worker_id>/edit", methods=["GET", "POST"])
def worker_edit(worker_id):
    worker = db.get_worker(worker_id)
    if not worker:
        flash("Worker not found.", "error")
        return redirect(url_for("workers"))

    if request.method == "POST":
        first, last = form_value("first_name"), form_value("last_name")
        role, rate_text = form_value("role"), form_value("worker_rate")
        if not (first and last and role and rate_text):
            flash("Please fill in all worker fields.", "error")
        elif role not in db.WORKER_ROLES and role != worker["role"]:
            flash("Choose a valid worker role from the list.", "error")
        else:
            try:
                rate = float(rate_text)
            except ValueError:
                rate = None
            if rate is None or rate < 0:
                flash("Daily rate must be a non-negative number.", "error")
            else:
                try:
                    db.update_worker(worker_id, first, last, role, rate)
                    flash("Worker updated.", "success")
                    return redirect(url_for("workers"))
                except ValueError as e:
                    flash(str(e), "error")
                except db.errors.Error as e:
                    flash(f"Database error: {db_message(e)}", "error")
        worker = db.get_worker(worker_id)

    return render_template("worker_edit.html", active="workers", worker=worker)


@app.post("/workers/<int:worker_id>/delete")
def worker_delete(worker_id):
    try:
        if db.delete_worker(worker_id):
            flash("Worker deleted.", "success")
        else:
            flash("Worker not found.", "error")
    except db.errors.Error as e:
        flash(f"Database error: {db_message(e)}", "error")
    return redirect(url_for("workers"))


# ---------------------------------------------------------------------
# Projects and project files
# ---------------------------------------------------------------------
@app.route("/projects")
def projects():
    return render_template("projects.html", active="projects",
                           projects=db.list_projects())


@app.post("/projects/add")
def project_add():
    name, location = form_value("project_name"), form_value("location")
    start, end = form_value("start_date"), form_value("end_date") or None
    if not (name and location and db.valid_date(start)):
        flash("Project name, location and a valid start date are required.", "error")
        return redirect(url_for("projects"))
    if end and not db.valid_date(end):
        flash("End date is not valid.", "error")
        return redirect(url_for("projects"))
    if end and end < start:
        flash("End date cannot be earlier than the start date.", "error")
        return redirect(url_for("projects"))
    try:
        pid = db.add_project(name, location, start, end)
        flash(f"Project added with ID {pid}.", "success")
    except db.errors.IntegrityError as e:
        flash(f"Database rule violated: {db_message(e)}", "error")
    except db.errors.Error as e:
        flash(f"Database error: {db_message(e)}", "error")
    return redirect(url_for("projects"))


@app.route("/projects/<int:project_id>/edit", methods=["GET", "POST"])
def project_edit(project_id):
    project = db.get_project(project_id)
    if not project:
        flash("Project not found.", "error")
        return redirect(url_for("projects"))

    if request.method == "POST":
        name, location = form_value("project_name"), form_value("location")
        start = form_value("start_date")
        end = form_value("end_date") or None
        if not (name and location and db.valid_date(start)):
            flash("Project name, location and a valid start date are required.", "error")
        elif end and not db.valid_date(end):
            flash("End date is not valid.", "error")
        elif end and end < start:
            flash("End date cannot be earlier than the start date.", "error")
        else:
            try:
                db.update_project(project_id, name, location, start, end)
                flash("Project updated.", "success")
                return redirect(url_for("projects"))
            except db.errors.Error as e:
                flash(f"Database error: {db_message(e)}", "error")
        project = db.get_project(project_id)

    return render_template("project_edit.html", active="projects", project=project)


@app.post("/projects/<int:project_id>/delete")
def project_delete(project_id):
    try:
        if db.delete_project(project_id):
            flash("Project deleted.", "success")
        else:
            flash("Project not found.", "error")
    except db.errors.Error as e:
        flash(f"Database error: {db_message(e)}", "error")
    return redirect(url_for("projects"))


@app.route("/projects/<int:project_id>/files")
def project_files(project_id):
    project = db.get_project(project_id)
    if not project:
        flash("Project not found.", "error")
        return redirect(url_for("projects"))
    return render_template("files.html", active="projects", project=project,
                           files=db.list_project_files(project_id))


@app.post("/projects/<int:project_id>/files/upload")
def project_file_upload(project_id):
    file = request.files.get("file")
    description = form_value("description")
    if not db.get_project(project_id):
        flash("Project not found.", "error")
    elif not file or not file.filename:
        flash("Choose a file to upload.", "error")
    else:
        try:
            fid = db.upload_project_file_data(project_id, file.filename,
                                              file.read(), description)
            flash(f"File stored with ID {fid}.", "success")
        except db.errors.Error as e:
            flash(f"Database error: {db_message(e)}", "error")
    return redirect(url_for("project_files", project_id=project_id))


@app.get("/files/<int:file_id>/download")
def project_file_download(file_id):
    row = db.get_project_file(file_id)
    if not row:
        flash("File not found.", "error")
        return redirect(url_for("projects"))
    return send_file(io.BytesIO(row["file_data"]), as_attachment=True,
                     download_name=row["file_name"])


@app.post("/files/<int:file_id>/delete")
def project_file_delete(file_id):
    row = db.get_project_file(file_id)
    if not row:
        flash("File not found.", "error")
        return redirect(url_for("projects"))
    project_id = row["project_id"]
    try:
        db.delete_project_file(file_id)
        flash("File deleted.", "success")
    except db.errors.Error as e:
        flash(f"Database error: {db_message(e)}", "error")
    return redirect(url_for("project_files", project_id=project_id))


# ---------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------
@app.route("/assignments")
def assignments():
    rows = db.list_assignments()
    return render_template("assignments.html", active="assignments",
                           assignments=rows,
                           workers=db.list_workers(),
                           projects=db.list_projects(),
                           assigned_ids={a["worker_id"] for a in rows},
                           active_ids=db.active_assigned_worker_ids(),
                           today=date.today().isoformat())


@app.post("/assignments/add")
def assignment_add():
    worker_id = request.form.get("worker_id", type=int)
    project_id = request.form.get("project_id", type=int)
    assign_date = form_value("assignment_date")
    if not worker_id or not project_id or not db.valid_date(assign_date):
        flash("Choose a worker, a project and a valid assignment date.", "error")
    elif not db.get_worker(worker_id) or not db.get_project(project_id):
        flash("Worker or project not found.", "error")
    else:
        try:
            aid = db.assign_worker(worker_id, project_id, assign_date)
            flash(f"Assignment created with ID {aid}.", "success")
        except ValueError as e:
            flash(str(e), "error")
        except db.errors.IntegrityError:
            flash("That worker is already assigned to that project.", "error")
        except db.errors.Error as e:
            flash(f"Database error: {db_message(e)}", "error")
    return redirect(url_for("assignments"))


@app.post("/assignments/<int:assignment_id>/delete")
def assignment_delete(assignment_id):
    try:
        if db.delete_assignment(assignment_id):
            flash("Assignment removed.", "success")
        else:
            flash("Assignment not found.", "error")
    except db.errors.Error as e:
        flash(f"Database error: {db_message(e)}", "error")
    return redirect(url_for("assignments"))


# ---------------------------------------------------------------------
# DTR attendance
# ---------------------------------------------------------------------
@app.route("/attendance")
def attendance():
    worker_id = query_int("worker_id")
    project_id = query_int("project_id")
    date_from = query_date("date_from")
    date_to = query_date("date_to")
    rows = db.get_dtr(worker_id=worker_id, project_id=project_id,
                      date_from=date_from, date_to=date_to)
    return render_template("attendance.html", active="attendance",
                           rows=rows,
                           workers=db.list_workers(),
                           projects=db.list_projects(),
                           assignments=db.list_assignments(),
                           today=date.today().isoformat(),
                           filters={"worker_id": worker_id,
                                    "project_id": project_id,
                                    "date_from": date_from,
                                    "date_to": date_to})


@app.post("/attendance/time-in")
def attendance_time_in():
    assignment_id = request.form.get("assignment_id", type=int)
    att_date = form_value("attendance_date")
    time_value = form_value("time_in")
    if not assignment_id or not db.valid_date(att_date) or not db.valid_time(time_value):
        flash("Choose an assignment, a valid date and a valid time.", "error")
    elif not db.get_assignment(assignment_id):
        flash("Assignment not found.", "error")
    else:
        try:
            _, status = db.time_in(assignment_id, att_date, time_value)
            flash(f"Time-in recorded. Status: {status}.", "success")
        except db.errors.IntegrityError:
            flash("A DTR entry already exists for that assignment and date.", "error")
        except db.errors.Error as e:
            flash(f"Database error: {db_message(e)}", "error")
    return redirect(url_for("attendance"))


@app.post("/attendance/time-out")
def attendance_time_out():
    assignment_id = request.form.get("assignment_id", type=int)
    att_date = form_value("attendance_date")
    time_value = form_value("time_out")
    if not assignment_id or not db.valid_date(att_date) or not db.valid_time(time_value):
        flash("Choose an assignment, a valid date and a valid time.", "error")
    else:
        try:
            db.time_out(assignment_id, att_date, time_value)
            flash("Time-out recorded.", "success")
        except ValueError as e:
            flash(str(e), "error")
        except db.errors.Error as e:
            flash(f"Database error: {db_message(e)}", "error")
    return redirect(url_for("attendance"))


@app.post("/attendance/status")
def attendance_status():
    assignment_id = request.form.get("assignment_id", type=int)
    att_date = form_value("attendance_date")
    status = form_value("status")
    if not assignment_id or not db.valid_date(att_date) or \
            status not in ("Absent", "On Leave", "Half-day"):
        flash("Choose an assignment, a valid date and a status.", "error")
    elif not db.get_assignment(assignment_id):
        flash("Assignment not found.", "error")
    else:
        try:
            db.mark_status(assignment_id, att_date, status)
            flash(f"Marked as {status}.", "success")
        except db.errors.Error as e:
            flash(f"Database error: {db_message(e)}", "error")
    return redirect(url_for("attendance"))


# ---------------------------------------------------------------------
# Payroll report
# ---------------------------------------------------------------------
@app.route("/payroll")
def payroll():
    date_from = query_date("date_from") or date.today().replace(day=1).isoformat()
    date_to = query_date("date_to") or date.today().isoformat()
    project_id = query_int("project_id")
    rows = []
    totals = {"hours": 0.0, "pay": 0.0}
    if date_from > date_to:
        flash("The period start is after the period end.", "error")
    else:
        rows = db.payroll_summary(date_from, date_to, project_id)
        totals = {
            "hours": sum(float(r["paid_hours"] or 0) for r in rows),
            "pay": sum(float(r["gross_pay"] or 0) for r in rows),
        }
    return render_template("payroll.html", active="payroll",
                           rows=rows, projects=db.list_projects(),
                           date_from=date_from, date_to=date_to,
                           project_id=project_id, totals=totals)


# ---------------------------------------------------------------------
# Development server
# ---------------------------------------------------------------------
if __name__ == "__main__":
    try:
        db.test_connection()
    except db.errors.Error as e:
        print("Cannot connect to the MySQL database.")
        print("Check DB_CONFIG in database.py and make sure MySQL is running.")
        print(f"Details: {e}")
    else:
        init_auth()
        db.ensure_assignment_rules()
        print("GIEX Builders web system running at http://127.0.0.1:5000")
        app.run(host="127.0.0.1", port=5000, debug=False)
