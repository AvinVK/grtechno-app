# Lead desk

Lead management for a fire protection installation business. Track enquiries from first call to
won or lost, see who to call today, and keep notes on every lead. Flask + SQLite, no build step.

- **Sign-in with your own userid.** The admin adds people; each person sets their own 6-digit PIN.
  Everyone sees only their own leads; the admin sees all of them and manages users.
- **Bottom tabs** (phone-first): **Active leads**, **Add lead**, **Won / Lost** and **Your status**
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

1. **Push this code to GitHub** (`AvinVK/fire-client-lead-management`). `.env` and `instance/` are
   git-ignored, so your data and secrets are never uploaded.
2. On PythonAnywhere open a **Bash console** and run (replace `YOURNAME`):

   ```bash
   git clone https://github.com/AvinVK/fire-client-lead-management.git
   cd fire-client-lead-management
   mkvirtualenv leads --python=python3.12     # use a Python version PythonAnywhere offers
   pip install -r requirements.txt
   cp .env.example .env
   nano .env                                  # set SESSION_COOKIE_SECURE=1 (and SECRET_KEY if you want your own)
   flask --app wsgi db upgrade
   flask --app wsgi create-admin              # prints the admin userid and one-time setup code
   ```

3. **Web tab** → *Add a new web app* → *Manual configuration* → pick the same Python version.
   - Source code and Working directory: `/home/YOURNAME/fire-client-lead-management`
   - Virtualenv: `/home/YOURNAME/.virtualenvs/leads`
   - Static files: URL `/static/` → Directory `/home/YOURNAME/fire-client-lead-management/app/static`
4. Open the **WSGI configuration file** from the Web tab, replace its contents with:

   ```python
   import sys
   path = "/home/YOURNAME/fire-client-lead-management"
   if path not in sys.path:
       sys.path.insert(0, path)

   from app import create_app
   application = create_app()
   ```
5. Click **Reload**. Visit `https://YOURNAME.pythonanywhere.com/set-pin`, use the admin userid and setup code, then sign in.

**Updating later:**

```bash
cd ~/fire-client-lead-management && git pull
pip install -r requirements.txt
flask --app wsgi db upgrade
```

then Reload on the Web tab.

**Back up your data.** Download `instance/leads.db` from the PythonAnywhere Files tab now and then,
and use Export CSV as a second copy.

## Users and sign-in

- A **userid** is the person's name plus a random, unique 4-digit code, for example `ravikumar-4821`.
  The 4-digit code is the user's primary key.
- Only the **admin** (created once with `create-admin`, named `grtechno` by default) can add users. Open **Users**
  in the top bar, type a name, and the app shows the userid and a one-time **setup code**. Send them to the person
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

## Dropdown lists and settings (kept in the database)

The app has no settings screen. It only reads these tables, so change them straight in `instance/leads.db`
(any SQLite tool works, for example DB Browser for SQLite):

| Table | One row per | Columns |
|---|---|---|
| `services` | Service choice | `name`, `sort_order`, `is_active` |
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
  models.py          Lead, Activity, User, Service, LeadSource, Setting, Pincode
  api.py             JSON endpoints under /api, validation, summary maths
  views.py           home page and CSV export
  auth.py            sign-in, setup codes, lockout, CSRF, who may see which leads
  users.py           admin-only user management API
  cli.py             `flask create-admin`, `reset-pin`, `seed-demo`
  constants.py       stage names
  templates/         base, index, login
  static/            css/app.css, js/app.js
migrations/          database migrations (Flask-Migrate)
tests/               pytest suite
wsgi.py              entry point for the flask command
```

## Things to know

- Leads that existed before sign-in was added have no owner, so only the admin can see them.
- The whole lead list loads in one request. That is fast for thousands of leads; if you grow far past
  that, the API will need paging.
- Win rate is Won divided by Won plus Lost across all time. "Won this month" uses the date the lead
  moved to Won.
- The Service and Source dropdowns, the currency symbol and the WhatsApp country code are not edited in the
  app. They live in database tables (see above).
