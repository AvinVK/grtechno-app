# Lead desk

Lead management for a fire protection installation business. Track enquiries from first call to
won or lost, see who to call today, and keep notes on every lead. Flask + SQLite, no build step.

- **Sign-in with your own userid.** The admin adds people; each person sets their own 6-digit PIN.
  Everyone sees only their own leads; the admin sees all of them and manages users.
- **Roles.** Each person has a role (Admin, Sales (field), Sales (office), Project manager, Site supervisor,
  Accounts). The role decides which services they can open and whether they see every client and project.
- **Lead desk extras.** A Site category list, the updated work categories, and a checklist on every lead. A won lead
  gets a **Create project** button.
- **Clients and Projects.** Won leads become a client and a project. The project holds the work order number and
  date, start date, completion period, estimated amount, discount, payment terms, special terms and a payment schedule.
  Work that is already running is added with **Add project** on the Projects screen (pick a client or type a new one).
- **Left menu.** The three-dash button at the top left opens a panel with the services you can use, who is
  signed in, and Sign out. Lead desk is the first service; more (attendance, manpower, material allotment, ...) plug in
  the same way. The admin also sees **Users & roles** there under **Manage**, which is its own app-wide page at `/users` (not part of Lead desk).
- **Bottom tabs** (phone-first, inside Lead desk): **Active leads**, **Add lead**, **Won / Lost** and **Your status**
  (open pipeline value, follow-ups due, won this month).
- **Active leads**: every lead still in progress (New enquiry, Site survey, Quote sent, Negotiation),
  earliest follow-up first, with search and stage filter chips. Tap a lead to update its stage,
  follow-up, notes and activity log. No drag and drop.
- **Add lead** is a full screen and always starts a lead at New enquiry.
  Typing the site pincode fills in state, district and city.
- **Won / Lost** are outcomes, set by the user with the Mark won / Mark lost buttons inside a lead.
  Those leads move to the Won / Lost tab; set a lead's Status back to an active stage to reopen it.
- **Each lead**: contact, company, phone, email, site address, service, estimated value, source,
  follow-up date, notes, one-tap Call / WhatsApp / Email, and an activity log (notes plus automatic
  stage and follow-up changes).
- **Export CSV** from the top bar (or the bottom of the Won / Lost tab on a phone).

The database is a single SQLite file at `instance/leads.db`. There is no Excel link; the CSV export
is a one-way copy for reporting.

## Run it locally

You need Python 3.10 or newer.

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
flask --app wsgi db upgrade
flask --app wsgi create-admin
flask --app wsgi run --debug
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app wsgi db upgrade
flask --app wsgi create-admin
flask --app wsgi run --debug
```

Open http://127.0.0.1:5000. `create-admin` prints the admin's userid and a one-time setup code; open
`/set-pin`, enter both, choose a 6-digit PIN, then sign in.

`flask db upgrade` creates `instance/leads.db`. Want sample data to click around in?

```bash
flask --app wsgi seed-demo            # adds 12 fictional leads
flask --app wsgi seed-demo --force    # wipes ALL leads first, then adds them
```


### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs the login session. Optional: if unset the app creates a random key once in `instance/secret_key`. |
| `TIMEZONE` | Decides what "today" means for follow-ups. Default `Asia/Kolkata`. |
| `SESSION_COOKIE_SECURE` | Set to `1` once the site is on HTTPS. |
| `DATABASE_URL` | Optional. Overrides the SQLite file location. |

Generate a secret key with: `python -c "import secrets; print(secrets.token_hex(32))"`

## Deploy to PythonAnywhere

This follows the same procedure as Clockit. `main` is production. After every push to `main`, a GitHub Action calls a
secret-protected `/deploy` route inside the running app (`app/deploy.py`, `scripts/deploy.py`). The route does:

1. `git pull` on the server,
2. a backup of the database to `instance/backups/` (the newest 10 are kept),
3. the database migrations (`flask db upgrade`), and
4. a reload of the site (it touches the WSGI file).

If the pull or the migration fails, the site is not reloaded and keeps running the old code; the Action turns red and
shows the reason. If `requirements.txt` changed, the Action prints a warning: run `pip install -r requirements.txt`
in a Bash console on PythonAnywhere and press Reload.

### One-time setup

**Before you start.** A free PythonAnywhere account runs **one** web app, and `avin0406` already runs Clockit. Use a
second account (for example `grtechno`, giving `https://grtechno.pythonanywhere.com`) or a paid plan that allows two
web apps. Below, `YOURNAME` is the PythonAnywhere username the app will live under. Merge `dev` into `main` first so
the code you clone already contains the `/deploy` route.

