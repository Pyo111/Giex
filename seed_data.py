"""
seed_data.py
Clears all tables and loads sample records so the system can be demonstrated.
WARNING: this deletes all existing data in giex_builders.
Run:  python seed_data.py
"""

import database as db


def clear_tables():
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table in ("project_file", "attendance", "assignment", "project", "worker"):
            cur.execute(f"TRUNCATE TABLE {table}")   # also resets AUTO_INCREMENT to 1
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()
    finally:
        conn.close()


def seed():
    clear_tables()

    workers = [
        ("Juan", "Dela Cruz", "Foreman", 900),
        ("Pedro", "Santos", "Mason", 700),
        ("Mark", "Reyes", "Carpenter", 700),
        ("Jose", "Garcia", "Steelman", 650),
        ("Ramon", "Bautista", "Laborer", 550),
        ("Liza", "Ramos", "Site Engineer", 1200),
    ]
    w = [db.add_worker(*x) for x in workers]

    p1 = db.add_project("2-Storey Residential Building", "Brgy. San Jose", "2026-10-01", "2027-03-31")
    p2 = db.add_project("Barangay Covered Court", "Brgy. Poblacion", "2026-11-02")

    a = {
        "juan_p1":  db.assign_worker(w[0], p1, "2026-10-01"),
        "pedro_p1": db.assign_worker(w[1], p1, "2026-10-01"),
        "mark_p1":  db.assign_worker(w[2], p1, "2026-10-05"),
        "jose_p2":  db.assign_worker(w[3], p2, "2026-11-02"),
        "ramon_p2": db.assign_worker(w[4], p2, "2026-11-02"),
        # Site engineers are the exception: they may handle several projects.
        "liza_p1":  db.assign_worker(w[5], p1, "2026-10-01"),
        "liza_p2":  db.assign_worker(w[5], p2, "2026-11-02"),
    }

    # One week of DTR (Nov 9-13, 2026)
    days = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    for d in days:
        db.time_in(a["juan_p1"], d, "07:55");  db.time_out(a["juan_p1"], d, "17:00")
        db.time_in(a["mark_p1"], d, "08:00");  db.time_out(a["mark_p1"], d, "17:00")
        db.time_in(a["jose_p2"], d, "07:50");  db.time_out(a["jose_p2"], d, "17:00")
    for d in days[:4]:
        db.time_in(a["pedro_p1"], d, "08:15"); db.time_out(a["pedro_p1"], d, "17:00")
    db.mark_status(a["pedro_p1"], days[4], "Absent")
    for d in days:
        db.time_in(a["ramon_p2"], d, "08:00")
        if d == "2026-11-11":
            db.time_out(a["ramon_p2"], d, "12:00")
            db.mark_status(a["ramon_p2"], d, "Half-day")
        else:
            db.time_out(a["ramon_p2"], d, "17:00")

    print("Sample data loaded into the giex_builders database.")


if __name__ == "__main__":
    seed()
