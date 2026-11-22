"""
migrate_to_cloud.py
Copy the existing XAMPP MySQL data into the hosted TiDB / MySQL database
configured by the DB_* values in .env.

Typical use:
    1. python init_cloud_db.py          # create tables/views/admin on TiDB
    2. python migrate_to_cloud.py       # copy the data
       python migrate_to_cloud.py --dry-run   # only show source row counts
       python migrate_to_cloud.py --replace   # clear target tables first
       python migrate_to_cloud.py --with-admins
       python migrate_to_cloud.py --skip-files

Source defaults match a stock XAMPP install:
    SOURCE_DB_HOST=localhost
    SOURCE_DB_PORT=3306
    SOURCE_DB_USER=root
    SOURCE_DB_PASSWORD=
    SOURCE_DB_NAME=giex_builders

The target always uses DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME
from .env (the same values Vercel will use). The source database is only read.
"""

import argparse
import os
import sys

import mysql.connector

import database as db

# Child tables are copied after their parent tables (foreign keys).
TABLES = [
    ("worker", "worker_id"),
    ("project", "project_id"),
    ("assignment", "assignment_id"),
    ("attendance", "attendance_id"),
    ("project_file", "file_id"),
]
ADMIN = ("admin", "admin_id")


def source_config():
    return {
        "host": os.environ.get("SOURCE_DB_HOST", "localhost"),
        "port": int(os.environ.get("SOURCE_DB_PORT", "3306")),
        "user": os.environ.get("SOURCE_DB_USER", "root"),
        "password": os.environ.get("SOURCE_DB_PASSWORD", ""),
        "database": os.environ.get("SOURCE_DB_NAME", "giex_builders"),
        "connection_timeout": 10,
        "charset": "utf8mb4",
        "ssl_disabled": True,
        "time_zone": os.environ.get("SOURCE_DB_TIME_ZONE", "+08:00"),
    }


def target_config():
    """DB_* from .env, with optional TARGET_DB_* overrides."""
    config = dict(db.DB_CONFIG)
    overrides = {
        "host": "TARGET_DB_HOST",
        "port": "TARGET_DB_PORT",
        "user": "TARGET_DB_USER",
        "password": "TARGET_DB_PASSWORD",
        "database": "TARGET_DB_NAME",
    }
    for key, env_name in overrides.items():
        value = os.environ.get(env_name)
        if value:
            config[key] = int(value) if key == "port" else value
    return config


def connect(config, label):
    try:
        conn = mysql.connector.connect(**config)
    except mysql.connector.Error as exc:
        sys.exit(f"Cannot connect to {label} "
                 f"({config.get('host')}:{config.get('port')}): {exc}")
    print(f"Connected to {label}: {config.get('host')}:{config.get('port')} "
          f"/ {config.get('database')}")
    return conn


def count_rows(conn, table):
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COUNT(*) FROM `{table}`")
        return int(cur.fetchone()[0])
    finally:
        cur.close()


def table_columns(conn, table):
    cur = conn.cursor(buffered=True)
    try:
        cur.execute(f"SELECT * FROM `{table}` LIMIT 0")
        return [column[0] for column in cur.description]
    finally:
        cur.close()


def existing_tables(conn):
    cur = conn.cursor()
    try:
        cur.execute("SHOW TABLES")
        return {row[0] for row in cur.fetchall()}
    finally:
        cur.close()


def server_flavor(conn):
    cur = conn.cursor()
    try:
        cur.execute("SELECT VERSION()")
        version = str(cur.fetchone()[0])
    finally:
        cur.close()
    return "tidb" if "tidb" in version.lower() else "mysql"


def validate_target():
    if db.DB_HOST.lower() in ("localhost", "127.0.0.1", "::1"):
        sys.exit("DB_HOST in .env still points to localhost. Put the TiDB host "
                 "in .env before migrating.")
    if db.DB_USER == "your-tidb-user.root" or \
            db.DB_PASSWORD == "your-tidb-password":
        sys.exit("The DB_USER / DB_PASSWORD in .env are still the example "
                 "values. Fill in your TiDB credentials first.")


def clear_target(conn, tables):
    cur = conn.cursor()
    try:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        for table, _ in reversed(tables):
            cur.execute(f"TRUNCATE TABLE `{table}`")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()
        print("Target business tables cleared (--replace).")
    finally:
        cur.close()


