#!/usr/bin/env python3
"""Trigger a deploy on PythonAnywhere through the app's own /deploy webhook (see app/deploy.py).

Set two environment variables (in GitHub: Settings > Secrets and variables > Actions):
    DEPLOY_URL     for example https://YOURNAME.pythonanywhere.com/deploy
    DEPLOY_SECRET  the same value as DEPLOY_SECRET in the server's .env file
Uses only the Python standard library, so nothing has to be installed first.
"""

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> None:
    url = (os.environ.get("DEPLOY_URL") or "").strip()
    secret = (os.environ.get("DEPLOY_SECRET") or "").strip()
    if not url or not secret:
        print("FAILURE: DEPLOY_URL and DEPLOY_SECRET must both be set.")
        sys.exit(1)

    print(f"Triggering deploy at {url} ...")
    request = urllib.request.Request(url, method="POST", headers={"X-Deploy-Secret": secret})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as err:
        status, raw = err.code, err.read()
    except urllib.error.URLError as err:
        print(f"FAILURE: could not reach the server ({err.reason}).")
        sys.exit(1)

    try:
        body = json.loads(raw)
    except ValueError:
        print(f"FAILURE: the deploy endpoint did not return JSON (status {status}).")
        print(raw[:500].decode("utf-8", "replace"))
        sys.exit(1)

    if status != 200 or not body.get("ok"):
        print(f"FAILURE: deploy failed (status {status}, step={body.get('step')}).")
        if body.get("error"):
            print("error:", body["error"])
        print("---- output ----")
        print(body.get("output", body))
        print("-----------------")
        sys.exit(1)

    print("SUCCESS: code pulled, database migrated, web app reloaded.")
    if body.get("backup"):
        print("Database backup:", body["backup"])
    if body.get("requirements_changed"):
        print("WARNING: requirements.txt changed. Open a Bash console on PythonAnywhere, activate the virtualenv, "
              "run `pip install -r requirements.txt`, then reload the web app.")
    print("---- git pull output ----")
    print(body.get("output", ""))
    print("--------------------------")


if __name__ == "__main__":
    main()
