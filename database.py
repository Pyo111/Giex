"""
database.py
Data-access layer for the GIEX Builders Database Management System (MySQL).
All SQL lives here; main.py only calls these functions.

Requires:  pip install mysql-connector-python
Before first run: execute schema_mysql.sql in MySQL (creates the database and tables).
"""

import os
import tempfile
from datetime import datetime, timedelta

import mysql.connector
from mysql.connector import errors  # re-exported for main.py


# ---------------------------------------------------------------------
# CONNECTION SETTINGS
# Local development: copy .env.example to .env and fill in your values.
# Vercel: set the same names under Project -> Settings -> Environment Variables.
# ---------------------------------------------------------------------
def _load_dotenv():
    """Load KEY=VALUE pairs from a .env file next to this module (local only)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError:
        pass


_load_dotenv()


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = _env_int("DB_PORT", 3306)
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "giex_builders")
DB_TIME_ZONE = os.environ.get("DB_TIME_ZONE", "+08:00").strip()


def _ssl_config():
    """Build TLS settings. Hosted MySQL/TiDB requires TLS; localhost does not."""
    mode = os.environ.get("DB_SSL_MODE", "").strip().upper()
    if not mode:
        local = DB_HOST.lower() in ("localhost", "127.0.0.1", "::1")
        mode = "DISABLED" if local else "REQUIRED"

    if mode == "DISABLED":
        return {"ssl_disabled": True}

    config = {"ssl_disabled": False}
    ca_path = os.environ.get("DB_SSL_CA", "").strip()

    # Vercel cannot ship a CA file easily, so accept PEM text as well.
    ca_pem = os.environ.get("DB_SSL_CA_PEM", "").strip()
    if ca_pem and not ca_path:
        ca_path = os.path.join(tempfile.gettempdir(), "giex-db-ca.pem")
        with open(ca_path, "w", encoding="utf-8") as handle:
            handle.write(ca_pem)

    if ca_path:
        config["ssl_ca"] = ca_path

    if mode in ("VERIFY_CA", "VERIFY_IDENTITY"):
        config["ssl_verify_cert"] = True
        config["ssl_verify_identity"] = mode == "VERIFY_IDENTITY"
    else:  # REQUIRED: encrypted, but the server certificate is not verified
        config["ssl_verify_cert"] = False
        config["ssl_verify_identity"] = False
    return config


DB_CONFIG = {
    "host": DB_HOST,
    "port": DB_PORT,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "database": DB_NAME,
    "connection_timeout": 10,
    "charset": "utf8mb4",
    **_ssl_config(),
}
if DB_TIME_ZONE:
    DB_CONFIG["time_zone"] = DB_TIME_ZONE

STANDARD_START = "08:00"   # time-in after this is auto-marked "Late"
REGULAR_HOURS = 8          # hours in one paid day

# Roles offered in the web interface. Site engineers are the only role that
# may hold assignments on more than one project.
WORKER_ROLES = (
    "Foreman",
    "Site Engineer",
    "Mason",
    "Carpenter",
    "Steelman",
    "Electrician",
    "Plumber",
    "Painter",
    "Welder",
    "Heavy Equipment Operator",
    "Safety Officer",
    "Laborer",
)


# ---------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------
def get_connection(database=True):
    config = dict(DB_CONFIG)
    if not database:
        config.pop("database", None)
    return mysql.connector.connect(**config)


_SERVER_FLAVOR = None


def server_flavor():
    """Return 'tidb' or 'mysql' (cached per process)."""
    global _SERVER_FLAVOR
    if _SERVER_FLAVOR is None:
        try:
            row = _fetch_one("SELECT VERSION() AS version")
        except mysql.connector.Error:
            row = None
        version = str((row or {}).get("version") or "")
        _SERVER_FLAVOR = "tidb" if "tidb" in version.lower() else "mysql"
    return _SERVER_FLAVOR


def test_connection():
    """Raises an error if MySQL cannot be reached or the tables are missing."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM worker")
        cur.fetchall()
    finally:
        conn.close()


