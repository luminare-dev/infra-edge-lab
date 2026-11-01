"""The gated cloud workflows (plan, apply, drift, e2e-tunnel), their helper scripts and the plan
summary.

The workflows cannot run here (they need real cloud accounts), so these tests pin the promises
they make: every job is off until the repository variable CLOUD_ENVS_ENABLED is "true", nothing
runs for a fork, each job's GitHub environment and permissions, the shared concurrency group of
the jobs that write demo-* names, no plan file leaving the runner, the cleanup that
runs whatever happened, and pins equal to docs/toolchain.md. scripts/cloud_ci.sh and
scripts/e2e_tunnel.sh are run with stand-ins where that is possible without an account, and
read where it is not. The YAML checks need PyYAML (requirements-test.txt); without it they are
skipped.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - only without the test requirements
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import plan_summary  # noqa: E402  (the module under test)

CLOUD_WORKFLOWS = ("plan", "apply", "drift", "e2e-tunnel")
GATE = "vars.CLOUD_ENVS_ENABLED == 'true'"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def toolchain_pin(tool: str) -> tuple[str, str, str]:
    """(version, file, sha256) of a row of the binary table in docs/toolchain.md."""
    for line in read("docs/toolchain.md").splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) > 4 and cells[0].lower() == tool:
            return cells[1], cells[3], cells[4]
    raise AssertionError(f"{tool} is not in docs/toolchain.md")


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class CloudWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = {name: read(f".github/workflows/{name}.yml") for name in CLOUD_WORKFLOWS}
        cls.flows = {name: yaml.safe_load(text) for name, text in cls.text.items()}

    def triggers(self, name: str) -> dict:
        flow = self.flows[name]
        return flow.get("on", flow.get(True))  # PyYAML reads the key "on" as True

    def test_every_job_is_off_until_the_variable_is_true(self):
        for name, flow in self.flows.items():
            for job_name, job in flow["jobs"].items():
                with self.subTest(workflow=name, job=job_name):
                    self.assertTrue(job["if"].startswith(GATE), job["if"])

    def test_never_for_a_fork_or_with_a_dangerous_trigger(self):
        for name in CLOUD_WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertNotIn("pull_request_target", self.text[name])
                self.assertNotIn("workflow_run", self.text[name])
        self.assertEqual(sorted(self.triggers("plan")), ["pull_request", "workflow_dispatch"])
        condition = self.flows["plan"]["jobs"]["plan"]["if"]
        self.assertIn("github.event.pull_request.head.repo.full_name == github.repository", condition)
        self.assertIn("github.event.pull_request.user.login != 'dependabot[bot]'", condition)
        self.assertEqual(sorted(self.triggers("apply")), ["workflow_dispatch"])
        self.assertEqual(sorted(self.triggers("drift")), ["schedule", "workflow_dispatch"])
        self.assertEqual(sorted(self.triggers("e2e-tunnel")), ["push", "schedule", "workflow_dispatch"])
        self.assertEqual(self.triggers("e2e-tunnel")["push"], {"branches": ["main"]})

    def test_environments_and_permissions(self):
        expected = {
            ("plan", "plan"): ("lab-plan", {"contents": "read"}),
            ("apply", "plan"): ("lab-plan", {"contents": "read"}),
            ("apply", "apply"): ("${{ inputs.env }}", {"contents": "read"}),
            ("drift", "drift"): ("lab-plan", {"contents": "read"}),
            ("drift", "issue"): (None, {"issues": "write"}),
            ("e2e-tunnel", "e2e-tunnel"): ("demo-e2e", {"contents": "read"}),
        }
        found = {(n, j): (job.get("environment"), job["permissions"])
                 for n, flow in self.flows.items() for j, job in flow["jobs"].items()}
        self.assertEqual(found, expected)
        for name, flow in self.flows.items():
            self.assertEqual(flow["permissions"], {}, name)
        self.assertEqual(self.triggers("apply")["workflow_dispatch"]["inputs"]["env"]["options"], ["demo", "showcase"])
        self.assertEqual(self.flows["apply"]["jobs"]["apply"]["needs"], "plan")

    def test_jobs_that_write_demo_names_share_one_group_and_are_never_cancelled(self):
        apply, e2e = self.flows["apply"]["concurrency"], self.flows["e2e-tunnel"]["concurrency"]
        self.assertEqual(apply, {"group": "cloud-${{ inputs.env }}", "cancel-in-progress": False})
        self.assertEqual(e2e, {"group": "cloud-demo", "cancel-in-progress": False})
        self.assertEqual(self.flows["drift"]["concurrency"]["cancel-in-progress"], False)

    def test_secrets_reach_their_step_only_and_no_plan_leaves_the_runner(self):
        """The one artifact is drift's anonymised report for the issue job, kept for one day."""
        for name, text in self.text.items():
            with self.subTest(workflow=name):
                self.assertEqual(set(re.findall(r"secrets\.(\w+)", text)), {"SOPS_AGE_KEY"})
                self.assertEqual(text.count("upload-artifact"), 1 if name == "drift" else 0)
                self.assertNotIn("secrets: inherit", text)
                for job in self.flows[name]["jobs"].values():
                    for step in job["steps"]:
                        self.assertNotIn("${{", step.get("run", ""), step.get("name"))
                        if "SOPS_AGE_KEY" in json.dumps(step.get("env", {})):
                            self.assertTrue(step["run"].strip().startswith(("bash scripts/", "task ")))

    def test_each_job_runs_its_helper(self):
        runs = {(n, j): [s.get("run", "").strip() for s in job["steps"]]
                for n, flow in self.flows.items() for j, job in flow["jobs"].items()}
        self.assertIn('bash scripts/cloud_ci.sh plan "$ENV"', runs[("plan", "plan")])
        self.assertIn('bash scripts/cloud_ci.sh plan "$ENV"', runs[("apply", "plan")])
        self.assertIn('bash scripts/cloud_ci.sh apply "$ENV"', runs[("apply", "apply")])
        self.assertIn('bash scripts/cloud_ci.sh drift "$ENV"', runs[("drift", "drift")])
        self.assertEqual(runs[("e2e-tunnel", "e2e-tunnel")][-2:], ["task e2e:tunnel", "bash scripts/e2e_tunnel.sh cleanup"])

    def test_the_cleanup_runs_whatever_happened(self):
        steps = self.flows["e2e-tunnel"]["jobs"]["e2e-tunnel"]["steps"]
        run, cleanup = steps[-2], steps[-1]
        self.assertEqual(cleanup["if"], "always()")
        job_timeout = self.flows["e2e-tunnel"]["jobs"]["e2e-tunnel"]["timeout-minutes"]
        self.assertLess(run["timeout-minutes"] + cleanup["timeout-minutes"], job_timeout)

    def test_drift_issue_only_on_a_finding(self):
        steps = self.flows["drift"]["jobs"]["drift"]["steps"]
        self.assertEqual(steps[-1]["if"], "steps.check.outputs.drift == 'true'")
        self.assertEqual(steps[-2]["id"], "check")
        self.assertEqual(steps[-1]["with"], {
            "name": "drift-${{ matrix.env }}", "path": "${{ runner.temp }}/drift-${{ matrix.env }}.md",
            "if-no-files-found": "error", "retention-days": 1})
        self.assertTrue(steps[-1]["uses"].startswith("actions/upload-artifact@"))
        issue = self.flows["drift"]["jobs"]["issue"]
        self.assertEqual(issue["needs"], "drift")
        self.assertIn("!cancelled()", issue["if"])
        self.assertTrue(issue["steps"][0]["uses"].startswith("actions/download-artifact@"))
        self.assertEqual(issue["steps"][0]["with"]["pattern"], "drift-*")
        self.assertIn('--body-file "$report"', issue["steps"][-1]["run"])

    def test_the_job_with_the_credentials_cannot_write_issues(self):
        """A compromised tool in the drift job gets a read-only token; the issue job gets no secret."""
        drift, issue = self.flows["drift"]["jobs"]["drift"], self.flows["drift"]["jobs"]["issue"]
        self.assertEqual(drift["permissions"], {"contents": "read"})
        self.assertNotIn("environment", issue)
        self.assertNotIn("secrets.", json.dumps(issue))
        self.assertFalse(any("actions/checkout@" in step.get("uses", "") for step in issue["steps"]))

    def test_downloads_match_the_toolchain(self):
        sops_version, sops_file, sops_sha = toolchain_pin("sops")
        task_version, _, task_sha = toolchain_pin("go-task")
        self.assertEqual(sops_file, f"sops-v{sops_version}.linux.amd64")
        for name, text in self.text.items():
            with self.subTest(workflow=name):
                self.assertIn(f"SOPS_VERSION: {sops_version}\n", text)
                self.assertIn(f"SOPS_SHA256: {sops_sha}\n", text)
                self.assertIn("sops-v${SOPS_VERSION}.linux.amd64", text)
                self.assertIn("scripts/install_tofu_tools.sh", text)
                self.assertGreaterEqual(text.count("sha256sum -c -"), 1)
        self.assertIn(f"TASK_VERSION: {task_version}\n", self.text["e2e-tunnel"])
        self.assertIn(f"TASK_SHA256: {task_sha}\n", self.text["e2e-tunnel"])

    def test_apply_installs_the_pinned_cloudflared_for_ssh_through_the_tunnel(self):
        version, file, sha256 = toolchain_pin("cloudflared")
        env = self.flows["apply"]["jobs"]["apply"]["env"]
        self.assertEqual((str(env["CLOUDFLARED_VERSION"]), env["CLOUDFLARED_SHA256"]), (version, sha256))
        self.assertIn(f"/releases/download/${{CLOUDFLARED_VERSION}}/{file}", self.text["apply"])
        self.assertIn('echo "${CLOUDFLARED_SHA256}  $RUNNER_TEMP/tools/cloudflared" | sha256sum -c -',
                      self.text["apply"])

    def test_checkout_without_credentials(self):
        for name, flow in self.flows.items():
            for job_name, job in flow["jobs"].items():
                if (name, job_name) == ("drift", "issue"):
                    continue  # reads its artifacts only, no checkout
                checkout = job["steps"][0]
                with self.subTest(workflow=name):
                    self.assertTrue(checkout["uses"].startswith("actions/checkout@"))
                    self.assertIs(checkout["with"]["persist-credentials"], False)