**1. Clone the code (Bash console on PythonAnywhere).**

```bash
cd ~
git clone https://github.com/AvinVK/grtechno-app.git
```

If the repository is private, clone with a read-only token instead (GitHub > Settings > Developer settings >
Fine-grained tokens, repository `grtechno-app`, permission *Contents: Read-only*):
`git clone https://AvinVK:TOKEN@github.com/AvinVK/grtechno-app.git`. The token is kept in `.git/config` on the
server, which is what lets the webhook run `git pull` later.

**2. Virtualenv and packages.**

```bash
cd ~/grtechno-app
mkvirtualenv grtechno --python=python3.12      # any Python version PythonAnywhere offers (3.10 or newer)
pip install -r requirements.txt
```

**3. The `.env` file** (`cp .env.example .env`, then `nano .env`). It is git-ignored, so it stays on the server.

```
SESSION_COOKIE_SECURE=1
TIMEZONE=Asia/Kolkata
DEPLOY_SECRET=<a long random value, see below>
WSGI_RELOAD_FILE=/var/www/YOURNAME_pythonanywhere_com_wsgi.py
```

Make the secret with `python -c "import secrets; print(secrets.token_urlsafe(32))"`. `SECRET_KEY` is optional: if you
leave it out, the app creates a strong key once in `instance/secret_key`.

**4. Create the database and the admin** (still in the Bash console, virtualenv active).

```bash
cd ~/grtechno-app
flask --app wsgi db upgrade                    # creates instance/leads.db with all tables and the starting lists
flask --app wsgi create-admin --code 3766      # prints the admin userid (grtechno-3766) and a one-time setup code
```

The database is one SQLite file, `instance/leads.db`. It is not in git, so a fresh server starts empty (no test
users or leads).

**5. The web app (Web tab).** *Add a new web app*, *Manual configuration*, the same Python version, then set:

- Source code and Working directory: `/home/YOURNAME/grtechno-app`
- Virtualenv: `/home/YOURNAME/.virtualenvs/grtechno`
- Static files: URL `/static/` to directory `/home/YOURNAME/grtechno-app/app/static`
- WSGI configuration file (open it and replace everything with):

```python
import sys
path = "/home/YOURNAME/grtechno-app"
if path not in sys.path:
    sys.path.insert(0, path)

from wsgi import application
```

Press **Reload**, then open `https://YOURNAME.pythonanywhere.com/set-pin`, enter the admin userid and setup code, and
choose your PIN. Sign in and add users from **Users** in the left menu.

**6. Connect GitHub.** In the repository, Settings > Secrets and variables > Actions > *New repository secret*:

| Secret | Value |
|---|---|
| `DEPLOY_URL` | `https://YOURNAME.pythonanywhere.com/deploy` |
| `DEPLOY_SECRET` | exactly the same value as `DEPLOY_SECRET` in the server's `.env` |

Test it: Actions tab > *Deploy to PythonAnywhere* > *Run workflow*. A green run means the pull, backup, migration and
reload all worked.

### Every release after that

Work on `dev`. When you have checked it there, merge `dev` into `main` and push. The Action deploys it. Look at the
Actions tab (or the email GitHub sends) to see that it went green.

Nobody has to hard-refresh after a release: the CSS and JavaScript addresses carry a fingerprint of the file
(`app.js?v=3f9a1c2b7d`, see `app/assets.py`), so a changed file gets a new address and browsers fetch it by themselves. The
pages themselves are never cached, so a normal reload shows the new version.

If you ever need to do it by hand, in a Bash console: `cd ~/grtechno-app && git pull origin main`, then
`workon grtechno`, `pip install -r requirements.txt`, `flask --app wsgi db upgrade`, then press Reload on the Web tab.

### The database on the server

- **Where:** `~/grtechno-app/instance/leads.db`. It survives deploys, because git never touches it.
- **Backups:** every deploy copies it to `instance/backups/leads-YYYYMMDD-HHMMSS.db` first (newest 10 kept). To
  restore one, copy it over `instance/leads.db` and press Reload. Also download `leads.db` from the Files tab now and
  then, and use **Export CSV** as a second copy.
- **Looking inside or editing lists** (services, site categories, roles, ...): in a Bash console, run
  `sqlite3 ~/grtechno-app/instance/leads.db`, or download the file, edit it with DB Browser for SQLite and upload it back
  (do that while nobody is using the app).
