# Deploy GIEX Builders DBMS to Vercel

Vercel can host the Flask web app, but it **cannot reach MySQL on your XAMPP
`localhost`**. The database must be hosted on the internet. This guide uses
**TiDB Cloud Starter** (formerly TiDB Cloud Serverless) because it has a free
MySQL-compatible tier. Any hosted MySQL 8 database also works.

> **TiDB caveat:** TiDB does not support triggers. The app detects TiDB and
> skips the two assignment triggers. The same rule is still enforced in Python
> by `assign_worker()` / `update_worker()`, so the web app behaves the same.
> Only direct SQL edits made outside the app bypass the rule.

---

## Part 1 — Create the TiDB Cloud database

1. Go to <https://tidbcloud.com/> and sign up (no credit card for Starter).
2. On **My TiDB**, click **Create Resource**.
3. Choose **Starter** (MySQL-compatible), a name such as `giex-builders`, and the
   **AWS / Singapore (ap-southeast-1)** region (closest to the Philippines).
4. Wait about 30 seconds for the instance to be created.
5. Click the instance name, then **Connect** in the upper-right corner.
6. Keep **Public** as the connection type, choose **MySQL CLI** (or
   **General**), and note these values:

   | Setting | Example |
   | --- | --- |
   | Host | `gateway01.ap-southeast-1.prod.aws.tidbcloud.com` |
   | Port | `4000` |
   | User | `3pTAoNNegb47Uc8.root` |
   | Password | click **Generate Password** and save it |

   The user name must include the account prefix (the part before `.root`).

7. **Networking / firewall:** new Starter instances allow all public
   connections by default. If you later restrict it, add a rule that allows
   Vercel's dynamic IPs (for example `0.0.0.0` to `255.255.255.255`) under
   **Settings → Networking → Authorized Networks**. Vercel Functions do not have
   fixed outbound IPs.

TLS is required by TiDB Cloud. The app supports it through `DB_SSL_MODE`.

---

## Part 2 — Initialize the database from your PC

Open **PowerShell** in `C:\xampp\htdocs\GIEX_Builders_DBMS`.

### 2.1 Install the Python packages

```powershell
pip install -r requirements.txt
```

### 2.2 Create your local `.env`

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in the values from the TiDB **Connect** dialog:

```ini
DB_HOST=gateway01.ap-southeast-1.prod.aws.tidbcloud.com
DB_PORT=4000
DB_USER=3pTAoNNegb47Uc8.root
DB_PASSWORD=the-password-you-saved
DB_NAME=giex_builders
DB_SSL_MODE=VERIFY_IDENTITY
DB_TIME_ZONE=+08:00

GIEX_SECRET_KEY=replace-with-a-long-random-value
GIEX_ADMIN_USERNAME=admin
GIEX_ADMIN_PASSWORD=choose-a-strong-password
```

Generate a strong Flask secret:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`database.py` loads `.env` automatically. The file is ignored by Git/Vercel and
must never be committed.

### 2.3 Create the tables, view, and administrator

```powershell
python init_cloud_db.py
```

This creates the `giex_builders` database, all tables, `v_dtr`, the admin
account, and (on TiDB) skips the unsupported triggers automatically.

Optional: load the sample workers/projects/DTR:

```powershell
python init_cloud_db.py --seed
```

> `--seed` clears existing worker/project/attendance data. Do not use it on a
> database that already has real records.

### 2.4 Confirm the connection

```powershell
python -c "import database as db; print(db.server_flavor()); print(len(db.list_workers()), 'workers')"
```

Expected output starts with `tidb`.

---

## Part 3 — Deploy to Vercel

You can deploy from the CLI (fastest, no Git required) or through GitHub.

### Option A — Vercel CLI

1. Install Node.js if needed, then install the CLI:

   ```powershell
   npm install -g vercel
   ```

2. Sign in and create the project:

   ```powershell
   vercel login
   vercel
   ```

   Accept the defaults. Vercel detects Flask from `app.py` and
   `requirements.txt`. The first deployment may show database errors until the
   environment variables are added — that is expected.

