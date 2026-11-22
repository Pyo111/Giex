"""
seed_admin.py
Create the default administrator account, or reset its password if it exists.

Run:
    python seed_admin.py                    # admin / admin123
    python seed_admin.py USERNAME PASSWORD  # custom credentials

The username and password default to GIEX_ADMIN_USERNAME and
GIEX_ADMIN_PASSWORD, then to admin / admin123.
"""

import argparse
import os
import sys

from werkzeug.security import generate_password_hash

import database as db


def main():
    parser = argparse.ArgumentParser(
        description="Create or reset a GIEX Builders administrator account.")
    parser.add_argument(
        "username", nargs="?",
        default=os.environ.get("GIEX_ADMIN_USERNAME", "admin"))
    parser.add_argument(
        "password", nargs="?",
        default=os.environ.get("GIEX_ADMIN_PASSWORD", "admin123"))
    parser.add_argument("--full-name", default="Administrator")
    args = parser.parse_args()

    if len(args.password) < 8:
        sys.exit("Password must be at least 8 characters long.")

    try:
        db.ensure_admin_table()
        password_hash = generate_password_hash(args.password)
        existing = db.get_admin_by_username(args.username)
        if existing:
            db.update_admin_password(existing["admin_id"], password_hash)
            print(f"Password reset for administrator '{args.username}'.")
        else:
            db.create_admin(args.username, password_hash, args.full_name)
            print(f"Administrator '{args.username}' created.")
    except db.errors.Error as exc:
        sys.exit(f"Database error: {getattr(exc, 'msg', exc)}")

    print("The account can now sign in to the GIEX Builders web system.")


if __name__ == "__main__":
    main()
