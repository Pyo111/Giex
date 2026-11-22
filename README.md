# GIEX Builders Database Management System (Python + MySQL)

Two working interfaces share the same database: a command-line program and a
browser dashboard, both in a black & yellow construction theme. The browser
interface requires an administrator to sign in.

## Files
- schema_mysql.sql - creates the giex_builders database, tables, keys and the DTR view
- database.py      - database settings (reads DB_* environment variables) and all database functions
- main.py          - menu-driven console program (black & yellow theme)
- app.py           - browser version (Flask), admin sign-in, black & yellow web dashboard
- templates/       - HTML pages for the browser version
- public/static/style.css - black & yellow web theme (served by Vercel's CDN)
- seed_data.py     - sample workers, projects and one week of DTR (clears existing data)
- init_cloud_db.py - creates the schema in a hosted MySQL/TiDB database and the first admin
- migrate_to_cloud.py - copies existing XAMPP workers/projects/DTR into the hosted database
- requirements.txt - Python packages (used by pip and Vercel)
- vercel.json      - Vercel project configuration
- DEPLOYMENT.md    - step-by-step live deployment guide (Vercel + TiDB Cloud)

## Setup
1. Install MySQL 8.0.16 or newer (MySQL Server + MySQL Workbench).
2. Install the Python packages:

       pip install mysql-connector-python flask

3. Create the database: in MySQL Workbench, File -> Open SQL Script -> schema_mysql.sql -> run (lightning icon).
   Or from a terminal:

       mysql -u root -p < schema_mysql.sql

4. Copy `.env.example` to `.env` and set your MySQL values. For the default
   XAMPP installation:

       DB_HOST=localhost
       DB_PORT=3306
       DB_USER=root
       DB_PASSWORD=
       DB_NAME=giex_builders
       DB_SSL_MODE=DISABLED

   `database.py` loads `.env` automatically. (You can also set real environment
   variables; they take precedence.)
5. (Optional) Load sample data:

       python seed_data.py

## Run the console version
    python main.py

## Run the browser version
    python app.py

Then open http://127.0.0.1:5000 in a browser. Keep the terminal running while
using the web system; press Ctrl+C in the terminal to stop the server.

## Admin sign-in
Every web page except the sign-in screen requires an administrator account.
On first run the app creates the `admin` table and a default account (there is
no need to re-import the schema for this):

    username: admin
    password: admin123

Sign in, then open **Settings** in the sidebar to set your own password and
create additional administrator accounts; the new admin can sign in immediately.

Optional environment variables:

    GIEX_SECRET_KEY       - Flask session secret (set your own for shared machines)
    GIEX_ADMIN_USERNAME   - default admin username (initial setup only)
    GIEX_ADMIN_PASSWORD   - default admin password (initial setup only)

Sessions last 8 hours, and signing out clears the session immediately.

## Menus / Pages
0. Sign in (web) - administrator must sign in before any page opens
1. Worker Management - add, view, search, update, delete (role chosen from a fixed list)
2. Project Management - add, view, update, delete, upload/view/download/delete project files
3. Assignments - assign workers to projects, view workers per project, remove
4. DTR Attendance - time-in, time-out, mark Absent/On Leave/Half-day, view DTR, payroll summary
5. Payroll Report (web) - gross pay per worker for a selected period and project
6. Settings (web) - add administrator accounts and change your password

## Rules built into the system
- Worker rate is a daily rate for 8 hours. Gross pay = paid hours / 8 x daily rate.
- A time-in after 08:00 is marked "Late" automatically.
- 1 hour of lunch is deducted when a shift covers 12:00-13:00.
- Paid hours are capped at 8 per day (no overtime pay).
- A worker can hold only ONE ongoing project assignment. When the project's end
  date has passed, the worker can be assigned to a new project. Site engineers
  are the exception and may hold several ongoing projects (enforced by app
  checks and MySQL triggers).
- A worker is assigned at most once to the same project, and has one DTR entry per
  day per assignment.

## Deploy online (Vercel + TiDB Cloud)

The Flask app can run on Vercel, but the database must be hosted because Vercel
cannot reach MySQL on `localhost` (XAMPP). See **[DEPLOYMENT.md](DEPLOYMENT.md)**
for the complete walkthrough using TiDB Cloud Starter (free MySQL-compatible
tier).

Quick version:

1. Create a TiDB Cloud Starter instance and copy its host, port, user, password.
2. Copy `.env.example` to `.env` and fill in the `DB_*` values.
3. `pip install -r requirements.txt`
4. `python init_cloud_db.py` (creates the schema and admin)
5. `python migrate_to_cloud.py` to copy your existing XAMPP data (use
   `--dry-run` first; add `--seed` to `init_cloud_db.py` instead if you want
   sample data)
6. Run `vercel` / `vercel --prod` and add the same environment variables in the
   Vercel dashboard.

Notes:

- TiDB does not support triggers. The app detects TiDB and skips them; the
  assignment rule is still enforced by the Python code.
- Vercel limits request/response bodies to 4.5 MB, so keep project file uploads
  below that size.
- Set `GIEX_SECRET_KEY`, `GIEX_ADMIN_USERNAME`, and `GIEX_ADMIN_PASSWORD` in
  Vercel before going live.