- **Schema changes** always ship as migration files in `migrations/versions/`, so they are applied by the deploy.
- **Forgot the admin PIN:** `flask --app wsgi reset-pin grtechno-3766` in the Bash console prints a new setup code.

### Things to know on the free plan

These are from memory, so check PythonAnywhere's pricing and help pages: a free web app has to be extended from the Web
tab every three months or it is switched off; there is no custom domain; and the server can only call a short list of
allowed websites. The pincode lookup calls India Post from the server, so on the free plan it may be blocked. The forms
still work (type state, district and city by hand), and every pincode that has been looked up once is kept in the
`pincodes` table. A paid plan removes these limits, and later features such as scheduled alerts need one.

## Users and sign-in

- A **userid** is the person's name plus a random, unique 4-digit code, for example `ravikumar-4821`.
  The 4-digit code is the user's primary key.
- Only the **admin** (created once with `create-admin`, named `grtechno` by default) can add users. Open **Users & roles**
  in the left menu (Manage section), type a name, and the app shows the userid and a one-time **setup code**. Send them to the person
  (there is a WhatsApp button). The code works once and is valid for 7 days.
- The person opens `/set-pin` (also linked on the sign-in page), enters the userid and setup code, and chooses
  their own 6-digit PIN. Obvious PINs (all the same digit, or a run like 123456) are refused.
- **Forgot your PIN?** Ask the admin for **Reset PIN** (or **New setup code**). The old PIN stops
  working straight away and the person sets a new one the same way.
- **Turn off** signs someone out and blocks sign-in; their leads stay. There is one admin; if the admin forgets their
  PIN run `flask --app wsgi reset-pin <userid>`.
- After 5 wrong tries an account is locked for 5 minutes. That lockout is what protects a 6-digit PIN from guessing,
  so keep it in place.
- Everyone sees only the leads they added. The admin sees all leads, with each owner's name.

## Services and the left menu

Each service (Lead desk today) is a row in the `modules` table. The menu is built from it, so adding, hiding or
reordering a service is a database change:

| Column | Meaning |
|---|---|
| `key` | Short unique id used in code, for example `attendance` |
| `name` | Shown in the menu and as the page title |
| `icon` | `leads`, `attendance`, `manpower`, `material`, or anything else for a plain grid icon |
| `path` | Where the menu link goes, for example `/attendance` |
| `sort_order` | Menu order, lowest first |
| `is_active` | 0 hides the service **and blocks its pages and API** |
| `admin_only` | 1 makes it visible and usable by the admin only |

```sql
INSERT INTO modules (key, name, icon, path, sort_order) VALUES ('attendance', 'Attendance', 'attendance', '/attendance', 2);
UPDATE modules SET admin_only = 1 WHERE key = 'attendance';
UPDATE modules SET is_active = 0 WHERE key = 'attendance';
```

**Building a new service.** Give it its own blueprint (pages under `/attendance`, API under `/api/attendance`) and
call `check_module("attendance")` from it (or put `@module_required("attendance")` on a route, or call it in the
blueprint's `before_request`, the way Lead desk does). That makes the row above binding on the server, not just in the
menu. Its page extends `base.html`, so it gets the top bar, the menu button and the panel for free. `GET /api/modules`
returns the same list as JSON.

## Roles and who sees what

| Table | What it holds |
|---|---|
| `roles` | `key`, `name`, `sees_all`. `sees_all = 1` (Admin, Accounts) means every client and project is visible |
| `role_modules` | Which services (`modules.key`) a role can open. The admin can open all of them |

Default roles and what they open: **Sales (field) / Sales (office)**: Lead desk. **Project manager** and
**Accounts**: Clients and Projects. **Site supervisor**: nothing yet (the attendance and material services will come).
Change it in the database, for example:

```sql
INSERT INTO role_modules (role_key, module_key) VALUES ('supervisor', 'projects');
DELETE FROM role_modules WHERE role_key = 'accounts' AND module_key = 'clients';
UPDATE roles SET sees_all = 1 WHERE key = 'project_manager';
```

The admin picks a role when adding a user and can change it later from the Users screen.

**Who sees which records.** Leads: only the person who owns them, and the admin. Projects: the admin and `sees_all`
roles see all; everyone else sees projects they created or manage. Clients: `sees_all` roles see all; everyone else
sees clients they created and the clients of projects they manage. Only the admin (or a `sees_all` role) can assign a
project manager, and the manager must have the Project manager role.

**Won lead to project.** Open a won lead and tap **Create project**. It creates the project and a client (an existing
client with the same name is reused). The sales person who owns the lead does this even if their role cannot open
Projects; the project manager or admin then completes the work order details and payment schedule.

**Add project (work that did not come from a lead).** Admin, Accounts and project managers can add a project
directly: choose an existing client or enter a new client name (a client with the same name is reused), then add the
title, work category and status (default Running). A project manager who adds one becomes its manager; for the
admin or Accounts the manager is assigned afterwards.

**Site category and work categories** are rows in `site_categories` and `services` (same columns as the other
dropdown lists). The first version's four differently named services (Sprinklers, Hydrant and pump room, Extinguishers,
NOC and audits) were switched off, not deleted, when the blueprint's list was added, so old leads keep their value.