def copy_table(src, dst, table, pk, batch_size=500):
    columns = table_columns(src, table)
    column_sql = ", ".join(f"`{name}`" for name in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO `{table}` ({column_sql}) VALUES ({placeholders})"

    read = src.cursor(buffered=True)
    write = dst.cursor()
    try:
        read.execute(f"SELECT {column_sql} FROM `{table}` ORDER BY `{pk}`")
        copied = 0
        # BLOB rows can be large; import project files one at a time.
        effective_batch = 1 if table == "project_file" else batch_size
        while True:
            rows = read.fetchmany(effective_batch)
            if not rows:
                break
            write.executemany(insert_sql, rows)
            dst.commit()
            copied += len(rows)
            print(f"  {table}: {copied} rows...", end="\r")
        print(f"  {table}: {copied} rows copied" + " " * 12)
        return copied
    finally:
        read.close()
        write.close()


def copy_admins(src, dst):
    """Copy old admin accounts without overwriting existing usernames."""
    columns = table_columns(src, ADMIN[0])
    column_sql = ", ".join(f"`{name}`" for name in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = (f"INSERT IGNORE INTO `{ADMIN[0]}` ({column_sql}) "
                  f"VALUES ({placeholders})")

    read = src.cursor(buffered=True)
    write = dst.cursor()
    copied = skipped = 0
    try:
        read.execute(f"SELECT {column_sql} FROM `{ADMIN[0]}` "
                     f"ORDER BY `{ADMIN[1]}`")
        while True:
            rows = read.fetchmany(100)
            if not rows:
                break
            before = write.rowcount
            write.executemany(insert_sql, rows)
            dst.commit()
            accepted = write.rowcount if write.rowcount >= 0 else len(rows)
            # executemany rowcount is a total for the batch.
            if accepted <= 0:
                accepted = 0
            copied += accepted
            skipped += len(rows) - accepted
            del before
        print(f"  admin: {copied} copied, {skipped} skipped (username/ID exists)")
        return copied
    finally:
        read.close()
        write.close()


def reset_auto_increment(conn, table, pk, flavor):
    """Make the next generated ID greater than every imported ID."""
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT COALESCE(MAX(`{pk}`), 0) FROM `{table}`")
        next_id = int(cur.fetchone()[0]) + 1
        if flavor == "tidb":
            cur.execute(f"ALTER TABLE `{table}` FORCE AUTO_INCREMENT = {next_id}")
        else:
            cur.execute(f"ALTER TABLE `{table}` AUTO_INCREMENT = {next_id}")
    except mysql.connector.Error as exc:
        print(f"  warning: could not reset AUTO_INCREMENT on {table}: {exc}")
    finally:
        cur.close()


def print_source_counts(src, tables):
    print("\nSource row counts:")
    for table, _ in tables:
        print(f"  {table:<14} {count_rows(src, table):>8}")


def main():
    parser = argparse.ArgumentParser(
        description="Copy XAMPP MySQL data into the hosted TiDB database.")
    parser.add_argument("--dry-run", action="store_true",
                        help="show source row counts and exit")
    parser.add_argument("--replace", action="store_true",
                        help="clear target business tables before importing")
    parser.add_argument("--with-admins", action="store_true",
                        help="also copy admin accounts (INSERT IGNORE)")
    parser.add_argument("--skip-files", action="store_true",
                        help="do not copy project_file BLOBs")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="rows per insert batch (default 500)")
    args = parser.parse_args()

    tables = list(TABLES)
    if args.skip_files:
        tables = [row for row in tables if row[0] != "project_file"]

    src = connect(source_config(), "source (XAMPP)")
    try:
        print_source_counts(src, tables)
        if args.dry_run:
            print("\nDry run only: no data was written.")
            return

        validate_target()
        dst = connect(target_config(), "target (TiDB/MySQL)")
        try:
            flavor = server_flavor(dst)
            required = {table for table, _ in tables} | {"admin"}
            missing = required - existing_tables(dst)
            if missing:
                sys.exit(
                    "Target tables missing: " + ", ".join(sorted(missing)) +
                    "\nRun `python init_cloud_db.py` first to create the schema.")

            target_counts = {table: count_rows(dst, table)
                             for table, _ in tables}
            busy = {table: count for table, count in target_counts.items()
                    if count}
            if busy and not args.replace:
                sys.exit(
                    "The target already contains data: " +
                    ", ".join(f"{t}={c}" for t, c in busy.items()) +
                    "\nRe-run with --replace to clear those tables and import "
                    "again, or use an empty database.")
            if busy and args.replace:
                clear_target(dst, tables)

            print(f"\nCopying into target ({flavor}) ...")
            for table, pk in tables:
                copy_table(src, dst, table, pk, args.batch_size)

            if args.with_admins:
                print("Copying admin accounts ...")
                copy_admins(src, dst)
                reset_auto_increment(dst, "admin", "admin_id", flavor)

            print("\nResetting AUTO_INCREMENT counters ...")
            for table, pk in tables:
                reset_auto_increment(dst, table, pk, flavor)

            print("\nVerifying row counts:")
            ok = True
            for table, _ in tables:
                source_count = count_rows(src, table)
                target_count = count_rows(dst, table)
                mark = "OK" if source_count == target_count else "MISMATCH"
                if source_count != target_count:
                    ok = False
                print(f"  {table:<14} source={source_count:<8} "
                      f"target={target_count:<8} {mark}")
            if not ok:
                sys.exit("\nCounts do not match. Check the output above.")
        finally:
            dst.close()
    finally:
        src.close()

    print("\nMigration complete.")
    print("The target now has your XAMPP data. Keep Vercel's DB_* environment "
          "variables identical to .env.")


if __name__ == "__main__":
    main()