class PlanSummaryTest(unittest.TestCase):
    PLAN = {
        "format_version": "1.2",
        "resource_changes": [
            {"address": 'module.tunnel.cloudflare_dns_record.tunnel["demo-web"]', "type": "cloudflare_dns_record",
             "change": {"actions": ["create"], "after": {"name": "demo-web.example.com", "content": "secret-ish"}}},
            {"address": "module.server.hcloud_server.this", "change": {"actions": ["update"],
                                                                       "after": {"user_data": "token-value"}}},
            {"address": "module.server.hcloud_firewall.this", "change": {"actions": ["delete", "create"]}},
            {"address": "module.old.hcloud_ssh_key.this", "change": {"actions": ["delete"]}},
            {"address": "module.gone.random_id.this", "change": {"actions": ["forget"]}},
            {"address": "data.cloudflare_zone.this", "change": {"actions": ["read"]}},
            {"address": "module.tunnel.cloudflare_zero_trust_tunnel_cloudflared.this",
             "change": {"actions": ["no-op"]}},
        ],
        "resource_drift": [{"address": "module.server.hcloud_firewall.this", "change": {"actions": ["update"]}}],
    }

    def test_counts_and_actions_without_values(self):
        text, counts = plan_summary.summarise(self.PLAN, "Plan of demo")
        self.assertEqual(counts, {"add": 2, "change": 1, "destroy": 2, "forget": 1})
        self.assertIn("Plan: 2 to add, 1 to change, 2 to destroy, 1 to forget.", text)
        self.assertIn('| create | `module.tunnel.cloudflare_dns_record.tunnel["demo-web"]` |', text)
        self.assertIn("| replace | `module.server.hcloud_firewall.this` |", text)
        self.assertIn("Changed outside OpenTofu", text)
        for hidden in ("example.com", "secret-ish", "token-value", "data.cloudflare_zone", "tunnel_cloudflared"):
            self.assertNotIn(hidden, text)

    def test_no_changes(self):
        text, counts = plan_summary.summarise({"format_version": "1.2", "resource_changes": []}, "Plan")
        self.assertIn("No changes.", text)
        self.assertEqual(sum(counts.values()), 0)

    def test_command_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            path.write_text(json.dumps(self.PLAN), encoding="utf-8")
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "plan_summary.py"), "--env", "demo",
                                  str(path)], capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertTrue(out.stdout.startswith("### Plan of demo\n"))
            path.write_text('{"values": {}}', encoding="utf-8")
            bad = subprocess.run([sys.executable, str(ROOT / "scripts" / "plan_summary.py"), str(path)],
                                 capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(bad.returncode, 1)


# Stand-in for sops: records the call and runs the command as sops exec-env does, with values
# "from the file".
FAKE_SOPS = """#!/bin/sh
printf 'sops [%s] [%s]\\n' "$1" "$2" >>"$CALLS"
CLOUDFLARE_API_TOKEN=token-from-the-file TF_VAR_zone=example.com TF_VAR_account_id=0123456789abcdef0123456789abcdef \\
  exec /bin/sh -c "$3"
"""


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class CloudCiScriptTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts" / "cloud_ci.sh", self.root / "scripts" / "cloud_ci.sh")
        (self.root / "secrets").mkdir()
        shutil.copy2(ROOT / "secrets" / "env.example", self.root / "secrets" / "env.example")
        (self.root / "bin").mkdir()
        fake = self.root / "bin" / "sops"
        fake.write_text(FAKE_SOPS, encoding="utf-8")
        fake.chmod(0o755)
        self.calls = self.root / "calls.log"
        self.output = self.root / "github_output"
        self.summary = self.root / "summary.md"

    def run_script(self, *args: str, **env: str | None) -> subprocess.CompletedProcess:
        environ = {k: v for k, v in os.environ.items()
                   if not k.startswith(("TF_VAR_", "CLOUDFLARE_", "SECRETS", "SOPS_", "GITHUB_"))}
        environ.update(PATH=f"{self.root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}", CALLS=str(self.calls),
                       GITHUB_OUTPUT=str(self.output), GITHUB_STEP_SUMMARY=str(self.summary),
                       RUNNER_TEMP=str(self.root))
        for key, value in env.items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        return subprocess.run(["bash", str(self.root / "scripts" / "cloud_ci.sh"), *args], env=environ,
                              capture_output=True, text=True, timeout=60, check=False)

    def test_an_environment_without_read_only_credentials_is_skipped(self):
        for action in ("plan", "drift"):
            with self.subTest(action=action):
                out = self.run_script(action, "showcase")
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertIn("::notice::showcase: no read-only credentials (secrets/showcase-ci.enc.env)", out.stdout)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "drift=false\n")
        self.assertFalse(self.calls.exists())

    def test_apply_needs_the_write_file_and_never_applies_lab(self):
        self.assertEqual(self.run_script("apply", "demo").returncode, 2)
        out = self.run_script("apply", "lab")
        self.assertEqual(out.returncode, 2)
        self.assertIn("lab is applied from the operator's workstation only", out.stderr)

    def test_the_age_key_must_be_there(self):
        (self.root / "secrets" / "demo-ci.enc.env").write_text("sops_mac=ENC[x]\n", encoding="utf-8")
        out = self.run_script("plan", "demo", SOPS_AGE_KEY=None)
        self.assertEqual(out.returncode, 2)
        self.assertIn("SOPS_AGE_KEY is empty", out.stderr)
        self.assertFalse(self.calls.exists())

    def test_reads_the_read_only_file_and_masks_every_value(self):
        (self.root / "secrets" / "lab-ci.enc.env").write_text("sops_mac=ENC[x]\n", encoding="utf-8")
        # Without PROXMOX_VE_ENDPOINT the lab check stops the run after the masks.
        out = self.run_script("plan", "lab", SOPS_AGE_KEY="AGE-SECRET-KEY-1TEST", GITHUB_ACTIONS="true")
        self.assertEqual(self.calls.read_text(encoding="utf-8"), "sops [exec-env] [secrets/lab-ci.enc.env]\n")
        for value in ("token-from-the-file", "example.com", "0123456789abcdef0123456789abcdef"):
            self.assertIn(f"::add-mask::{value}\n", out.stdout)
        self.assertIn("PROXMOX_VE_ENDPOINT is not set", out.stderr)

    def test_rejects_wrong_input(self):
        for args in ((), ("plan",), ("deploy", "demo"), ("plan", "local"), ("plan", "prod")):
            with self.subTest(args=args):
                self.assertEqual(self.run_script(*args).returncode, 2)

    def test_reports_leave_out_the_zone_and_the_ids(self):
        script = read("scripts/cloud_ci.sh")
        function = re.search(r"(?s)\nanonymise\(\) \{.*?\n\}\n", script).group(0)
        env = {**os.environ, "TF_VAR_zone": "example.com", "TF_VAR_account_id": "a" * 32, "TF_VAR_zone_id": "b" * 32}
        text = f"- DNS record CNAME demo-web.example.com in {'b' * 32} of {'a' * 32}\n"
        out = subprocess.run(["bash", "-c", f"{function}\nanonymise"], input=text, env=env, capture_output=True,
                             text=True, timeout=30, check=True)
        self.assertEqual(out.stdout, "- DNS record CNAME demo-web.<zone> in <zone_id> of <account_id>\n")

    def test_plans_never_reach_the_log(self):
        """Every plan and apply writes into a log file (quiet); the log shows the summary only."""
        logical = re.sub(r"\\\n\s*", " ", read("scripts/cloud_ci.sh")).splitlines()
        runs = [line.strip() for line in logical
                if re.search(r"(tofu_env\.sh (plan|apply)|tofu -chdir=\"\$dir\" (plan|apply))\b", line)]
        self.assertEqual(len(runs), 4, runs)
        for line in runs:
            with self.subTest(line=line):
                self.assertTrue(line.startswith("quiet \""), line)
        self.assertIn("-lock=false", read("scripts/cloud_ci.sh"))
        self.assertIn("plan_summary.py", read("scripts/cloud_ci.sh"))


