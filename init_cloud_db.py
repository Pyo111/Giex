"""
init_cloud_db.py
Create the GIEX Builders schema in a hosted MySQL-compatible database
(MySQL, MariaDB, or TiDB Cloud Starter) and create the first administrator.

Run this once from your PC, with the DB_* values from .env (or the shell):

    python init_cloud_db.py
    python init_cloud_db.py --seed     # also load the sample records

Safe to re-run: tables use IF NOT EXISTS, and the administrator is only
created when no admin account exists yet.
"""

import argparse
import os
import re
import sys

from werkzeug.security import generate_password_hash

import database as db


def load_schema():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "schema_mysql.sql")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def split_statements(script):
    """Split a MySQL script, honouring DELIMITER // blocks (used by triggers)."""
    statements = []
    delimiter = ";"
    buffer = []

    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        if line.upper().startswith("DELIMITER "):
            delimiter = line.split(None, 1)[1].strip()
            continue

        buffer.append(raw_line)
        if line.endswith(delimiter):
            statement = "\n".join(buffer).strip()
            statement = statement[:-len(delimiter)].strip()
            if statement:
                statements.append(statement)
            buffer = []

    leftover = "\n".join(buffer).strip()
    if leftover:
        statements.append(leftover)
    return statements


def main():
    parser = argparse.ArgumentParser(
        description="Create the GIEX Builders schema in a hosted database.")
    parser.add_argument("--seed", action="store_true",
                        help="load the sample workers/projects/DTR afterwards")
    args = parser.parse_args()

    db_name = db.DB_CONFIG.get("database", "giex_builders")
    if not re.fullmatch(r"[A-Za-z0-9_]+", db_name or ""):
        sys.exit(f"Invalid DB_NAME: {db_name!r}")

    print(f"Connecting to {db.DB_HOST}:{db.DB_PORT} as {db.DB_USER} ...")
    try:
        conn = db.get_connection(database=False)
    except db.errors.Error as exc:
        sys.exit(f"Cannot connect: {exc}")

    try:
        cur = conn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.commit()
    finally:
        conn.close()

    flavor = db.server_flavor()
    print(f"Server detected: {flavor}")

    statements = split_statements(load_schema())
    executed = skipped = 0

    try:
        conn = db.get_connection()
        cur = conn.cursor()
        for statement in statements:
            upper = statement.upper()
            if upper.startswith("CREATE DATABASE") or upper.startswith("USE "):
                skipped += 1
                continue
            if flavor == "tidb" and (
                    upper.startswith("CREATE TRIGGER")
                    or upper.startswith("DROP TRIGGER")):
                skipped += 1
                continue
            cur.execute(statement)
            executed += 1
        conn.commit()
    except db.errors.Error as exc:
        sys.exit(f"Schema import failed: {exc}")
    finally:
        conn.close()

    db.ensure_admin_table()
    username = os.environ.get("GIEX_ADMIN_USERNAME", "admin")
    password = os.environ.get("GIEX_ADMIN_PASSWORD", "admin123")
    if db.list_admins():
        print("Administrator account already exists; left unchanged.")
    else:
        db.create_admin(username, generate_password_hash(password),
                        "Administrator")
        print(f"Administrator created: {username}")

    db.ensure_assignment_rules()

    if args.seed:
        import seed_data
        seed_data.seed()
        print("Sample data loaded (existing worker/project data was cleared).")

    print(f"\nDone: {executed} SQL statements executed, {skipped} skipped.")
    print("Next step: deploy to Vercel and add the same DB_* variables there.")


if __name__ == "__main__":
    main()
