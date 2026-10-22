"""scripts/environment.sh (task up, inventory, configure, smoke, destroy and rebuild) and
scripts/e2e_local.sh (task e2e:local).

environment.sh runs on a copy of the repository layout with stand-ins for tofu, sops and
ansible-playbook that record their calls, so the tests see which playbooks run in which order,
from which folder, with which inventory, and whether TUNNEL_TOKEN reached them (never its value).
Nothing here contacts Docker, OpenTofu's registry or the Cloudflare API: the tunnel token script
is replaced in the copy. The real end-to-end run is task e2e:local (CI workflow e2e-local).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOSTS = {
    "edge-01": {"ansible_host": "lab-local-edge-01", "connection": "community.docker.docker",
                "groups": ["edge", "monitoring"], "ip": "192.0.2.2"},
    "fx-01": {"ansible_host": "lab-local-fx-01", "connection": "community.docker.docker",
              "groups": ["fxserver"], "ip": "192.0.2.4"},
}
TUNNEL_ID = "00000000-0000-4000-8000-000000000001"

# tofu: "output <...> -json" prints the hosts output; "-raw tunnel_id" the tunnel ID.
FAKE_TOFU = """#!/bin/sh
{ printf 'tofu'; printf ' [%s]' "$@"; printf '\\n'; } >>"$CALLS"
case "$*" in
  *"output -json"*) cat "$OUTPUTS" ;;
  *"output -raw tunnel_id"*) printf '%s' "$TUNNEL_ID" ;;
esac
"""
# ansible-playbook: records the folder, the arguments and whether TUNNEL_TOKEN is set.
FAKE_PLAYBOOK = """#!/bin/sh
{ printf 'ansible-playbook cwd=%s token=%s' "$(basename "$PWD")" "${TUNNEL_TOKEN:+set}"; printf ' [%s]' "$@";
  printf '\\n'; } >>"$CALLS"
"""
FAKE_SOPS = """#!/bin/sh
printf 'sops [%s] [%s]\\n' "$1" "$2" >>"$CALLS"
CLOUDFLARE_API_TOKEN=from-sops TF_VAR_account_id=0123456789abcdef0123456789abcdef \\
  TF_VAR_state_passphrase=passphrase-from-the-sops-file exec /bin/sh -c "$3"
"""
# Replaces scripts/tunnel_token.py in the copy: prints a token when the API credentials came
# from sops and the tunnel ID from tofu.
FAKE_TUNNEL_TOKEN = """import sys, os
print("tunnel_token.py", " ".join(sys.argv[1:]), "api=" + os.environ.get("CLOUDFLARE_API_TOKEN", ""),
      file=open(os.environ["CALLS"], "a"))
