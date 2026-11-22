"""
main.py
GIEX Builders Database Management System - command-line interface (MySQL).
Theme: black & yellow.
Run:  python main.py
"""

import os
import re
import sys
from decimal import Decimal

import database as db

# ---------------------------------------------------------------------
# Console theme - black background with GIEX yellow (#FFD400) accents
# ---------------------------------------------------------------------
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def _enable_ansi():
    """Turn on ANSI escape processing in classic Windows consoles."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


USE_COLOR = sys.stdout.isatty() and _enable_ansi()


class C:
    """ANSI truecolor codes for the black & yellow theme."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    BG_BLACK = "\033[48;2;0;0;0m"
    BG_YELLOW = "\033[48;2;255;212;0m"       # #FFD400
    YELLOW = "\033[38;2;255;212;0m"          # brand yellow
    YELLOW_BRIGHT = "\033[38;2;255;225;77m"  # interactive yellow
    YELLOW_PALE = "\033[38;2;255;233;138m"
    DARK = "\033[38;2;23;19;0m"              # text on yellow
    WHITE = "\033[38;2;255;255;255m"
    GREY = "\033[38;2;163;160;143m"


STATUS_COLORS = {
    "Present": C.WHITE,
    "Late": C.YELLOW_PALE,
    "Absent": C.BOLD + C.YELLOW_BRIGHT,
    "Half-day": C.GREY,
    "On Leave": C.GREY,
}

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

RULE_WIDTH = 62


def paint(text, *styles):
    text = str(text)
    if not USE_COLOR or not styles:
        return text
    return "".join(styles) + text + C.RESET + C.BG_BLACK


def visible_len(text):
    return len(_ANSI_RE.sub("", text))


def pad(text, width, right=False):
    gap = " " * max(0, width - visible_len(text))
    return gap + text if right else text + gap


def start_screen():
    """Fill the screen with the black canvas of the theme."""
    if USE_COLOR:
        sys.stdout.write(C.BG_BLACK + C.WHITE + "\033[2J\033[H")
        sys.stdout.flush()


def end_screen():
    """Restore the terminal's normal colors on exit."""
    if USE_COLOR:
        sys.stdout.write(C.RESET + "\n")
        sys.stdout.flush()


def ok(message):
    print("  " + paint("✓", C.YELLOW_BRIGHT) + " " + paint(message, C.WHITE))


def err(message):
    print("  " + paint("✗", C.BOLD, C.YELLOW_BRIGHT) + " "
          + paint(message, C.YELLOW_BRIGHT))


def note(message):
    print("  " + paint("•", C.YELLOW) + " " + paint(message, C.GREY))


def banner():
    print()
    print("  " + paint("██", C.YELLOW) + "  "
          + paint("GIEX BUILDERS", C.BOLD, C.WHITE))
    print("      " + paint("DATABASE MANAGEMENT SYSTEM", C.WHITE))
    print("      " + paint("Workers  •  Projects  •  Attendance  •  Payroll", C.GREY))
    print()
    print("  " + paint("─" * RULE_WIDTH, C.YELLOW))


def opt(key, label):
    return paint(f"[{key}]", C.BOLD, C.YELLOW_BRIGHT) + "  " + paint(label, C.WHITE)


def section(title, options):
    print()
    print("  " + paint("▌", C.YELLOW) + " " + paint(title, C.BOLD, C.WHITE))
    print("  " + paint("─" * RULE_WIDTH, C.YELLOW))
    for option in options:
        print("   " + option)


# ---------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------
def ask(prompt, required=True):
    label = paint(prompt, C.YELLOW_PALE)
    while True:
        value = input(label).strip()
        if value or not required:
            return value
        err("This field is required.")


def ask_int(prompt):
    while True:
        try:
            return int(ask(prompt))
        except ValueError:
            err("Please enter a whole number.")


def ask_float(prompt):
    while True:
        try:
            value = float(ask(prompt))
            if value >= 0:
                return value
        except ValueError:
            pass
        err("Please enter a valid non-negative number.")


def ask_date(prompt, required=True):
    while True:
        value = ask(prompt + " (YYYY-MM-DD): ", required)
        if not value and not required:
            return None
        if db.valid_date(value):
            return value
        err("Invalid date format.")


def ask_time(prompt):
    while True:
        value = ask(prompt + " (HH:MM, 24-hr): ")
        if db.valid_time(value):
            return value
        err("Invalid time format.")


def ask_role(current=None):
    """Let the user pick a role from the same list used by the web interface."""
    print("  " + paint("Roles:", C.YELLOW_PALE))
    for index, role in enumerate(db.WORKER_ROLES, 1):
        suffix = " (current)" if role == current else ""
        print("   " + opt(index, role + suffix))
    prompt = "Select role number"
    if current:
        prompt += " (0 to keep current)"
    while True:
        value = ask(prompt + ": ")
        if current and value == "0":
            return current
        try:
            index = int(value)
        except ValueError:
            index = 0
        if 1 <= index <= len(db.WORKER_ROLES):
            return db.WORKER_ROLES[index - 1]
        err("Please choose a role from the list.")


def pause():
    input(paint("\nPress Enter to continue...", C.GREY))


# ---------------------------------------------------------------------
# Table renderer
# ---------------------------------------------------------------------
def print_table(rows, columns, headers=None, status_column=None):
    headers = headers or columns
    if not rows:
        print("  " + paint("(no records found)", C.GREY))
        return

    numeric = []
    for column in columns:
        values = [r[column] for r in rows if r[column] is not None]
        numeric.append(bool(values) and all(
            isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
            for v in values))

    body = [[("" if r[c] is None else str(r[c])) for c in columns] for r in rows]
    widths = [max(visible_len(str(h)), *(visible_len(row[i]) for row in body))
              for i, h in enumerate(headers)]

    def rule(left, mid, right, style):
        parts = (paint("─" * (w + 2), style) for w in widths)
        return ("  " + paint(left, style) + paint(mid, style).join(parts)
                + paint(right, style))

    print(rule("┌", "┬", "┐", C.YELLOW))

    header_cells = []
    for i, (header, width) in enumerate(zip(headers, widths)):
        header_cells.append(paint(
            " " + pad(str(header), width, numeric[i]) + " ",
            C.BG_YELLOW, C.BOLD, C.DARK))
    head_sep = paint("│", C.BG_YELLOW, C.DARK)
    print("  " + head_sep + head_sep.join(header_cells) + head_sep)

    print(rule("├", "┼", "┤", C.YELLOW))

    for row in body:
        cells = []
        for i, value in enumerate(row):
            text = value
            if status_column and columns[i] == status_column \
                    and text in STATUS_COLORS:
                text = paint(text, STATUS_COLORS[text])
            else:
                text = paint(text, C.WHITE)
            cells.append(" " + pad(text, widths[i], numeric[i]) + " ")
        sep = paint("│", C.GREY)
        print("  " + sep + sep.join(cells) + sep)

    print(rule("└", "┴", "┘", C.YELLOW))


# ---------------------------------------------------------------------
# Worker management
# ---------------------------------------------------------------------
def worker_menu():
    while True:
        section("WORKER MANAGEMENT", [
            opt(1, "Add worker"),
            opt(2, "View all workers"),
            opt(3, "Search worker"),
            opt(4, "Update worker"),
            opt(5, "Delete worker"),
            opt(0, "Back"),
        ])
        choice = ask("Select: ")
        if choice == "1":
            wid = db.add_worker(ask("First name: "), ask("Last name: "),
                                ask_role(), ask_float("Daily rate (PHP): "))
            ok(f"Worker added with ID {wid}.")
        elif choice == "2":
            print_table(db.list_workers(),
                        ["worker_id", "first_name", "last_name", "role", "worker_rate"],
                        ["ID", "First Name", "Last Name", "Role", "Daily Rate"])
        elif choice == "3":
            print_table(db.search_workers(ask("Keyword (name or role): ")),
                        ["worker_id", "first_name", "last_name", "role", "worker_rate"],
                        ["ID", "First Name", "Last Name", "Role", "Daily Rate"])
        elif choice == "4":
            w = db.get_worker(ask_int("Worker ID: "))
            if not w:
                err("Worker not found.")
                continue
            note("Leave blank to keep the current value.")
            first = ask(f"First name [{w['first_name']}]: ", False) or w["first_name"]
            last = ask(f"Last name [{w['last_name']}]: ", False) or w["last_name"]
            role = ask_role(w["role"])
            rate = ask(f"Daily rate [{w['worker_rate']}]: ", False)
            if rate:
                try:
                    rate = float(rate)
                except ValueError:
                    err("Invalid rate; keeping the current value.")
                    rate = w["worker_rate"]
            else:
                rate = w["worker_rate"]
            try:
                db.update_worker(w["worker_id"], first, last, role, rate)
                ok("Worker updated.")
            except ValueError as e:
                err(str(e))
            except db.errors.Error as e:
                err(f"Database error: {getattr(e, 'msg', str(e))}")
        elif choice == "5":
            wid = ask_int("Worker ID: ")
            if ask("This also deletes the worker's assignments and DTR. "
                   "Type YES to confirm: ") == "YES":
                if db.delete_worker(wid):
                    ok("Worker deleted.")
                else:
                    err("Worker not found.")
        elif choice == "0":
            return
        pause()


# ---------------------------------------------------------------------
# Project management
# ---------------------------------------------------------------------
def project_menu():
    while True:
        section("PROJECT MANAGEMENT", [
            opt(1, "Add project"),
            opt(2, "View all projects"),
            opt(3, "Update project"),
            opt(4, "Delete project"),
            opt(5, "Upload project file"),
            opt(6, "View project files"),
            opt(7, "Download project file"),
            opt(8, "Delete project file"),
            opt(0, "Back"),
        ])
        choice = ask("Select: ")
        if choice == "1":
            name, loc = ask("Project name: "), ask("Location: ")
            start = ask_date("Start date")
            end = ask_date("End date (blank if ongoing)", required=False)
            pid = db.add_project(name, loc, start, end)
            ok(f"Project added with ID {pid}.")
        elif choice == "2":
            print_table(db.list_projects(),
                        ["project_id", "project_name", "location", "start_date", "end_date"],
                        ["ID", "Project Name", "Location", "Start", "End"])
        elif choice == "3":
            p = db.get_project(ask_int("Project ID: "))
            if not p:
                err("Project not found.")
                continue
            note("Leave blank to keep the current value.")
            name = ask(f"Project name [{p['project_name']}]: ", False) or p["project_name"]
            loc = ask(f"Location [{p['location']}]: ", False) or p["location"]
            start = ask_date(f"Start date [{p['start_date']}]", False) or p["start_date"]
            end = ask_date(f"End date [{p['end_date']}]", False) or p["end_date"]
            db.update_project(p["project_id"], name, loc, start, end)
            ok("Project updated.")
        elif choice == "4":
            pid = ask_int("Project ID: ")
            if ask("This also deletes its assignments, DTR and files. "
                   "Type YES to confirm: ") == "YES":
                if db.delete_project(pid):
                    ok("Project deleted.")
                else:
                    err("Project not found.")
        elif choice == "5":
            pid = ask_int("Project ID: ")
            path = ask("Path of file to upload: ")
            try:
                fid = db.upload_project_file(pid, path, ask("Description: ", False))
                ok(f"File stored with ID {fid}.")
            except FileNotFoundError:
                err("File not found on disk.")
        elif choice == "6":
            print_table(db.list_project_files(ask_int("Project ID: ")),
                        ["file_id", "file_name", "file_type", "description",
                         "uploaded_on", "size_bytes"],
                        ["ID", "File Name", "Type", "Description", "Uploaded", "Bytes"])
        elif choice == "7":
            try:
                out = db.download_project_file(ask_int("File ID: "),
                                               ask("Save to folder: "))
                ok(f"Saved to {out}")
            except ValueError as e:
                err(str(e))
        elif choice == "8":
            if db.delete_project_file(ask_int("File ID: ")):
                ok("File deleted.")
            else:
                err("File not found.")
        elif choice == "0":
            return
        pause()


# ---------------------------------------------------------------------
# Assignment management
# ---------------------------------------------------------------------
ASSIGN_COLS = ["assignment_id", "worker_id", "worker_name", "role",
               "project_id", "project_name", "assignment_date"]
ASSIGN_HDRS = ["Assign ID", "Worker ID", "Worker", "Role",
               "Proj ID", "Project", "Date Assigned"]


def assignment_menu():
    while True:
        section("ASSIGNMENTS", [
            opt(1, "Assign worker to project"),
            opt(2, "View all assignments"),
            opt(3, "View workers in a project"),
            opt(4, "Remove assignment"),
            opt(0, "Back"),
        ])
        choice = ask("Select: ")
        if choice == "1":
            wid, pid = ask_int("Worker ID: "), ask_int("Project ID: ")
            if not db.get_worker(wid) or not db.get_project(pid):
                err("Worker or project not found.")
            else:
                try:
                    aid = db.assign_worker(wid, pid, ask_date("Assignment date"))
                    ok(f"Assignment created with ID {aid}.")
                except ValueError as e:
                    err(str(e))
                except db.errors.Error as e:
                    err(f"Database error: {getattr(e, 'msg', str(e))}")
        elif choice == "2":
            print_table(db.list_assignments(), ASSIGN_COLS, ASSIGN_HDRS)
        elif choice == "3":
            print_table(db.list_assignments(ask_int("Project ID: ")
                                            ), ASSIGN_COLS, ASSIGN_HDRS)
        elif choice == "4":
            if db.delete_assignment(ask_int("Assignment ID: ")):
                ok("Assignment removed.")
            else:
                err("Assignment not found.")
        elif choice == "0":
            return
        pause()


# ---------------------------------------------------------------------
# DTR attendance
# ---------------------------------------------------------------------
DTR_COLS = ["attendance_date", "worker_id", "worker_name", "project_name",
            "time_in", "time_out", "attendance_status", "total_hours"]
DTR_HDRS = ["Date", "Worker ID", "Worker", "Project",
            "Time-in", "Time-out", "Status", "Total Hrs"]


def attendance_menu():
    while True:
        section("DTR ATTENDANCE", [
            opt(1, "Time-in"),
            opt(2, "Time-out"),
            opt(3, "Mark Absent / On Leave / Half-day"),
            opt(4, "View DTR by worker"),
            opt(5, "View DTR by project"),
            opt(6, "Payroll report"),
            opt(0, "Back"),
        ])
        choice = ask("Select: ")
        if choice == "1":
            aid = ask_int("Assignment ID: ")
            if not db.get_assignment(aid):
                err("Assignment not found.")
            else:
                _, status = db.time_in(aid, ask_date("Date"), ask_time("Time-in"))
                ok(f"Time-in recorded. Status: {status}")
        elif choice == "2":
            try:
                db.time_out(ask_int("Assignment ID: "), ask_date("Date"),
                            ask_time("Time-out"))
                ok("Time-out recorded.")
            except ValueError as e:
                err(str(e))
        elif choice == "3":
            aid, date = ask_int("Assignment ID: "), ask_date("Date")
            status = {"1": "Absent", "2": "On Leave", "3": "Half-day"}.get(
                ask("[1] Absent  [2] On Leave  [3] Half-day: "))
            if status:
                db.mark_status(aid, date, status)
                ok(f"Marked as {status}.")
        elif choice == "4":
            wid = ask_int("Worker ID: ")
            print_table(db.get_dtr(worker_id=wid,
                                   date_from=ask_date("From", False),
                                   date_to=ask_date("To", False)),
                        DTR_COLS, DTR_HDRS, status_column="attendance_status")
        elif choice == "5":
            pid = ask_int("Project ID: ")
            print_table(db.get_dtr(project_id=pid,
                                   date_from=ask_date("From", False),
                                   date_to=ask_date("To", False)),
                        DTR_COLS, DTR_HDRS, status_column="attendance_status")
        elif choice == "6":
            start, end = ask_date("Period from"), ask_date("Period to")
            pid = ask("Project ID (blank for all): ", False)
            rows = db.payroll_summary(start, end, int(pid) if pid else None)
            print_table(rows,
                        ["worker_id", "worker_name", "role", "worker_rate",
                         "days_worked", "days_absent", "total_hours",
                         "paid_hours", "gross_pay"],
                        ["ID", "Worker", "Role", "Daily Rate", "Days", "Absent",
                         "Actual Hrs", "Paid Hrs", "Gross Pay"])
        elif choice == "0":
            return
        pause()


# ---------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------
def main():
    try:
        db.test_connection()
    except db.errors.Error as e:
        print()
        err("Cannot connect to the MySQL database.")
        note("Check DB_CONFIG in database.py and make sure schema_mysql.sql was executed.")
        note(f"Details: {e}")
        return

    start_screen()
    banner()

    try:
        while True:
            section("MAIN MENU", [
                opt(1, "Worker Management"),
                opt(2, "Project Management"),
                opt(3, "Assignments"),
                opt(4, "DTR Attendance"),
                opt(0, "Exit"),
            ])
            choice = ask("Select: ")
            try:
                if choice == "1":
                    worker_menu()
                elif choice == "2":
                    project_menu()
                elif choice == "3":
                    assignment_menu()
                elif choice == "4":
                    attendance_menu()
                elif choice == "0":
                    print()
                    ok("Goodbye!")
                    break
            except db.errors.IntegrityError as e:
                err(f"Database rule violated: {e.msg}")
                pause()
            except db.errors.Error as e:
                err(f"Database error: {e.msg}")
                pause()
    except KeyboardInterrupt:
        print()
        ok("Session cancelled. Goodbye!")
    finally:
        end_screen()


if __name__ == "__main__":
    main()