class EndToEndTunnelScriptTest(unittest.TestCase):
    """What scripts/e2e_tunnel.sh promises; the run itself needs a Cloudflare account."""

    @classmethod
    def setUpClass(cls):
        cls.script = read("scripts/e2e_tunnel.sh")

    def test_steps_in_order(self):
        steps = re.findall(r'(?m)^step "([^"]+)"', self.script)
        self.assertEqual(steps, ["preflight", "zone snapshot", "tofu init", "tofu plan", "preflight of the plan",
                                 "tofu apply", "inventory", "collections", "prepare (test page)",
                                 "configure (site.yml with the tunnel token)", "smoke (on the host)",
                                 "tunnel connected", "demo-web through Access", "SSH through demo-ssh"])

    def test_destroy_sweep_and_zone_check_always_run(self):
        finish = re.search(r"(?s)\nfinish\(\) \{.*?\n\}\n", self.script).group(0)
        self.assertLess(finish.index('step "destroy" destroy'), finish.index('step "sweep" sweep'))
        self.assertLess(finish.index('step "sweep" sweep'), finish.index("zone_unchanged"))
        self.assertLess(self.script.index("trap finish EXIT"), self.script.index('step "preflight"'))
        self.assertLess(self.script.index("trap finish EXIT"), self.script.index('>"$work/started-at"'))

    def test_applies_exactly_the_checked_plan(self):
        self.assertIn('tofu_demo plan -input=false -no-color -out="$work/tfplan"', self.script)
        self.assertIn('tofu_demo apply -input=false -no-color "$work/tfplan"', self.script)
        self.assertIn('bash scripts/cf_preflight.sh demo "$work/plan.json"', self.script)

    def test_sweeps_only_what_the_run_created(self):
        self.assertIn('sweep --delete --created-after "$since"', self.script)
        self.assertRegex(self.script, r"(?m)^SWEEP_MARGIN_MINUTES=\d+$")

    def test_names_of_the_test(self):
        self.assertIn("TUNNEL_NAME=demo-e2e\n", self.script)
        self.assertIn("NAME_PREFIX=lab-e2e-\n", self.script)
        self.assertIn("TF_VAR_substrate=docker", self.script)
        self.assertIn("TF_VAR_fetch_tunnel_token=false", self.script)

    def test_cloudflared_pin_matches_the_toolchain(self):
        version, file, sha256 = toolchain_pin("cloudflared")
        self.assertEqual(file, "cloudflared-linux-amd64")
        self.assertIn(f"CLOUDFLARED_VERSION={version}\n", self.script)
        self.assertIn(f"CLOUDFLARED_SHA256={sha256}\n", self.script)
        role = "luminare.infra_edge.cloudflared"
        self.assertIn(role, read("docs/toolchain.md"))

    @unittest.skipUnless(shutil.which("bash"), "needs bash")
    def test_quiet_shows_results_without_the_ids_of_the_objects(self):
        """The apply log names each object with its ID; quiet() shows the results without them."""
        function = re.search(r"(?s)\nquiet\(\) \{.*?\n\}\n", self.script).group(0)
        tunnel_id = "0b6c4f5e-1c2d-4e5f-8a9b-0c1d2e3f4a5b"
        log = (
            f"module.tunnel.cloudflare_zero_trust_tunnel_cloudflared.this: Creation complete after 1s [id={tunnel_id}]\n"
            "module.tunnel.cloudflare_dns_record.this[\"demo-web\"]: Creation complete after 0s "
            "[id=0123456789abcdef0123456789abcdef]\n"
            "module.access.cloudflare_zero_trust_access_service_token.this[\"demo-ssh\"]: Destruction complete "
            f"after 1s [id={tunnel_id}]\n"
            "Apply complete! Resources: 13 added, 0 changed, 0 destroyed.\n"
            "Error: deleting the tunnel [id=" + tunnel_id + "] failed\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "sample.log"
            sample.write_text(log, encoding="utf-8")
            for command, status in (("cat", 0), ("false_after_cat", 1)):
                with self.subTest(command=command):
                    out = subprocess.run(
                        ["bash", "-c", f'{function}\nfalse_after_cat() {{ cat "$1"; return 1; }}\n'
                                       f'quiet "$1/apply.log" {command} "$2"', "_", tmp, str(sample)],
                        capture_output=True, text=True, timeout=30, check=False)
                    self.assertEqual(out.returncode, status, out.stderr)
                    self.assertNotIn("[id=", out.stdout + out.stderr)
                    self.assertNotIn(tunnel_id, out.stdout + out.stderr)
                    self.assertIn("this: Creation complete after 1s\n", out.stdout)
                    self.assertIn("Apply complete! Resources: 13 added, 0 changed, 0 destroyed.", out.stdout)
                    if status:
                        self.assertIn("Error: deleting the tunnel failed", out.stderr)
                    # The log file itself keeps everything, in the private work folder.
                    self.assertIn(tunnel_id, (Path(tmp) / "apply.log").read_text(encoding="utf-8"))

    def test_secrets_never_reach_a_command_line(self):
        self.assertIn('-H "@$work/web-headers"', self.script)
        self.assertIn("TUNNEL_SERVICE_TOKEN_ID=$ssh_id TUNNEL_SERVICE_TOKEN_SECRET=$ssh_secret", self.script)
        self.assertIn("TUNNEL_TOKEN=$token playbook", self.script)
        self.assertNotIn("--service-token-secret", self.script)
        for value in ("$tunnel_id", "$token", "$value", "$zone"):
            self.assertIn(f'mask "{value}"', self.script)

    def test_nested_scripts_use_the_credentials_of_the_run(self):
        self.assertIn("export SECRETS_LOADED=1 TOFU_ENV_IN_SOPS=1 ENVIRONMENT_IN_SOPS=1", self.script)
        for rel in ("scripts/cf_preflight.sh", "scripts/dns_backup.sh", "scripts/sweep_demo.sh"):
            self.assertIn('[ "${SECRETS_LOADED:-}" != 1 ]', read(rel), rel)


# Stand-in for docker: lists one container of the test while it "exists", records removals.
FAKE_DOCKER = """#!/bin/sh
printf 'docker' >>"$CALLS"; printf ' [%s]' "$@" >>"$CALLS"; printf '\\n' >>"$CALLS"
case "$1 $2" in
  "ps -aq") [ -f "$STATE/container" ] && echo 0123456789ab ;;
  "rm -f") rm -f "$STATE/container" ;;
  "network inspect") exit 1 ;;
esac
exit 0
"""
FAKE_PYTHON_SWEEP = """import os, sys
with open(os.environ["CALLS"], "a") as calls:
    print("cloudflare_api.py", " ".join(sys.argv[1:]), file=calls)
print("sweep: no left-over demo object")
"""


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class EndToEndTunnelCleanupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts" / "e2e_tunnel.sh", self.root / "scripts" / "e2e_tunnel.sh")
        (self.root / "scripts" / "cloudflare_api.py").write_text(FAKE_PYTHON_SWEEP, encoding="utf-8")
        (self.root / "bin").mkdir()
        fake = self.root / "bin" / "docker"
        fake.write_text(FAKE_DOCKER, encoding="utf-8")
        fake.chmod(0o755)
        self.state = self.root / "state"
        self.state.mkdir()
        self.work = self.root / "work"
        self.calls = self.root / "calls.log"

    def run_script(self, *args: str, **env: str | None) -> subprocess.CompletedProcess:
        environ = {k: v for k, v in os.environ.items()
                   if not k.startswith(("TF_VAR_", "CLOUDFLARE_", "SECRETS", "SOPS_", "GITHUB_"))}
        environ.update(PATH=f"{self.root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}", CALLS=str(self.calls),
                       STATE=str(self.state), E2E_TUNNEL_DIR=str(self.work), CLOUDFLARE_API_TOKEN="t",
                       TF_VAR_account_id="a" * 32, TF_VAR_zone_id="b" * 32, TF_VAR_zone="example.com",
                       TF_VAR_access_team_name="team")
        for key, value in env.items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        return subprocess.run(["bash", str(self.root / "scripts" / "e2e_tunnel.sh"), *args], env=environ,
                              capture_output=True, text=True, timeout=60, check=False)

    def calls_list(self) -> list[str]:
        return self.calls.read_text(encoding="utf-8").splitlines() if self.calls.exists() else []

    def test_cleanup_removes_the_containers_and_sweeps_from_the_start_of_the_run(self):
        self.work.mkdir()
        (self.work / "started-at").write_text("2026-10-22T10:00:00Z\n", encoding="utf-8")
        (self.state / "container").write_text("", encoding="utf-8")
        out = self.run_script("cleanup")
        self.assertEqual(out.returncode, 0, out.stderr)
        calls = self.calls_list()
        self.assertIn("docker [rm] [-f] [0123456789ab]", calls)
        self.assertIn("cloudflare_api.py sweep --delete --created-after 2026-10-22T10:00:00Z", calls)
        self.assertFalse(self.work.exists())
        ps = next(c for c in calls if c.startswith("docker [ps]"))
        for needle in ("[label=managed-by=tofu]", "[label=env=demo]", "[name=lab-e2e-demo-]"):
            self.assertIn(needle, ps)

    def test_a_failed_sweep_keeps_only_the_start_time(self):
        (self.root / "scripts" / "cloudflare_api.py").write_text(
            FAKE_PYTHON_SWEEP.replace('print("sweep: no left-over demo object")', "sys.exit(1)"), encoding="utf-8")
        self.work.mkdir()
        (self.work / "started-at").write_text("2026-10-22T10:00:00Z\n", encoding="utf-8")
        (self.work / "web-headers").write_text("CF-Access-Client-Secret: synthetic\n", encoding="utf-8")
        out = self.run_script("cleanup")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), ["started-at"])
        self.assertIn("to sweep again", out.stderr)

    def test_cleanup_without_a_run_sweeps_nothing(self):
        out = self.run_script("cleanup", TF_VAR_access_team_name=None)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("nothing to sweep", out.stdout)
        self.assertFalse(any(c.startswith("cloudflare_api.py") for c in self.calls_list()))

    def test_a_run_refuses_to_start_over_an_earlier_one_or_without_credentials(self):
        out = self.run_script(TF_VAR_zone=None)
        self.assertEqual(out.returncode, 2)
        self.assertIn("TF_VAR_zone is not set", out.stderr)
        self.work.mkdir()
        tools = self.root / "bin"
        for tool in ("tofu", "ansible-playbook", "ansible", "ansible-galaxy", "curl", "ssh", "ssh-keygen", "tar"):
            (tools / tool).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (tools / tool).chmod(0o755)
        out = self.run_script()
        self.assertEqual(out.returncode, 2)
        self.assertIn("is left from an earlier run", out.stderr)
        self.assertEqual(self.calls_list(), [])

    def test_rejects_an_unknown_argument(self):
        self.assertEqual(self.run_script("teardown").returncode, 2)


if __name__ == "__main__":
    unittest.main()