3. Add the environment variables. The easiest way is the dashboard:
   **Project → Settings → Environment Variables**, add each variable for
   **Production** (and Preview if you want):

   | Name | Value |
   | --- | --- |
   | `DB_HOST` | `gateway01...tidbcloud.com` |
   | `DB_PORT` | `4000` |
   | `DB_USER` | `xxxxxxxx.root` |
   | `DB_PASSWORD` | your TiDB password |
   | `DB_NAME` | `giex_builders` |
   | `DB_SSL_MODE` | `VERIFY_IDENTITY` (fallback: `REQUIRED`) |
   | `DB_TIME_ZONE` | `+08:00` |
   | `GIEX_SECRET_KEY` | the long random value |
   | `GIEX_ADMIN_USERNAME` | `admin` |
   | `GIEX_ADMIN_PASSWORD` | same password used by the init script |
   | `TZ` | `Asia/Manila` (optional, affects function logs/time) |

   Or add them from the CLI (repeat for each variable):

   ```powershell
   vercel env add DB_HOST production
   ```

4. Deploy to production:

   ```powershell
   vercel --prod
   ```

5. Open the URL Vercel prints. Test:

   - `https://your-project.vercel.app/healthz` → `{"status":"ok","database":"tidb"}`
   - `https://your-project.vercel.app/login` → sign in
   - Change the admin password under **Settings → Password**

### Option B — GitHub

1. Create a repository and push the project:

   ```powershell
   git init
   git add .
   git commit -m "Deploy GIEX Builders DBMS"
   git branch -M main
   git remote add origin https://github.com/YOUR-USER/giex-builders-dbms.git
   git push -u origin main
   ```

2. Go to <https://vercel.com/new>, import the repository, and click **Deploy**.
   Vercel auto-detects Flask; do not set a build command or output directory.

3. Add the environment variables from the table above, then redeploy
   (**Deployments → ... → Redeploy**).

---

## Part 4 — Test the live system

1. Sign in with the `GIEX_ADMIN_USERNAME` / `GIEX_ADMIN_PASSWORD` you created.
2. Add a worker, a project, and an assignment.
3. Record a time-in/time-out and check **DTR Attendance** and **Payroll Report**.
4. Upload a small project file (under 4 MB).
5. Change the admin password in **Settings**.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Can't connect to MySQL server` | Check `DB_HOST`, `DB_PORT=4000`, and that the TiDB instance is running. |
| `SSL is required` / TLS error | Set `DB_SSL_MODE=REQUIRED` (or `VERIFY_IDENTITY`). |
| `Unknown database 'giex_builders'` | Run `python init_cloud_db.py` again. |
| `Trigger ... not supported` | The database is TiDB; this should be skipped automatically. Set `GIEX_DB_FLAVOR=tidb` if detection failed. |
| Login page says "Cannot reach the database" | Environment variables are missing or wrong in Vercel; check Runtime Logs. |
| Redirected to login repeatedly | Set `GIEX_SECRET_KEY` in Vercel and redeploy. |
| `413` when uploading a file | Vercel Functions limit request/response bodies to **4.5 MB**. Store larger files elsewhere (e.g. Vercel Blob/S3). |
| First request is slow | Normal cold start; Vercel Fluid compute keeps the instance warm under traffic. |
| `ModuleNotFoundError` | Make sure `requirements.txt` is committed and lists the package. |
| Free quota errors | TiDB Starter gives 5 GiB storage + 50M RUs/month; check usage in the TiDB console. |

---

## Production notes

- **Plan limits:** Vercel Hobby is intended for personal, non-commercial
  projects. A school/demo project is fine; a commercial deployment needs a paid
  plan.
- **Sessions:** Flask uses signed cookies, so no server-side session store is
  needed. Set a strong `GIEX_SECRET_KEY`.
- **Database connections:** the app opens short-lived connections per query.
  That matches TiDB Starter's 30-minute connection limit and requires no pool.
- **File size:** project files are stored in the `project_file` table. With
  Vercel's 4.5 MB body limit, uploads are effectively capped at ~4.5 MB.
- **Triggers:** on TiDB the two triggers are skipped; the rules are enforced by
  the Flask app. On real MySQL, they are installed automatically.
- **Backups:** TiDB Cloud Starter includes backups; review the retention for
  your plan before relying on it.
- **Don't commit** `.env`, passwords, or the TiDB CA private material.

Local development still works exactly as before:

```powershell
python app.py
```

(with `.env` pointing to TiDB, or with local XAMPP MySQL if you set
`DB_HOST=localhost`, `DB_USER=root`, `DB_PASSWORD=`, `DB_SSL_MODE=DISABLED`).