## Dropdown lists and settings (kept in the database)

The app has no settings screen. It only reads these tables, so change them straight in `instance/leads.db`
(any SQLite tool works, for example DB Browser for SQLite):

| Table | One row per | Columns |
|---|---|---|
| `services` | Work category | `name`, `sort_order`, `is_active` |
| `site_categories` | Site category (hospital, school, ...) | `name`, `sort_order`, `is_active` |
| `lead_sources` | Lead source choice | `name`, `sort_order`, `is_active` |
| `settings` | Single value | `key` = `currency` or `country_code`, `value` |
| `pincodes` | Pincode | `pincode`, `state`, `district`, `city` (filled from India Post on first use; correct a row here if it is wrong) |

Set `is_active` to 0 to hide a choice from new leads without touching leads that already use it. Lists are
sorted by `sort_order`, then name. Changes show up the next time the app loads its data (reload the page).
`flask db upgrade` fills the tables with a starting set of services and sources on first run.

```sql
INSERT INTO services (name, sort_order) VALUES ('CCTV', 8);
UPDATE lead_sources SET is_active = 0 WHERE name = 'Walk-in';
UPDATE settings SET value = '$' WHERE key = 'currency';
```

## Changing the data model

Edit `app/models.py`, then:

```bash
flask --app wsgi db migrate -m "describe the change"
flask --app wsgi db upgrade
```

Commit the new file in `migrations/versions/`. Run the same `db upgrade` on PythonAnywhere after you pull.

## Project layout

```
app/
  __init__.py        app factory
  config.py          settings read from .env
  models.py          Lead, Activity, ChecklistItem, User, Role, RoleModule, Module, Client, Project,
                     ProjectPayment, Service, LeadSource, SiteCategory, Setting, Pincode
  api.py             JSON endpoints under /api, validation, summary maths
  views.py           home page and CSV export
  auth.py            sign-in, setup codes, lockout, CSRF, who may see which leads
  users.py           admin-only user management API (add users, roles, reset PIN, turn off)
  assets.py          fingerprints CSS/JS addresses so browsers pick up new versions after a deploy
  deploy.py          the /deploy webhook: git pull, database backup, migrations, reload
  clients.py         Clients service: pages and API
  projects.py        Projects service: pages and API, and the won-lead-to-project step
  validation.py      field checks shared by the clients and projects APIs
  reference_data.py  starting roles, services, site categories (mirrored by the migration, and tested)
  modules.py         the services list, who may use which, and the check_module guard
  cli.py             `flask create-admin`, `reset-pin`, `seed-demo`
  constants.py       stage names
  templates/         base (top bar + menu), _sidebar, _icons, index, clients, projects, users, login, set_pin
  static/            css/app.css, js/common.js (shared helpers), js/app.js (Lead desk),
                     js/clients.js, js/projects.js, js/users.js (the Users page), js/shell.js (the left menu)
migrations/          database migrations (Flask-Migrate)
tests/               pytest suite
wsgi.py              entry point for the flask command and for PythonAnywhere
scripts/deploy.py    called by the GitHub Action to trigger a deploy
.github/workflows/   the deploy workflow
```

## Things to know

- Leads that existed before sign-in was added have no owner, so only the admin can see them.
- The whole lead list loads in one request. That is fast for thousands of leads; if you grow far past
  that, the API will need paging.
- Win rate is Won divided by Won plus Lost across all time. "Won this month" uses the date the lead
  moved to Won.
- The Service and Source dropdowns, the currency symbol and the WhatsApp country code are not edited in the
  app. They live in database tables (see above).
