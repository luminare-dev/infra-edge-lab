"""scripts/tunnel_token.py: the tunnel token for one configure run (docs/adr/0011).

The script is tested against a stand-in for the Cloudflare API on a loopback port (the hidden
--api-base option); no test ever contacts Cloudflare. The tests pin the request (path and bearer
token), that only the token reaches standard output, and that no error message ever contains a
token or the API token. Standard library only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "tunnel_token.py"
ACCOUNT = "0123456789abcdef0123456789abcdef"
TUNNEL = "00000000-0000-4000-8000-000000000001"
# Synthetic values in the character sets of the real ones; they belong to no account.
API_TOKEN = "unit-test-api-token-not-real"
TUNNEL_TOKEN = "unit-test-tunnel-token-" + "x" * 40


class FakeApi(BaseHTTPRequestHandler):
    """Answers GET .../token with the status and body the test sets on the server."""

    def do_GET(self):  # noqa: N802 (http.server API)
        self.server.requests.append((self.path, self.headers.get("Authorization")))
        body = json.dumps(self.server.answer).encode() if isinstance(self.server.answer, dict) else self.server.answer
        self.send_response(self.server.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the test output clean
        pass


class TunnelTokenTest(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
        self.server.requests = []
        self.server.status = 200
        self.server.answer = {"success": True, "errors": [], "messages": [], "result": TUNNEL_TOKEN}
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/client/v4"

    def run_script(self, *args: str, **env: str | None) -> subprocess.CompletedProcess:
        environ = {k: v for k, v in os.environ.items() if k not in ("CLOUDFLARE_API_TOKEN", "TF_VAR_account_id")}
        environ.update(CLOUDFLARE_API_TOKEN=API_TOKEN, TF_VAR_account_id=ACCOUNT)
        for key, value in env.items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        return subprocess.run([sys.executable, str(SCRIPT), "--api-base", self.base, *args], env=environ,
                              capture_output=True, text=True, timeout=30, check=False)

    def test_prints_only_the_token(self):
        out = self.run_script("--tunnel-id", TUNNEL)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, TUNNEL_TOKEN + "\n")
        self.assertEqual(out.stderr, "")
        self.assertEqual(self.server.requests,
                         [(f"/client/v4/accounts/{ACCOUNT}/cfd_tunnel/{TUNNEL}/token", f"Bearer {API_TOKEN}")])

    def test_account_from_the_command_line(self):
        other = "f" * 32
        out = self.run_script("--tunnel-id", TUNNEL, "--account-id", other, TF_VAR_account_id=None)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"/accounts/{other}/", self.server.requests[0][0])

    def test_refusals_never_show_a_secret(self):
        cases = {
            "HTTP 403 with an error list": (403, {"success": False, "errors": [{"code": 10000, "message":
                                                                               "Authentication error"}],
                                                  "result": TUNNEL_TOKEN}),
            "success false": (200, {"success": False, "errors": [], "result": TUNNEL_TOKEN}),
            "no token": (200, {"success": True, "result": None}),
            "a token with odd characters": (200, {"success": True, "result": TUNNEL_TOKEN + " <x>"}),
            "not JSON": (200, b"<html>maintenance</html>"),
        }
        for label, (status, answer) in cases.items():
            with self.subTest(case=label):
                self.server.status, self.server.answer = status, answer
                out = self.run_script("--tunnel-id", TUNNEL)
                self.assertEqual(out.returncode, 1)
                self.assertEqual(out.stdout, "")
                self.assertIn("tunnel_token.py:", out.stderr)
                self.assertNotIn(TUNNEL_TOKEN, out.stderr)
                self.assertNotIn(API_TOKEN, out.stderr)
        self.server.status, self.server.answer = 403, cases["HTTP 403 with an error list"][1]
        self.assertIn("10000: Authentication error", self.run_script("--tunnel-id", TUNNEL).stderr)

    def test_checks_its_inputs_before_any_request(self):
        cases = {
            "no API token": ({"CLOUDFLARE_API_TOKEN": None}, ("--tunnel-id", TUNNEL)),
            "no account": ({"TF_VAR_account_id": None}, ("--tunnel-id", TUNNEL)),
            "account that is no ID": ({"TF_VAR_account_id": "../../zones"}, ("--tunnel-id", TUNNEL)),
            "tunnel ID that is no UUID": ({}, ("--tunnel-id", "../token")),
        }
        for label, (env, args) in cases.items():
            with self.subTest(case=label):
                out = self.run_script(*args, **env)
                self.assertEqual(out.returncode, 2)
                self.assertEqual(out.stdout, "")
        self.assertEqual(self.server.requests, [])

    def test_unreachable_api(self):
        self.base = "http://127.0.0.1:9/client/v4"
        out = self.run_script("--tunnel-id", TUNNEL)
        self.assertEqual(out.returncode, 1)
        self.assertIn("could not be reached", out.stderr)
        self.assertNotIn(API_TOKEN, out.stderr)


if __name__ == "__main__":
    unittest.main()