print("synthetic-tunnel-token-for-the-test")
"""


class EnvironmentScriptTest(unittest.TestCase):
    CLEARED = ("TUNNEL_TOKEN", "SECRETS", "AUTO_APPROVE", "ENVIRONMENT_IN_SOPS", "TOFU_ENV_IN_SOPS",
               "AWS_ENDPOINT_URL_S3", "CLOUDFLARE_API_TOKEN", "TF_VAR_account_id")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "scripts").mkdir()
        for name in ("environment.sh", "tofu_env.sh", "render_inventory.py"):
            shutil.copy2(ROOT / "scripts" / name, self.root / "scripts" / name)
        (self.root / "scripts" / "tunnel_token.py").write_text(FAKE_TUNNEL_TOKEN, encoding="utf-8")
        for env in ("local", "lab", "demo", "showcase"):
            (self.root / "tofu" / "envs" / env).mkdir(parents=True)
            (self.root / "ansible" / "inventories" / env).mkdir(parents=True)
        (self.root / "secrets").mkdir()
        (self.root / "bin").mkdir()
        for name, body in (("tofu", FAKE_TOFU), ("ansible-playbook", FAKE_PLAYBOOK), ("sops", FAKE_SOPS)):
            fake = self.root / "bin" / name
            fake.write_text(body, encoding="utf-8")
            fake.chmod(0o755)
        self.calls_file = self.root / "calls.log"
        self.outputs = self.root / "outputs.json"
        self.outputs.write_text(json.dumps({"hosts": {"sensitive": False, "value": HOSTS}}), encoding="utf-8")

    def run_script(self, *args: str, **env: str | None) -> subprocess.CompletedProcess:
        environ = {k: v for k, v in os.environ.items() if k not in self.CLEARED}
        environ.update(PATH=f"{self.root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
                       CALLS=str(self.calls_file), OUTPUTS=str(self.outputs), TUNNEL_ID=TUNNEL_ID,
                       TF_VAR_state_passphrase="passphrase-of-the-test-run")
        for key, value in env.items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        return subprocess.run(["bash", str(self.root / "scripts" / "environment.sh"), *args], env=environ,
                              capture_output=True, text=True, timeout=60, check=False)

    def calls(self) -> list[str]:
        return self.calls_file.read_text(encoding="utf-8").splitlines() if self.calls_file.exists() else []

    def hosts_file(self, env: str) -> Path:
        return self.root / "ansible" / "inventories" / env / "hosts.yml"

    def test_inventory_from_the_outputs(self):
        out = self.run_script("inventory", "local")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), ["tofu [-chdir=tofu/envs/local] [output] [-json]"])
        text = self.hosts_file("local").read_text(encoding="utf-8")
        self.assertIn('ansible_host: "lab-local-fx-01"', text)
        self.assertIn("host_ip: \"192.0.2.4\"", text)

    def test_inventory_keeps_the_old_file_when_the_outputs_are_invalid(self):
        self.hosts_file("local").write_text("# last good inventory\n", encoding="utf-8")
        self.outputs.write_text(json.dumps({"hosts": {"value": {"edge-01": {**HOSTS["edge-01"], "groups": []}}}}),
                                encoding="utf-8")
        out = self.run_script("inventory", "local")
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(self.hosts_file("local").read_text(encoding="utf-8"), "# last good inventory\n")

    def test_configure_local_prepares_first_and_never_passes_a_tunnel_token(self):
        self.hosts_file("local").write_text("all: {}\n", encoding="utf-8")
        out = self.run_script("configure", "local", "--diff", TUNNEL_TOKEN="a-token-from-the-shell")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), [
            "ansible-playbook cwd=ansible token= [-i] [inventories/local] [playbooks/local_prepare.yml]",
            "ansible-playbook cwd=ansible token= [-i] [inventories/local] [playbooks/site.yml] [--diff]",
        ])

    def test_configure_needs_the_inventory(self):
        out = self.run_script("configure", "local")
        self.assertEqual(out.returncode, 2)
        self.assertIn("task inventory ENV=local", out.stderr)
        self.assertEqual(self.calls(), [])

    def test_configure_with_a_tunnel_fetches_the_token_inside_sops(self):
        self.hosts_file("lab").write_text("all: {}\n", encoding="utf-8")
        (self.root / "secrets" / "lab.enc.env").write_text("read by the fake sops only\n", encoding="utf-8")
        (self.root / "tofu" / "envs" / "lab" / "backend_override.tf").write_text("# local state\n",
                                                                                   encoding="utf-8")
        out = self.run_script("configure", "lab")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), [
            "sops [exec-env] [secrets/lab.enc.env]",
            "tofu [-chdir=tofu/envs/lab] [output] [-raw] [tunnel_id]",
            f"tunnel_token.py --tunnel-id {TUNNEL_ID} api=from-sops",
            "ansible-playbook cwd=ansible token=set [-i] [inventories/lab] [playbooks/site.yml]",
        ])
        self.assertNotIn("synthetic-tunnel-token", out.stdout + out.stderr)

    def test_configure_uses_a_token_that_is_already_set(self):
        self.hosts_file("demo").write_text("all: {}\n", encoding="utf-8")
        out = self.run_script("configure", "demo", TUNNEL_TOKEN="a-token-from-the-operator")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(),
                         ["ansible-playbook cwd=ansible token=set [-i] [inventories/demo] [playbooks/site.yml]"])

    def test_restore_test(self):
        self.hosts_file("local").write_text("all: {}\n", encoding="utf-8")
        out = self.run_script("restore-test", "local", "-e", "restore_test_backup_now=true")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), ["ansible-playbook cwd=ansible token= [-i] [inventories/local] "
                                        "[playbooks/restore_test.yml] [-e] [restore_test_backup_now=true]"])

    def test_smoke(self):
        self.hosts_file("local").write_text("all: {}\n", encoding="utf-8")
        out = self.run_script("smoke", "local")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(),
                         ["ansible-playbook cwd=ansible token= [-i] [inventories/local] [playbooks/smoke.yml]"])

    def test_up_runs_every_step_in_order(self):
        out = self.run_script("up", "local")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), [
            "tofu [-chdir=tofu/envs/local] [init] [-input=false] [-reconfigure]",
            "tofu [-chdir=tofu/envs/local] [apply] [-auto-approve]",
            "tofu [-chdir=tofu/envs/local] [output] [-json]",
            "ansible-playbook cwd=ansible token= [-i] [inventories/local] [playbooks/local_prepare.yml]",
            "ansible-playbook cwd=ansible token= [-i] [inventories/local] [playbooks/site.yml]",
            "ansible-playbook cwd=ansible token= [-i] [inventories/local] [playbooks/smoke.yml]",
        ])

    def test_apply_of_other_environments_asks_unless_auto_approve(self):
        override = self.root / "tofu" / "envs" / "demo" / "backend_override.tf"
        for env, expected in (({}, "[apply]"), ({"AUTO_APPROVE": "1"}, "[apply] [-auto-approve]")):
            with self.subTest(env=env):
                self.calls_file.unlink(missing_ok=True)
                self.run_script("up", "demo", BACKEND="local", TUNNEL_TOKEN="operator-token", **env)
                self.assertTrue(override.exists())
                self.assertIn(f"tofu [-chdir=tofu/envs/demo] {expected}", self.calls())

    def test_destroy_local_removes_the_generated_files(self):
        self.hosts_file("local").write_text("all: {}\n", encoding="utf-8")
        generated = self.root / "ansible" / "inventories" / "local" / ".generated"
        generated.mkdir()
        (generated / "perf_password").write_text("x\n", encoding="utf-8")
        (self.root / "tofu" / "envs" / "local" / "terraform.tfstate").write_text("{}\n", encoding="utf-8")
        out = self.run_script("destroy", "local")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), ["tofu [-chdir=tofu/envs/local] [destroy] [-auto-approve]"])
        self.assertFalse(self.hosts_file("local").exists())
        self.assertFalse(generated.exists())
        self.assertFalse((self.root / "tofu" / "envs" / "local" / "terraform.tfstate").exists())

    def test_destroy_of_local_without_a_state_runs_no_tofu(self):
        out = self.run_script("destroy", "local")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("nothing to destroy", out.stdout)
        self.assertEqual(self.calls(), [])

    def test_rebuild_destroys_then_builds_and_times_it(self):
        (self.root / "tofu" / "envs" / "local" / "terraform.tfstate").write_text("{}\n", encoding="utf-8")
        out = self.run_script("rebuild", "local")
        self.assertEqual(out.returncode, 0, out.stderr)
        calls = self.calls()
        self.assertEqual(calls[0], "tofu [-chdir=tofu/envs/local] [destroy] [-auto-approve]")
        self.assertEqual(calls[1], "tofu [-chdir=tofu/envs/local] [init] [-input=false] [-reconfigure]")
        self.assertEqual(calls[-1], "ansible-playbook cwd=ansible token= [-i] [inventories/local] [playbooks/smoke.yml]")
        self.assertRegex(out.stdout, r"rebuild of local took \d+ s")

    def test_showcase_is_never_destroyed_or_rebuilt(self):
        for action in ("destroy", "rebuild"):
            with self.subTest(action=action):
                out = self.run_script(action, "showcase", AUTO_APPROVE="1")
                self.assertEqual(out.returncode, 2)
                self.assertIn(f"refusing to {action} showcase", out.stderr)
        self.assertEqual(self.calls(), [])

    def test_rejects_unknown_input(self):
        for args in (("deploy", "local"), ("up", "prod"), ("up",)):
            with self.subTest(args=args):
                self.assertEqual(self.run_script(*args).returncode, 2)
        self.assertEqual(self.calls(), [])


class EndToEndScriptTest(unittest.TestCase):
    """What scripts/e2e_local.sh promises; the run itself is task e2e:local."""

    @classmethod
    def setUpClass(cls):
        cls.script = (ROOT / "scripts" / "e2e_local.sh").read_text(encoding="utf-8")

    def test_steps_in_order(self):
        steps = re.findall(r'(?m)^step "([^"]+)"', self.script)
        self.assertEqual(steps, ["tofu init", "tofu apply", "inventory", "collections", "configure (first run)",
                                 "configure (second run: changed=0)", "tofu plan (no changes)", "smoke",
                                 "restore test"])
        self.assertIn("restore-test local -e restore_test_backup_now=true", self.script)

    def test_destroy_always_runs(self):
        self.assertIn("trap finish EXIT", self.script)
        self.assertRegex(self.script, r'(?s)finish\(\) \{.*step "destroy" destroy')

    def test_second_run_and_plan_are_checked(self):
        self.assertIn("check_no_changes", self.script)
        self.assertIn("plan local -detailed-exitcode", self.script)

    def test_never_a_tunnel_and_a_random_passphrase(self):
        self.assertIn("unset TUNNEL_TOKEN", self.script)
        self.assertIn("secrets.token_urlsafe(32)", self.script)

    def test_never_starts_over_the_state_of_an_earlier_run(self):
        guard = self.script.index("is left from an earlier run")
        self.assertLess(guard, self.script.index("trap finish EXIT"))
        self.assertLess(guard, self.script.index('step "tofu init"'))

    @unittest.skipUnless(shutil.which("bash"), "needs bash")
    def test_recap_check(self):
        """The changed=0 check, run on recap lines as ansible-playbook prints them."""
        function = re.search(r"(?s)\ncheck_no_changes\(\) \{.*?\n\}\n", self.script).group(0)
        good = ("db-01                      : ok=136  changed=0    unreachable=0    failed=0    "
                "skipped=35   rescued=0    ignored=0   \n")
        bad = good.replace("changed=0 ", "changed=1 ")
        with tempfile.TemporaryDirectory() as tmp:
            for text, expected in ((good * 2, 0), (good + bad, 1), ("no recap\n", 1)):
                log = Path(tmp) / "site.log"
                log.write_text(text, encoding="utf-8")
                result = subprocess.run(["bash", "-c", f'{function}\ncheck_no_changes "$1"', "_", str(log)],
                                        capture_output=True, text=True, timeout=30, check=False)
                with self.subTest(text=text[:40], expected=expected):
                    self.assertEqual(result.returncode, expected, result.stderr)


if __name__ == "__main__":
    unittest.main()