def _execute(sql, params=()):
    """INSERT / UPDATE / DELETE. Returns (lastrowid, rowcount)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid, cur.rowcount
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _fetch_all(sql, params=()):
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


def _fetch_one(sql, params=()):
    rows = _fetch_all(sql, params)
    return rows[0] if rows else None


def to_hhmm(value):
    """MySQL TIME columns come back as timedelta; convert to 'HH:MM'."""
    if value is None:
        return None
    if isinstance(value, timedelta):
        total_min = int(value.total_seconds()) // 60
        return f"{total_min // 60:02d}:{total_min % 60:02d}"
    return str(value)[:5]


# ---------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------
def valid_date(text):
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


def valid_time(text):
    try:
        datetime.strptime(text, "%H:%M")
        return True
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------
# ADMIN (sign-in accounts)
# ---------------------------------------------------------------------
def ensure_admin_table():
    """Create the admin table on first run so sign-in works without re-importing the schema."""
    _execute(
        """CREATE TABLE IF NOT EXISTS admin (
               admin_id      INT UNSIGNED NOT NULL AUTO_INCREMENT,
               username      VARCHAR(50)  NOT NULL,
               password_hash VARCHAR(255) NOT NULL,
               full_name     VARCHAR(100) NULL,
               created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
               PRIMARY KEY (admin_id),
               UNIQUE KEY uq_admin_username (username)
           ) ENGINE = InnoDB"""
    )


def list_admins():
    return _fetch_all(
        "SELECT admin_id, username, full_name, created_at FROM admin ORDER BY admin_id"
    )


def get_admin(admin_id):
    return _fetch_one("SELECT * FROM admin WHERE admin_id = %s", (admin_id,))


def get_admin_by_username(username):
    return _fetch_one("SELECT * FROM admin WHERE username = %s", (username,))


def create_admin(username, password_hash, full_name=None):
    rowid, _ = _execute(
        "INSERT INTO admin (username, password_hash, full_name) VALUES (%s, %s, %s)",
        (username, password_hash, full_name),
    )
    return rowid


def update_admin_password(admin_id, password_hash):
    _, count = _execute(
        "UPDATE admin SET password_hash = %s WHERE admin_id = %s",
        (password_hash, admin_id),
    )
    return count


# ---------------------------------------------------------------------
# WORKER
# ---------------------------------------------------------------------
def add_worker(first_name, last_name, role, worker_rate):
    rowid, _ = _execute(
        "INSERT INTO worker (first_name, last_name, role, worker_rate) VALUES (%s, %s, %s, %s)",
        (first_name, last_name, role, worker_rate),
    )
    return rowid


def list_workers():
    return _fetch_all("SELECT * FROM worker ORDER BY worker_id")


def get_worker(worker_id):
    return _fetch_one("SELECT * FROM worker WHERE worker_id = %s", (worker_id,))


def search_workers(keyword):
    like = f"%{keyword}%"
    return _fetch_all(
        """SELECT * FROM worker
           WHERE first_name LIKE %s OR last_name LIKE %s OR role LIKE %s
           ORDER BY last_name""",
        (like, like, like),
    )


def update_worker(worker_id, first_name, last_name, role, worker_rate):
    current = get_worker(worker_id)
    if (current and is_site_engineer(current["role"])
            and not is_site_engineer(role)
            and worker_active_assignment_count(worker_id) > 1):
        raise ValueError(
            "This worker has more than one ongoing project. Only site engineers "
            "can hold multiple ongoing projects, so reassign the worker first."
        )
    _, count = _execute(
        """UPDATE worker SET first_name = %s, last_name = %s, role = %s, worker_rate = %s
           WHERE worker_id = %s""",
        (first_name, last_name, role, worker_rate, worker_id),
    )
    return count


def delete_worker(worker_id):
    return _execute("DELETE FROM worker WHERE worker_id = %s", (worker_id,))[1]


# ---------------------------------------------------------------------
# PROJECT
# ---------------------------------------------------------------------
def add_project(project_name, location, start_date, end_date=None):
    rowid, _ = _execute(
        "INSERT INTO project (project_name, location, start_date, end_date) VALUES (%s, %s, %s, %s)",
        (project_name, location, start_date, end_date),
    )
    return rowid


def list_projects():
    return _fetch_all("SELECT * FROM project ORDER BY project_id")


def get_project(project_id):
    return _fetch_one("SELECT * FROM project WHERE project_id = %s", (project_id,))


def update_project(project_id, project_name, location, start_date, end_date):
    _, count = _execute(
        """UPDATE project SET project_name = %s, location = %s, start_date = %s, end_date = %s
           WHERE project_id = %s""",
        (project_name, location, start_date, end_date, project_id),
    )
    return count


def delete_project(project_id):
    return _execute("DELETE FROM project WHERE project_id = %s", (project_id,))[1]


# ---------------------------------------------------------------------
# ASSIGNMENT
# ---------------------------------------------------------------------
def is_site_engineer(role):
    """Site engineers may hold assignments on more than one project."""
    text = (role or "").lower()
    return "engineer" in text or "engr" in text


def worker_active_assignment_count(worker_id):
    """Number of assignments whose project has not finished yet."""
    row = _fetch_one(
        """SELECT COUNT(*) AS total
           FROM assignment a
           JOIN project p ON p.project_id = a.project_id
           WHERE a.worker_id = %s
             AND (p.end_date IS NULL OR p.end_date >= CURDATE())""",
        (worker_id,),
    )
    return int(row["total"]) if row else 0


def active_assigned_worker_ids():
    """Worker IDs currently attached to an ongoing project."""
    rows = _fetch_all(
        """SELECT DISTINCT a.worker_id
           FROM assignment a
           JOIN project p ON p.project_id = a.project_id
           WHERE p.end_date IS NULL OR p.end_date >= CURDATE()"""
    )
    return {row["worker_id"] for row in rows}


def _trigger_exists(name):
    row = _fetch_one(
        """SELECT COUNT(*) AS total FROM information_schema.TRIGGERS
           WHERE TRIGGER_SCHEMA = DATABASE() AND TRIGGER_NAME = %s""",
        (name,),
    )
    return bool(row and row["total"])


def ensure_assignment_rules():
    """Install database triggers for the one-active-assignment-per-worker rule.

    A worker can be assigned to a new project after the current project's end
    date has passed. Site engineers (roles containing "Engineer" or "Engr.")
    may hold several ongoing projects at once.

    TiDB (TiDB Cloud Starter) does not support triggers. There the rule is
    still enforced by assign_worker()/update_worker() in this module.
    """
    triggers = {
        "trg_assignment_single_project": """
            CREATE TRIGGER trg_assignment_single_project
            BEFORE INSERT ON assignment
            FOR EACH ROW
            BEGIN
                DECLARE worker_role VARCHAR(50);
                DECLARE active_count INT;

                SELECT role INTO worker_role
                FROM worker WHERE worker_id = NEW.worker_id;
                SELECT COUNT(*) INTO active_count
                FROM assignment a
                JOIN project p ON p.project_id = a.project_id
                WHERE a.worker_id = NEW.worker_id
                  AND (p.end_date IS NULL OR p.end_date >= CURDATE());

                IF active_count > 0
                   AND LOCATE('engineer', LOWER(worker_role)) = 0
                   AND LOCATE('engr', LOWER(worker_role)) = 0 THEN
                    SIGNAL SQLSTATE '45000'
                        SET MESSAGE_TEXT = 'Only site engineers can be assigned to more than one ongoing project.';
                END IF;
            END
        """,
        "trg_worker_single_project": """
            CREATE TRIGGER trg_worker_single_project
            BEFORE UPDATE ON worker
            FOR EACH ROW
            BEGIN
                IF (LOCATE('engineer', LOWER(OLD.role)) > 0
                    OR LOCATE('engr', LOWER(OLD.role)) > 0)
                   AND LOCATE('engineer', LOWER(NEW.role)) = 0
                   AND LOCATE('engr', LOWER(NEW.role)) = 0
                   AND (SELECT COUNT(*)
                        FROM assignment a
                        JOIN project p ON p.project_id = a.project_id
                        WHERE a.worker_id = NEW.worker_id
                          AND (p.end_date IS NULL OR p.end_date >= CURDATE())) > 1 THEN
                    SIGNAL SQLSTATE '45000'
                        SET MESSAGE_TEXT = 'This worker has more than one ongoing project; only site engineers can hold multiple ongoing projects.';
                END IF;
            END
        """,
    }
    if os.environ.get("GIEX_DB_FLAVOR", "").strip().lower() == "tidb" \
            or server_flavor() == "tidb":
        print("TiDB detected: triggers are not supported, so assignment rules "
              "are enforced by the application instead.")
        return

    refresh = os.environ.get("GIEX_REFRESH_TRIGGERS", "").lower() in (
        "1", "true", "yes")
    try:
        for name, sql in triggers.items():
            if refresh:
                _execute(f"DROP TRIGGER IF EXISTS {name}")
            elif _trigger_exists(name):
                continue
            _execute(sql)
    except mysql.connector.Error as exc:
        print(f"Warning: could not install assignment triggers: {exc}")


def assign_worker(worker_id, project_id, assignment_date):
    worker = get_worker(worker_id)
    if worker is None:
        raise ValueError("Worker not found.")

    duplicate = _fetch_one(
        "SELECT assignment_id FROM assignment WHERE worker_id = %s AND project_id = %s",
        (worker_id, project_id),
    )
    if duplicate:
        raise ValueError("That worker is already assigned to that project.")

    if not is_site_engineer(worker["role"]):
        active = _fetch_one(
            """SELECT p.project_name
               FROM assignment a
               JOIN project p ON p.project_id = a.project_id
               WHERE a.worker_id = %s
                 AND (p.end_date IS NULL OR p.end_date >= CURDATE())
               ORDER BY a.assignment_id
               LIMIT 1""",
            (worker_id,),
        )
        if active:
            raise ValueError(
                f"{worker['first_name']} {worker['last_name']} is still assigned "
                f"to '{active['project_name']}', which is ongoing. Assign another "
                "project after that project's end date."
            )

    rowid, _ = _execute(
        "INSERT INTO assignment (worker_id, project_id, assignment_date) VALUES (%s, %s, %s)",
        (worker_id, project_id, assignment_date),
    )
    return rowid


def list_assignments(project_id=None):
    sql = """SELECT a.assignment_id, a.assignment_date,
                    w.worker_id, CONCAT(w.first_name, ' ', w.last_name) AS worker_name, w.role,
                    p.project_id, p.project_name, p.end_date,
                    CASE WHEN p.end_date IS NULL OR p.end_date >= CURDATE()
                         THEN 'Ongoing' ELSE 'Completed' END AS project_status
             FROM assignment a
             JOIN worker  w ON w.worker_id  = a.worker_id
             JOIN project p ON p.project_id = a.project_id"""
    params = ()
    if project_id is not None:
        sql += " WHERE a.project_id = %s"
        params = (project_id,)
    sql += " ORDER BY a.assignment_id"
    return _fetch_all(sql, params)


def get_assignment(assignment_id):
    return _fetch_one("SELECT * FROM assignment WHERE assignment_id = %s", (assignment_id,))


def delete_assignment(assignment_id):
    return _execute("DELETE FROM assignment WHERE assignment_id = %s", (assignment_id,))[1]


# ---------------------------------------------------------------------
# ATTENDANCE (DTR)
# ---------------------------------------------------------------------
def time_in(assignment_id, attendance_date, time_value):
    """Record a time-in. Marks 'Late' automatically after STANDARD_START."""
    status = "Late" if time_value > STANDARD_START else "Present"
    rowid, _ = _execute(
        """INSERT INTO attendance (assignment_id, attendance_date, time_in, attendance_status)
           VALUES (%s, %s, %s, %s)""",
        (assignment_id, attendance_date, time_value, status),
    )
    return rowid, status


def time_out(assignment_id, attendance_date, time_value):
    row = _fetch_one(
        """SELECT attendance_id, time_in FROM attendance
           WHERE assignment_id = %s AND attendance_date = %s""",
        (assignment_id, attendance_date),
    )
    if row is None:
        raise ValueError("No time-in found for that assignment and date.")
    if row["time_in"] is not None and time_value <= to_hhmm(row["time_in"]):
        raise ValueError("Time-out must be later than time-in.")
    _execute("UPDATE attendance SET time_out = %s WHERE attendance_id = %s",
             (time_value, row["attendance_id"]))
    return row["attendance_id"]


def mark_status(assignment_id, attendance_date, status):
    """Record a day with no time-in/out (Absent, On Leave) or override a status."""
    _execute(
        """INSERT INTO attendance (assignment_id, attendance_date, attendance_status)
           VALUES (%s, %s, %s)
           ON DUPLICATE KEY UPDATE attendance_status = VALUES(attendance_status)""",
        (assignment_id, attendance_date, status),
    )


def get_dtr(worker_id=None, project_id=None, date_from=None, date_to=None):
    sql = "SELECT * FROM v_dtr WHERE 1 = 1"
    params = []
    if worker_id is not None:
        sql += " AND worker_id = %s"
        params.append(worker_id)
    if project_id is not None:
        sql += " AND project_id = %s"
        params.append(project_id)
    if date_from:
        sql += " AND attendance_date >= %s"
        params.append(date_from)
    if date_to:
        sql += " AND attendance_date <= %s"
        params.append(date_to)
    sql += " ORDER BY attendance_date, worker_id"
    rows = _fetch_all(sql, params)
    for r in rows:
        r["time_in"] = to_hhmm(r["time_in"])
        r["time_out"] = to_hhmm(r["time_out"])
    return rows


def payroll_summary(date_from, date_to, project_id=None):
    """Total hours and gross pay per worker (pay = paid hours / 8 x daily rate, max 8 hrs/day)."""
    sql = """SELECT worker_id, worker_name, role, worker_rate,
                    SUM(attendance_status IN ('Present','Late','Half-day')) AS days_worked,
                    SUM(attendance_status = 'Absent')                       AS days_absent,
                    ROUND(SUM(total_hours), 2)                              AS total_hours,
                    ROUND(SUM(LEAST(total_hours, %s)), 2)                   AS paid_hours,
                    ROUND(SUM(LEAST(total_hours, %s)) / %s * worker_rate, 2) AS gross_pay
             FROM v_dtr
             WHERE attendance_date BETWEEN %s AND %s"""
    params = [REGULAR_HOURS, REGULAR_HOURS, REGULAR_HOURS, date_from, date_to]
    if project_id is not None:
        sql += " AND project_id = %s"
        params.append(project_id)
    sql += " GROUP BY worker_id, worker_name, role, worker_rate ORDER BY worker_name"
    return _fetch_all(sql, params)


# ---------------------------------------------------------------------
# PROJECT FILES
# ---------------------------------------------------------------------
def upload_project_file(project_id, path, description=""):
    with open(path, "rb") as f:
        data = f.read()
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lstrip(".").lower()
    rowid, _ = _execute(
        """INSERT INTO project_file (project_id, file_name, file_type, description, file_data)
           VALUES (%s, %s, %s, %s, %s)""",
        (project_id, name, ext, description, data),
    )
    return rowid


def list_project_files(project_id):
    return _fetch_all(
        """SELECT file_id, file_name, file_type, description, uploaded_on,
                  LENGTH(file_data) AS size_bytes
           FROM project_file WHERE project_id = %s ORDER BY file_id""",
        (project_id,),
    )


def download_project_file(file_id, output_dir):
    row = _fetch_one("SELECT file_name, file_data FROM project_file WHERE file_id = %s", (file_id,))
    if row is None:
        raise ValueError("File not found.")
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, row["file_name"])
    with open(out_path, "wb") as f:
        f.write(row["file_data"])
    return out_path


def upload_project_file_data(project_id, file_name, data, description=""):
    """Store a file supplied as raw bytes (used by the web interface)."""
    ext = os.path.splitext(file_name)[1].lstrip(".").lower()
    rowid, _ = _execute(
        """INSERT INTO project_file (project_id, file_name, file_type, description, file_data)
           VALUES (%s, %s, %s, %s, %s)""",
        (project_id, file_name, ext, description, data),
    )
    return rowid


def get_project_file(file_id):
    """Return one project file row including its bytes, or None."""
    return _fetch_one(
        """SELECT file_id, project_id, file_name, file_type, description,
                  uploaded_on, file_data
           FROM project_file WHERE file_id = %s""",
        (file_id,),
    )


def delete_project_file(file_id):
    return _execute("DELETE FROM project_file WHERE file_id = %s", (file_id,))[1]
