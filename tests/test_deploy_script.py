import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "deploy.py"


def serve(status, payload, seen):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(self.headers.get("X-Deploy-Secret"))
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_script(url, secret="x" * 32):
    env = dict(os.environ, DEPLOY_URL=url, DEPLOY_SECRET=secret)
    return subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)


def test_script_reports_success_and_sends_the_secret():
    seen = []
    server = serve(200, {"ok": True, "output": "Updating abc..def", "backup": "leads-1.db", "requirements_changed": True}, seen)
    try:
        result = run_script(f"http://127.0.0.1:{server.server_port}/deploy")
    finally:
        server.shutdown()
    assert result.returncode == 0 and "SUCCESS" in result.stdout
    assert "leads-1.db" in result.stdout and "requirements.txt changed" in result.stdout
    assert seen == ["x" * 32]


def test_script_fails_loudly_when_the_server_reports_a_problem():
    server = serve(500, {"ok": False, "step": "database", "error": "boom", "output": "pulled"}, [])
    try:
        result = run_script(f"http://127.0.0.1:{server.server_port}/deploy")
    finally:
        server.shutdown()
    assert result.returncode == 1 and "step=database" in result.stdout and "boom" in result.stdout


def test_script_handles_a_wrong_secret_a_non_json_reply_and_missing_settings():
    forbidden = serve(403, {"error": "forbidden"}, [])
    html = serve(200, b"<html>not json</html>", [])
    try:
        assert run_script(f"http://127.0.0.1:{forbidden.server_port}/deploy").returncode == 1
        assert "did not return JSON" in run_script(f"http://127.0.0.1:{html.server_port}/deploy").stdout
    finally:
        forbidden.shutdown(); html.shutdown()
    missing = subprocess.run([sys.executable, str(SCRIPT)], env={k: v for k, v in os.environ.items() if not k.startswith("DEPLOY_")},
                             capture_output=True, text=True, timeout=30)
    assert missing.returncode == 1 and "must both be set" in missing.stdout
    assert run_script("http://127.0.0.1:1/deploy").returncode == 1                # nothing listening
