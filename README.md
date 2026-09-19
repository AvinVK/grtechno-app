# Lead desk

Lead management for a fire protection installation business. Track enquiries from first call to
won or lost, see who to call today, and keep notes on every lead. Flask + SQLite, no build step.

- **Bottom tabs** (phone-first): **Active leads**, **Add lead**, and **Won / Lost**.
- **Active leads**: every lead still in progress (New enquiry, Site survey, Quote sent, Negotiation),
  earliest follow-up first, with search and stage filter chips. Tap a lead to update its stage,
  follow-up, notes and activity log. No drag and drop.
- **Add lead** always starts a lead at New enquiry.
- **Won / Lost** are outcomes, set by the user with the Mark won / Mark lost buttons inside a lead.
  Those leads move to the Won / Lost tab; set a lead's Status back to an active stage to reopen it.
- **Each lead**: contact, company, phone, email, site address, service, estimated value, source,
  follow-up date, notes, one-tap Call / WhatsApp / Email, and an activity log (notes plus automatic
  stage and follow-up changes).
- **Export CSV** from the top bar (or the bottom of All leads on a phone).
- **Settings** page to edit the services list, lead sources, currency symbol and WhatsApp country code.

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
flask --app wsgi run --debug
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
flask --app wsgi db upgrade
flask --app wsgi run --debug
```

Open http://127.0.0.1:5000.

`flask db upgrade` creates `instance/leads.db`. Want sample data to click around in?

```bash
flask --app wsgi seed-demo            # adds 12 fictional leads
flask --app wsgi seed-demo --force    # wipes ALL leads first, then adds them
```

Locally the app has no login. Setting `APP_PASSWORD` in `.env` turns the login screen on.

### Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs the login session. Use a long random value when hosting. |
| `APP_PASSWORD` | One shared password for the whole team. Empty means no login. **Always set it when hosted.** |
| `TIMEZONE` | Decides what "today" means for follow-ups. Default `Asia/Kolkata`. |
| `SESSION_COOKIE_SECURE` | Set to `1` once the site is on HTTPS. |
| `DATABASE_URL` | Optional. Overrides the SQLite file location. |

Generate a secret key with: `python -c "import secrets; print(secrets.token_hex(32))"`

The app refuses to start if `APP_PASSWORD` is set but `SECRET_KEY` is still the default.

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
   nano .env                                  # set SECRET_KEY, APP_PASSWORD, SESSION_COOKIE_SECURE=1
   flask --app wsgi db upgrade
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
5. Click **Reload**. Visit `https://YOURNAME.pythonanywhere.com` and sign in with `APP_PASSWORD`.

**Updating later:**

```bash
cd ~/fire-client-lead-management && git pull
pip install -r requirements.txt
flask --app wsgi db upgrade
```

then Reload on the Web tab.

**Back up your data.** Download `instance/leads.db` from the PythonAnywhere Files tab now and then,
and use Export CSV as a second copy.

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
  models.py          Lead, Activity, Setting
  api.py             JSON endpoints under /api, validation, summary maths
  views.py           pages, CSV export, settings form
  auth.py            shared-password login and CSRF for forms
  cli.py             `flask seed-demo`
  constants.py       stage names and default lists
  templates/         base, index, login, settings
  static/            css/app.css, js/app.js
migrations/          database migrations (Flask-Migrate)
tests/               pytest suite
wsgi.py              entry point for the flask command
```

## Things to know

- **One shared password**, not per-person accounts. Everyone who signs in sees and can change everything.
  There is no lockout after wrong guesses, so pick a long password.
- The whole lead list loads in one request. That is fast for thousands of leads; if you grow far past
  that, the API will need paging.
- Win rate is Won divided by Won plus Lost across all time. "Won this month" uses the date the lead
  moved to Won.
- The default services and sources are a starting guess. Replace them on the Settings page.
