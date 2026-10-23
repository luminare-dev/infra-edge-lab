"""scripts/cloudflare_api.py and the shell scripts around it (cf_preflight.sh, sweep_demo.sh,
dns_backup.sh): the checks before an apply, the zone copy and comparison, and the sweeper.

Everything runs against a stand-in for the Cloudflare API on a loopback port (CLOUDFLARE_API_BASE,
which the script accepts for 127.0.0.1 only); no test ever contacts Cloudflare. The zone is
example.com, every ID is synthetic. The tests pin which requests are made (and that the checks
send reads only), which records count as managed, which objects the sweeper deletes and in which
order, and that no output contains the API token. Standard library only; the dns_backup.sh tests
also need age and age-keygen and are skipped without them.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "cloudflare_api.py"
sys.path.insert(0, str(ROOT / "scripts"))
import cloudflare_api  # noqa: E402  (the module under test)

ACCOUNT = "0123456789abcdef0123456789abcdef"
ZONE_ID = "fedcba9876543210fedcba9876543210"
ZONE = "example.com"
API_TOKEN = "unit-test-api-token-not-real"
OLD = "2026-10-01T08:00:00.123456789Z"
NEW = "2026-10-22T10:30:00.5Z"


def uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def rid(n: int) -> str:
    return f"{n:032x}"


def zone_records() -> list[dict]:
    """A zone like the shared one: the site, mail and other records, none of them managed here."""
    return [
        {"id": rid(1), "name": ZONE, "type": "A", "content": "192.0.2.10", "proxied": True, "ttl": 1,
         "comment": None, "created_on": OLD, "modified_on": OLD},
        {"id": rid(2), "name": f"www.{ZONE}", "type": "AAAA", "content": "2001:db8::10", "proxied": True,
         "ttl": 1, "comment": None, "created_on": OLD, "modified_on": OLD},
        {"id": rid(3), "name": ZONE, "type": "MX", "content": f"mail.{ZONE}", "priority": 10, "proxied": False,
         "ttl": 3600, "comment": None, "created_on": OLD, "modified_on": OLD},
        {"id": rid(4), "name": f"_dmarc.{ZONE}", "type": "TXT", "content": '"v=DMARC1; p=reject"',
         "proxied": False, "ttl": 3600, "comment": None, "created_on": OLD, "modified_on": OLD},
    ]


def demo_objects(created: str = NEW) -> dict:
    """What one run of the demo environment creates (tofu/envs/demo with tunnel demo-e2e)."""
    return {
        "records": [
            {"id": rid(20 + i), "name": f"{label}.{ZONE}", "type": "CNAME", "content": f"{uuid(1)}.cfargotunnel.com",
             "proxied": True, "ttl": 1, "comment": "managed-by-tofu env=demo", "created_on": created,
             "modified_on": created} for i, label in enumerate(("demo-web", "demo-ssh"))],
        "tunnels": [{"id": uuid(1), "name": "demo-e2e", "status": "inactive", "created_at": created,
                     "connections": []}],
        "apps": [{"id": uuid(10 + i), "name": label, "domain": f"{label}.{ZONE}", "created_at": created}
                 for i, label in enumerate(("demo-web", "demo-ssh"))],
        "policies": [{"id": uuid(20 + i), "name": f"{label} service auth", "created_at": created}
                     for i, label in enumerate(("demo-web", "demo-ssh"))],
        "tokens": [{"id": uuid(30 + i), "name": f"{label} service token", "client_id": f"client-{i}.access",
                    "created_at": created} for i, label in enumerate(("demo-web", "demo-ssh"))],
    }


class FakeApi(BaseHTTPRequestHandler):
    """The few endpoints the scripts use, with pagination, refusals and deletions."""

    def answer(self, status: int, body) -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json" if not isinstance(body, bytes) else "text/plain")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def route(self, path: str):
        """(list name, item id) of a path, or None."""
        s = self.server
        patterns = (
            (rf"^/client/v4/zones/{ZONE_ID}/dns_records(?:/([0-9a-f]+))?$", "records"),
            (rf"^/client/v4/accounts/{ACCOUNT}/cfd_tunnel(?:/([0-9a-f-]+))?$", "tunnels"),
            (rf"^/client/v4/accounts/{ACCOUNT}/access/apps(?:/([0-9a-f-]+))?$", "apps"),
            (rf"^/client/v4/accounts/{ACCOUNT}/access/policies(?:/([0-9a-f-]+))?$", "policies"),
            (rf"^/client/v4/accounts/{ACCOUNT}/access/service_tokens(?:/([0-9a-f-]+))?$", "tokens"),
        )
        for pattern, name in patterns:
            m = re.match(pattern, path)
            if m:
                return name, m.group(1)
        del s
        return None

    def handle_any(self, method: str) -> None:
        url = urlsplit(self.path)
        s = self.server
        s.requests.append((method, url.path, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != f"Bearer {API_TOKEN}":
            return self.answer(403, {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]})
        for refused in s.refused:
            if refused in url.path:
                return self.answer(403, {"success": False, "errors": [{"code": 9109, "message": "Unauthorized"}]})
        if url.path == f"/client/v4/zones/{ZONE_ID}/dns_records/export" and method == "GET":
            return self.answer(200, s.export.encode())
        if method == "DELETE" and url.path.endswith("/connections"):
            return self.answer(200, {"success": True, "errors": [], "result": None})
        found = self.route(url.path)
        if not found:
            return self.answer(404, {"success": False, "errors": [{"code": 7003, "message": "No route"}]})
        name, item_id = found
        items = s.data[name]
        if method == "DELETE":
            before = len(items)
            s.data[name] = [i for i in items if i["id"] != item_id]
            ok = len(s.data[name]) < before
            return self.answer(200 if ok else 404, {"success": ok, "errors": [], "result": {"id": item_id}})
        if item_id:
            item = next((i for i in items if i["id"] == item_id), None)
            if name == "tunnels" and item is not None:
                s.status_calls += 1
                if s.status_calls >= s.healthy_after:
                    item = {**item, "status": "healthy", "connections": [{"id": "c1"}]}
            return self.answer(200 if item else 404, {"success": item is not None, "errors": [], "result": item})
        query = parse_qs(url.query)
        page, per_page = int(query.get("page", ["1"])[0]), int(query.get("per_page", ["100"])[0])
        per_page = min(per_page, s.page_size)
        chunk = items[(page - 1) * per_page: page * per_page]
        pages = max(1, -(-len(items) // per_page))
        return self.answer(200, {"success": True, "errors": [], "result": chunk,
                                 "result_info": {"page": page, "per_page": per_page, "total_pages": pages,
                                                 "total_count": len(items)}})

    def do_GET(self):  # noqa: N802 (http.server API)
        self.handle_any("GET")

    def do_DELETE(self):  # noqa: N802
        self.handle_any("DELETE")

    def do_POST(self):  # noqa: N802 - never used by the scripts; recorded so a test can see it
        self.handle_any("POST")

    def log_message(self, *args):
        pass


class ApiTestCase(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
        self.server.requests = []
        self.server.refused = []
        self.server.page_size = 3  # small pages, so every list is read across pages
        self.server.status_calls = 0
        self.server.healthy_after = 1
        self.server.export = (f";; Domain:     {ZONE}.\n{ZONE}.\t3600\tIN\tSOA\tns.{ZONE}. dns.{ZONE}. 1 1 1 1 1\n"
                              f"www.{ZONE}.\t1\tIN\tAAAA\t2001:db8::10\n")
        self.server.data = {"records": zone_records(), "tunnels": [], "apps": [], "policies": [], "tokens": []}
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/client/v4"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def add(self, objects: dict) -> None:
        for name, items in objects.items():
            self.server.data[name] += copy.deepcopy(items)

    def environ(self, **env: str | None) -> dict[str, str]:
        environ = {k: v for k, v in os.environ.items()
                   if not k.startswith(("TF_VAR_", "CLOUDFLARE_", "SECRETS", "DNS_BACKUP_", "SOPS_"))}
        environ.update(CLOUDFLARE_API_TOKEN=API_TOKEN, CLOUDFLARE_API_BASE=self.base, TF_VAR_account_id=ACCOUNT,
                       TF_VAR_zone_id=ZONE_ID, TF_VAR_zone=ZONE, SECRETS_LOADED="1")
        for key, value in env.items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        return environ

    def run_cli(self, *args: str, **env: str | None) -> subprocess.CompletedProcess:
        out = subprocess.run([sys.executable, str(SCRIPT), *args], env=self.environ(**env), capture_output=True,
                             text=True, timeout=60, check=False)
        self.assertNotIn(API_TOKEN, out.stdout + out.stderr)
        return out

    def methods(self) -> set[str]:
        return {method for method, _, _ in self.server.requests}


def plan(*changes: tuple[str, str, list[str], dict | None, dict | None]) -> dict:
    """A plan in the shape of tofu show -json: (address, type, actions, before, after)."""
    return {"format_version": "1.2", "resource_changes": [
        {"address": address, "type": rtype, "change": {"actions": actions, "before": before, "after": after}}
        for address, rtype, actions, before, after in changes]}


def demo_plan() -> dict:
    """The resources a plan of the tunnel test creates (as tofu show -json printed them)."""
    changes = []
    for label in ("demo-ssh", "demo-web"):
        changes.append((f'module.tunnel.cloudflare_dns_record.tunnel["{label}"]', "cloudflare_dns_record", ["create"],
                        None, {"name": f"{label}.{ZONE}", "type": "CNAME", "comment": "managed-by-tofu env=demo",
                               "proxied": True}))
        changes.append((f'module.access.cloudflare_zero_trust_access_application.this["{label}"]',
                        "cloudflare_zero_trust_access_application", ["create"], None,
                        {"name": label, "domain": f"{label}.{ZONE}"}))
    changes.append(("module.tunnel.cloudflare_zero_trust_tunnel_cloudflared.this",
                    "cloudflare_zero_trust_tunnel_cloudflared", ["create"], None, {"name": "demo-e2e"}))
    changes.append(('module.containers[0].docker_container.host["edge-01"]', "docker_container", ["create"], None,
                    {"name": "lab-e2e-demo-edge-01"}))
    return plan(*changes)


class NameRulesTest(unittest.TestCase):
    def test_patterns_are_those_of_both_modules(self):
        for module in ("cf_tunnel", "cf_access_app"):
            guard = (ROOT / "tofu" / "modules" / module / "guard.tf").read_text(encoding="utf-8")
            for env, pattern in cloudflare_api.NAME_PATTERNS.items():
                with self.subTest(module=module, env=env):
                    self.assertRegex(guard, rf'\n\s+{env}\s+= "{re.escape(pattern)}"\n')

    def test_comment_and_tunnel_prefixes_are_those_of_the_tunnel_module(self):
        main = (ROOT / "tofu" / "modules" / "cf_tunnel" / "main.tf").read_text(encoding="utf-8")
        self.assertIn('comment = "managed-by-tofu env=${var.env}"', main)
        guard = (ROOT / "tofu" / "modules" / "cf_tunnel" / "guard.tf").read_text(encoding="utf-8")
        self.assertIn('tunnel_prefix = lookup({ lab = "lab-", demo = "demo-", showcase = "show-" }, var.env, "-")',
                      guard)
        self.assertEqual(cloudflare_api.TUNNEL_PREFIXES, {"lab": "lab-", "demo": "demo-", "showcase": "show-"})

    def test_demo_object_names_are_those_of_the_access_module(self):
        main = (ROOT / "tofu" / "modules" / "cf_access_app" / "main.tf").read_text(encoding="utf-8")
        self.assertIn('name       = "${each.key} service token"', main)
        self.assertIn('name       = "${each.key} service auth"', main)
        self.assertIn('name             = "${var.env} allow listed e-mail addresses"', main)
        self.assertTrue(cloudflare_api.DEMO_TOKEN_RE.match("demo-web service token"))
        self.assertTrue(any(p.match("demo allow listed e-mail addresses") for p in cloudflare_api.DEMO_POLICY_RES))

    def test_labels_and_times(self):
        self.assertEqual(cloudflare_api.label_of(ZONE, ZONE), "@")
        self.assertEqual(cloudflare_api.label_of(f"demo-web.{ZONE}", ZONE), "demo-web")
        self.assertIsNone(cloudflare_api.label_of("demo-web.example.net", ZONE))
        self.assertIsNone(cloudflare_api.label_of(f"x{ZONE}", ZONE))
        self.assertTrue(cloudflare_api.managed_label("play", "showcase"))
        self.assertFalse(cloudflare_api.managed_label("demo-web", "lab"))
        self.assertFalse(cloudflare_api.managed_label("x.demo-web", "demo"))
        self.assertEqual(cloudflare_api.parse_time(OLD).isoformat(), "2026-10-01T08:00:00.123456+00:00")
        self.assertIsNone(cloudflare_api.parse_time("yesterday"))


class PermissionsTest(ApiTestCase):
    def test_lists_the_permissions_without_a_request(self):
        apply = self.run_cli("permissions", "--env", "demo")
        self.assertEqual(apply.returncode, 0, apply.stderr)
        for line in ("Account · Cloudflare Tunnel · Edit", "Account · Access: Apps and Policies · Edit",
                     "Account · Access: Service Tokens · Edit", "Zone · DNS · Edit"):
            self.assertIn(line, apply.stdout)
        read_only = self.run_cli("permissions", "--env", "lab", "--read-only")
        self.assertIn("Zone · DNS · Read", read_only.stdout)
        self.assertNotIn("Edit", read_only.stdout)
        self.assertEqual(self.server.requests, [])


class PreflightTest(ApiTestCase):
    def preflight(self, *args: str, **env) -> subprocess.CompletedProcess:
        return self.run_cli("preflight", "--env", "demo", *args, **env)

    def plan_file(self, data: dict) -> str:
        path = self.tmp / "plan.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def test_passes_for_a_zone_without_demo_records_and_sends_reads_only(self):
        out = self.preflight()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("preflight of demo: passed", out.stdout)
        self.assertIn("Edit permissions: not checked", out.stdout)
        self.assertEqual(self.methods(), {"GET"})
        paths = {path for _, path, _ in self.server.requests}
        for suffix in (f"/zones/{ZONE_ID}/dns_records", f"/accounts/{ACCOUNT}/cfd_tunnel",
                       f"/accounts/{ACCOUNT}/access/apps", f"/accounts/{ACCOUNT}/access/service_tokens"):
            self.assertIn(f"/client/v4{suffix}", paths)

    def test_refuses_a_record_under_the_prefix_that_this_repository_did_not_create(self):
        self.add({"records": [{"id": rid(9), "name": f"demo-manual.{ZONE}", "type": "A", "content": "192.0.2.9",
                               "comment": None, "created_on": OLD}]})
        out = self.preflight()
        self.assertEqual(out.returncode, 1)
        self.assertIn(f"A demo-manual.{ZONE} has the prefix of demo but not the comment", out.stderr)

    def test_records_of_other_environments_do_not_matter(self):
        self.add({"records": [{"id": rid(9), "name": f"lab-pve.{ZONE}", "type": "CNAME", "content": "x",
                               "comment": "managed-by-tofu env=lab", "created_on": OLD}]})
        self.assertEqual(self.preflight().returncode, 0)

    def test_refuses_a_zone_id_of_another_zone(self):
        out = self.preflight(TF_VAR_zone="example.org")
        self.assertEqual(out.returncode, 1)
        self.assertIn("TF_VAR_zone_id does not belong to TF_VAR_zone", out.stderr)

    def test_names_the_permission_that_a_read_does_not_show(self):
        self.server.refused = ["/access/service_tokens"]
        out = self.preflight()
        self.assertEqual(out.returncode, 1)
        self.assertIn("Account · Access: Service Tokens · Read", out.stderr)
        self.assertIn("9109: Unauthorized", out.stderr)

    def test_a_plan_of_new_demo_records_passes(self):
        out = self.preflight("--plan-json", self.plan_file(demo_plan()))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("2 DNS record change(s) checked", out.stdout)
        self.assertIn("1 new tunnel(s) and 2 new Access application(s) checked", out.stdout)
        self.assertEqual(self.methods(), {"GET"})

    def test_a_plan_over_left_over_objects_is_refused(self):
        self.add(demo_objects())
        out = self.preflight("--plan-json", self.plan_file(demo_plan()))
        self.assertEqual(out.returncode, 1)
        self.assertIn(f"the plan would create demo-web.{ZONE}, but the zone already has CNAME", out.stderr)
        self.assertIn("task sweep:demo", out.stderr)
        self.assertIn("the plan would create the tunnel demo-e2e, which exists already", out.stderr)
        self.assertIn(f"Access application for demo-ssh.{ZONE}, which has one already", out.stderr)

    def test_a_plan_that_touches_a_record_outside_the_prefix_is_refused(self):
        cases = {
            "creates www": plan(("r", "cloudflare_dns_record", ["create"], None,
                                 {"name": f"www.{ZONE}", "type": "CNAME"})),
            "changes the apex": plan(("r", "cloudflare_dns_record", ["update"],
                                      {"id": rid(1), "name": ZONE, "type": "A"}, {"name": ZONE, "type": "A"})),
            "renames into the mail record": plan(("r", "cloudflare_dns_record", ["update"],
                                                  {"name": f"demo-web.{ZONE}", "type": "CNAME"},
                                                  {"name": f"_dmarc.{ZONE}", "type": "CNAME"})),
            "writes MX": plan(("r", "cloudflare_dns_record", ["create"], None,
                               {"name": f"demo-mx.{ZONE}", "type": "MX"})),
            "another zone": plan(("r", "cloudflare_dns_record", ["create"], None,
                                  {"name": "demo-web.example.net", "type": "CNAME"})),
        }
        for label, data in cases.items():
            with self.subTest(case=label):
                out = self.preflight("--plan-json", self.plan_file(data))
                self.assertEqual(out.returncode, 1, out.stdout)
                self.assertIn("preflight: refused:", out.stderr)

    def test_a_plan_that_deletes_an_unmarked_record_is_refused(self):
        self.add({"records": [{"id": rid(9), "name": f"demo-old.{ZONE}", "type": "CNAME", "content": "x",
                               "comment": "made by hand", "created_on": OLD}]})
        data = plan(("r", "cloudflare_dns_record", ["delete"],
                     {"id": rid(9), "name": f"demo-old.{ZONE}", "type": "CNAME"}, None))
        out = self.preflight("--plan-json", self.plan_file(data))
        self.assertEqual(out.returncode, 1)
        self.assertIn(f"would change or delete CNAME demo-old.{ZONE}, which does not carry the comment", out.stderr)

    def test_a_plan_that_deletes_its_own_record_passes(self):
        self.add({"records": demo_objects()["records"]})
        data = plan(("r", "cloudflare_dns_record", ["delete"],
                     {"id": rid(20), "name": f"demo-web.{ZONE}", "type": "CNAME"}, None),
                    ("s", "cloudflare_dns_record", ["no-op"], {"name": f"www.{ZONE}"}, {"name": f"www.{ZONE}"}))
        out = self.preflight("--plan-json", self.plan_file(data))
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_checks_its_inputs_before_any_request(self):
        cases = {
            "no API token": {"CLOUDFLARE_API_TOKEN": None},
            "account that is no ID": {"TF_VAR_account_id": "../../zones"},
            "zone ID that is no ID": {"TF_VAR_zone_id": "x"},
            "zone with a trailing dot": {"TF_VAR_zone": f"{ZONE}."},
        }
        for label, env in cases.items():
            with self.subTest(case=label):
                self.assertEqual(self.preflight(**env).returncode, 2)
        self.assertEqual(self.preflight("--plan-json", str(self.tmp / "missing.json")).returncode, 2)
        self.assertEqual(self.server.requests, [])

    def test_only_a_loopback_base_replaces_the_api(self):
        self.assertEqual(cloudflare_api.API_BASE, "https://api.cloudflare.com/client/v4")
        for base, expected in (("http://127.0.0.1:8080/client/v4", "http://127.0.0.1:8080/client/v4"),
                               ("https://api.example.com/client/v4", cloudflare_api.API_BASE),
                               ("http://127.0.0.1.example.com/x", cloudflare_api.API_BASE)):
            with self.subTest(base=base):
                os.environ["CLOUDFLARE_API_BASE"] = base
                try:
                    self.assertEqual(cloudflare_api.api_base(), expected)
                finally:
                    del os.environ["CLOUDFLARE_API_BASE"]


class SnapshotTest(ApiTestCase):
    def test_snapshot_leaves_out_the_environment_and_what_changes_by_itself(self):
        self.add({"records": demo_objects()["records"]})
        path = self.tmp / "before.json"
        out = self.run_cli("snapshot", "--exclude-env", "demo", "--output", str(path))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        records = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(records), 4)
        self.assertFalse(any(r["name"].startswith("demo-") for r in records))
        self.assertFalse(any({"id", "created_on", "modified_on"} & set(r) for r in records))
        self.assertNotIn("192.0.2.10", out.stdout)

    def test_compare_names_the_records_that_differ(self):
        before, after = self.tmp / "before.json", self.tmp / "after.json"
        self.run_cli("snapshot", "--exclude-env", "demo", "--output", str(before))
        self.server.data["records"][1]["content"] = "2001:db8::11"
        self.add({"records": demo_objects()["records"]})
        self.run_cli("snapshot", "--exclude-env", "demo", "--output", str(after))
        out = self.run_cli("compare", str(before), str(after))
        self.assertEqual(out.returncode, 1)
        self.assertIn(f"gone or changed: AAAA www.{ZONE}", out.stdout)
        self.assertIn(f"new or changed: AAAA www.{ZONE}", out.stdout)
        self.assertNotIn("2001:db8::1", out.stdout)
        self.assertNotIn("demo-web", out.stdout)
        same = self.run_cli("compare", str(after), str(after))
        self.assertEqual(same.returncode, 0)
        self.assertIn("unchanged", same.stdout)

    def test_export_prints_the_zone_file(self):
        out = self.run_cli("export")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, self.server.export)
        self.assertIn("export: 2 record line(s)", out.stderr)
        self.server.export = "<html>maintenance</html>"
        self.assertEqual(self.run_cli("export").returncode, 1)


class SweepTest(ApiTestCase):
    def foreign_objects(self) -> dict:
        """Objects the sweeper must never touch: other environments, unmarked names, other zones."""
        return {
            "records": [
                {"id": rid(40), "name": f"lab-pve.{ZONE}", "type": "CNAME", "content": "x",
                 "comment": "managed-by-tofu env=lab", "created_on": NEW},
                {"id": rid(41), "name": f"demo-hand.{ZONE}", "type": "CNAME", "content": "x",
                 "comment": "made by hand", "created_on": NEW},
            ],
            "tunnels": [{"id": uuid(40), "name": "show-edge", "status": "inactive", "created_at": NEW}],
            "apps": [{"id": uuid(41), "name": "demo-web", "domain": "demo-web.example.net", "created_at": NEW},
                     {"id": uuid(42), "name": "lab-pve", "domain": f"lab-pve.{ZONE}", "created_at": NEW}],
            "policies": [{"id": uuid(43), "name": "lab allow listed e-mail addresses", "created_at": NEW}],
            "tokens": [{"id": uuid(44), "name": "lab-pveapi service token", "created_at": NEW}],
        }

    def test_lists_without_deleting_by_default(self):
        self.add(demo_objects())
        self.add(self.foreign_objects())
        out = self.run_cli("sweep")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.methods(), {"GET"})
        lines = [line for line in out.stdout.splitlines() if line.startswith("sweep: would delete")]
        self.assertEqual(len(lines), 9)
        kinds = [re.match(r"sweep: would delete the (.+?) (demo|CNAME)", line).group(1) for line in lines]
        self.assertEqual(kinds, ["Access application"] * 2 + ["Access policy"] * 2 + ["service token"] * 2
                         + ["DNS record"] * 2 + ["tunnel"])
        for name in ("lab-pve", "demo-hand", "show-edge", "example.net", "lab allow", "lab-pveapi"):
            self.assertNotIn(name, out.stdout)

    def test_deletes_the_demo_objects_in_order_and_nothing_else(self):
        self.add(demo_objects())
        foreign = self.foreign_objects()
        self.add(foreign)
        out = self.run_cli("sweep", "--delete")
        self.assertEqual(out.returncode, 0, out.stderr)
        deleted = [path for method, path, _ in self.server.requests if method == "DELETE"]
        self.assertEqual(len(deleted), 10)
        self.assertTrue(all("/access/apps/" in p for p in deleted[:2]))
        self.assertTrue(all("/access/policies/" in p for p in deleted[2:4]))
        self.assertTrue(all("/access/service_tokens/" in p for p in deleted[4:6]))
        self.assertTrue(all("/dns_records/" in p for p in deleted[6:8]))
        self.assertEqual(deleted[8:], [f"/client/v4/accounts/{ACCOUNT}/cfd_tunnel/{uuid(1)}/connections",
                                       f"/client/v4/accounts/{ACCOUNT}/cfd_tunnel/{uuid(1)}"])
        for name, items in foreign.items():
            for item in items:
                self.assertIn(item["id"], [i["id"] for i in self.server.data[name]])
        self.assertEqual(len(self.server.data["records"]), 4 + 2)
        again = self.run_cli("sweep")
        self.assertIn("sweep: no left-over demo object", again.stdout)

    def test_keeps_a_tunnel_with_a_connector(self):
        objects = demo_objects()
        objects["tunnels"][0]["status"] = "healthy"
        self.add(objects)
        out = self.run_cli("sweep", "--delete")
        self.assertEqual(out.returncode, 1)
        self.assertIn("kept the tunnel demo-e2e: it has a connector (healthy)", out.stdout)
        self.assertEqual([t["id"] for t in self.server.data["tunnels"]], [uuid(1)])
        self.assertEqual(self.run_cli("sweep").returncode, 0, "a listing alone does not fail")

    def test_created_after_spares_what_existed_before_the_run(self):
        self.add(demo_objects(created=OLD))
        self.add({"records": [{"id": rid(50), "name": f"demo-new.{ZONE}", "type": "CNAME", "content": "x",
                               "comment": "managed-by-tofu env=demo", "created_on": NEW},
                              {"id": rid(51), "name": f"demo-undated.{ZONE}", "type": "CNAME", "content": "x",
                               "comment": "managed-by-tofu env=demo"}]})
        out = self.run_cli("sweep", "--delete", "--created-after", "2026-10-22T10:00:00Z")
        self.assertEqual(out.returncode, 0, out.stderr)
        deleted = [path for method, path, _ in self.server.requests if method == "DELETE"]
        self.assertEqual(deleted, [f"/client/v4/zones/{ZONE_ID}/dns_records/{rid(50)}"])
        self.assertEqual(self.run_cli("sweep", "--created-after", "not a time").returncode, 2)

    def test_the_task_wrapper_passes_its_arguments(self):
        self.add(demo_objects())
        out = subprocess.run(["bash", str(ROOT / "scripts" / "sweep_demo.sh"), "--delete"], env=self.environ(),
                             capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("sweep: deleted the tunnel demo-e2e", out.stdout)
        bad = subprocess.run(["bash", str(ROOT / "scripts" / "sweep_demo.sh"), "--everything"], env=self.environ(),
                             capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(bad.returncode, 2)


class TunnelStatusTest(ApiTestCase):
    def test_waits_for_a_connection(self):
        self.add({"tunnels": demo_objects()["tunnels"]})
        self.server.healthy_after = 2
        out = self.run_cli("tunnel-status", "--tunnel-id", uuid(1), "--wait", "30")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("healthy, 1 connection(s)", out.stdout)

    def test_gives_up(self):
        self.add({"tunnels": demo_objects()["tunnels"]})
        self.server.healthy_after = 10**6
        out = self.run_cli("tunnel-status", "--tunnel-id", uuid(1), "--wait", "0")
        self.assertEqual(out.returncode, 1)
        self.assertIn("still inactive", out.stderr)
        self.assertEqual(self.run_cli("tunnel-status", "--tunnel-id", "../x").returncode, 2)


class PreflightScriptTest(ApiTestCase):
    def run_script(self, *args: str, **env) -> subprocess.CompletedProcess:
        out = subprocess.run(["bash", str(ROOT / "scripts" / "cf_preflight.sh"), *args], env=self.environ(**env),
                             capture_output=True, text=True, timeout=60, check=False)
        self.assertNotIn(API_TOKEN, out.stdout + out.stderr)
        return out

    def test_prints_the_permissions_then_checks(self):
        out = self.run_script("demo")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertLess(out.stdout.index("Zone · DNS · Edit"), out.stdout.index("preflight of demo: passed"))

    def test_checks_the_saved_plan(self):
        self.add(demo_objects())
        path = self.tmp / "plan.json"
        path.write_text(json.dumps(demo_plan()), encoding="utf-8")
        out = self.run_script("demo", str(path))
        self.assertEqual(out.returncode, 1)
        self.assertIn("preflight of demo: refused", out.stdout)

    def test_rejects_wrong_input(self):
        for args in ((), ("local",), ("prod",), ("demo", str(self.tmp / "missing.json"))):
            with self.subTest(args=args):
                self.assertEqual(self.run_script(*args).returncode, 2)
        self.assertEqual(self.run_script("demo", SECRETS=str(self.tmp / "none.enc.env")).returncode, 2)
        self.assertEqual(self.server.requests, [])


@unittest.skipUnless(shutil.which("age") and shutil.which("age-keygen"), "needs age and age-keygen")
class DnsBackupTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.identity = self.tmp / "keys.txt"
        subprocess.run(["age-keygen", "-o", str(self.identity)], capture_output=True, check=True)
        self.backups = self.tmp / "backups"

    def run_script(self, *args: str, **env) -> subprocess.CompletedProcess:
        defaults = {"DNS_BACKUP_DIR": str(self.backups), "SOPS_AGE_KEY_FILE": str(self.identity)}
        out = subprocess.run(["bash", str(ROOT / "scripts" / "dns_backup.sh"), *args],
                             env=self.environ(**{**defaults, **env}), capture_output=True, text=True, timeout=60,
                             check=False)
        self.assertNotIn(API_TOKEN, out.stdout + out.stderr)
        return out

    def test_writes_an_encrypted_copy_that_the_operator_key_reads(self):
        out = self.run_script("demo")
        self.assertEqual(out.returncode, 0, out.stderr)
        files = sorted(self.backups.iterdir())
        self.assertEqual(len(files), 1, files)
        self.assertRegex(files[0].name, r"^\d{8}T\d{6}Z\.zone\.age$")
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.backups.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(b"SOA", files[0].read_bytes())
        plain = subprocess.run(["age", "--decrypt", "--identity", str(self.identity), str(files[0])],
                               capture_output=True, text=True, check=True).stdout
        self.assertEqual(plain, self.server.export)

    def test_recipients_from_the_environment(self):
        public = subprocess.run(["age-keygen", "-y", str(self.identity)], capture_output=True, text=True,
                                check=True).stdout.strip()
        out = self.run_script("lab", DNS_BACKUP_RECIPIENTS=public, SOPS_AGE_KEY_FILE=str(self.tmp / "none"))
        self.assertEqual(out.returncode, 0, out.stderr)
        bad = self.run_script("lab", DNS_BACKUP_RECIPIENTS="not-a-key")
        self.assertEqual(bad.returncode, 2)

    def test_a_failed_export_leaves_no_file(self):
        self.server.refused = ["/dns_records/export"]
        out = self.run_script("demo")
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(list(self.backups.iterdir()), [])

    def test_refuses_without_a_recipient_or_for_local(self):
        self.assertEqual(self.run_script("demo", SOPS_AGE_KEY_FILE=str(self.tmp / "none")).returncode, 2)
        self.assertEqual(self.run_script("local").returncode, 2)
        self.assertEqual(self.server.requests, [])


if __name__ == "__main__":
    unittest.main()
