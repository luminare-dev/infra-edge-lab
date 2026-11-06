"""Conventions of the OpenTofu code in tofu/ that "tofu validate" and "tofu test" do not check.

- Every module has the expected files, a required_version, a lock file for its providers and
  tests; no module configures a provider.
- Every environment has the expected files and a lock file that locks each provider to the same
  build as the modules; its tests mock every provider.
- State: the remote environments use the S3 backend with a lock file and no endpoint or
  credential in the code, the local environment a local file, and every environment the same
  enforced encryption.
- scripts/tofu_env.sh (task init, plan and test of one environment), run with fake tofu and sops
  binaries: the BACKEND=local override, the passphrase check, the SOPS file and the tunnel token
  that a plan never reads.
- The .tf and .tftest.hcl files stay valid for Terraform: no .tofu file in a module, only
  encryption.tofu in an environment, and no OpenTofu-only construct in a .tf file.
- No real zone, host name or address: the zone is always a variable, and examples use
  documentation names and ranges.
- The tunnel token is never an output.
- The pins of scripts/install_tofu_tools.sh agree with docs/toolchain.md, the CI job "tofu" runs
  every step of scripts/check_tofu.sh (the IaC security scan with Trivy among them), every
  finding the scan accepts has a reason, and the host image is pinned by digest.

Standard library only, like the template's tests.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ("cf_access_app", "cf_tunnel", "docker_host", "hcloud_vm", "pve_vm")
MODULE_FILES = ("versions.tf", "variables.tf", "main.tf", "outputs.tf", "README.md", ".terraform.lock.hcl")
ENVS = ("demo", "lab", "local", "showcase")
REMOTE_STATE_ENVS = ("demo", "lab", "showcase")
ENV_FILES = ("versions.tf", "main.tf", "variables.tf", "outputs.tf", "backend.tf", "encryption.tofu",
             ".terraform.lock.hcl")
CHECK_STEPS = ("fmt", "validate", "tflint", "iac", "test", "integration", "compat")


def read(rel: str | Path) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def code_files() -> list[Path]:
    """Every OpenTofu file under tofu/ except provider downloads."""
    return sorted(p for p in (ROOT / "tofu").rglob("*")
                  if p.is_file() and ".terraform" not in p.parts and p.suffix in {".tf", ".hcl", ".tofu"}
                  and p.name != ".terraform.lock.hcl")


def strip_comments(text: str) -> str:
    """HCL without # and // line comments (good enough for the patterns checked here)."""
    return "\n".join(re.sub(r"(^|\s)(#|//).*$", "", line) for line in text.splitlines())


def required_providers(versions_tf: str) -> dict[str, str]:
    """source -> version constraint from a versions.tf."""
    pairs = re.findall(r'source\s*=\s*"([^"]+)"\s*\n\s*version\s*=\s*"([^"]+)"', versions_tf)
    return {source.lower(): constraint for source, constraint in pairs}


def lock_entries(lock: str) -> dict[str, dict[str, object]]:
    """provider address -> {version, constraints, h1 (number of h1 hashes), hashes} from a lock file."""
    entries = {}
    for m in re.finditer(r'provider "registry\.opentofu\.org/([^"]+)" \{(.*?)\n\}', lock, re.DOTALL):
        body = m.group(2)
        entries[m.group(1)] = {
            "version": re.search(r'version\s*=\s*"([^"]+)"', body).group(1),
            "constraints": re.search(r'constraints\s*=\s*"([^"]+)"', body).group(1),
            "h1": len(re.findall(r'"h1:', body)),
            "hashes": sorted(re.findall(r'"((?:h1|zh):[^"]+)"', body)),
        }
    return entries


def root_dirs() -> list[str]:
    """Every module and environment directory, relative to the repository root."""
    return [f"tofu/modules/{m}" for m in MODULES] + [f"tofu/envs/{e}" for e in ENVS]


class ModuleLayoutTest(unittest.TestCase):
    def test_every_module_has_its_files_and_tests(self):
        for module in MODULES:
            for name in MODULE_FILES:
                with self.subTest(module=module, file=name):
                    self.assertTrue((ROOT / "tofu" / "modules" / module / name).is_file())
            with self.subTest(module=module, file="tests"):
                self.assertTrue(list((ROOT / "tofu" / "modules" / module / "tests").glob("*.tftest.hcl")))

    def test_required_version(self):
        for module in MODULES:
            with self.subTest(module=module):
                self.assertRegex(read(f"tofu/modules/{module}/versions.tf"),
                                 r'required_version\s*=\s*">= 1\.11\.0"')

    def test_lock_files_match_the_constraints(self):
        for module in MODULES:
            providers = required_providers(read(f"tofu/modules/{module}/versions.tf"))
            locked = lock_entries(read(f"tofu/modules/{module}/.terraform.lock.hcl"))
            with self.subTest(module=module):
                self.assertTrue(providers)
                self.assertEqual(set(locked), set(providers))
            for source, constraint in providers.items():
                with self.subTest(module=module, provider=source):
                    self.assertEqual(locked[source]["constraints"], constraint)
                    # tofu providers lock -platform=linux_amd64 -platform=darwin_arm64
                    self.assertGreaterEqual(locked[source]["h1"], 2)

    def test_a_provider_has_one_constraint_everywhere(self):
        seen: dict[str, str] = {}
        for rel in root_dirs():
            for source, constraint in required_providers(read(f"{rel}/versions.tf")).items():
                with self.subTest(dir=rel, provider=source):
                    self.assertEqual(seen.setdefault(source, constraint), constraint)

    def test_a_provider_is_locked_to_one_build_everywhere(self):
        """An environment locks the same version and checksums as the modules it calls."""
        seen: dict[str, tuple[str, list[str]]] = {}
        for rel in root_dirs():
            for source, entry in lock_entries(read(f"{rel}/.terraform.lock.hcl")).items():
                with self.subTest(dir=rel, provider=source):
                    locked = (entry["version"], entry["hashes"])
                    self.assertEqual(seen.setdefault(source, locked), locked)

    def test_modules_configure_no_provider(self):
        for module in MODULES:
            for path in (ROOT / "tofu" / "modules" / module).glob("*.tf"):
                with self.subTest(file=path.relative_to(ROOT).as_posix()):
                    self.assertNotRegex(strip_comments(read(path)), r'(?m)^\s*provider\s+"')


class EnvironmentLayoutTest(unittest.TestCase):
    def test_every_environment_has_its_files_and_tests(self):
        self.assertEqual(sorted(p.name for p in (ROOT / "tofu" / "envs").iterdir() if p.is_dir()), list(ENVS))
        for env in ENVS:
            for name in ENV_FILES:
                with self.subTest(env=env, file=name):
                    self.assertTrue((ROOT / "tofu" / "envs" / env / name).is_file())
            with self.subTest(env=env, file="tests"):
                self.assertTrue(list((ROOT / "tofu" / "envs" / env / "tests").glob("*.tftest.hcl")))

    def test_required_version(self):
        for env in ENVS:
            with self.subTest(env=env):
                self.assertRegex(read(f"tofu/envs/{env}/versions.tf"), r'required_version\s*=\s*">= 1\.11\.0"')

    def test_lock_files_match_the_constraints(self):
        for env in ENVS:
            providers = required_providers(read(f"tofu/envs/{env}/versions.tf"))
            locked = lock_entries(read(f"tofu/envs/{env}/.terraform.lock.hcl"))
            with self.subTest(env=env):
                self.assertTrue(providers)
                self.assertEqual(set(locked), set(providers))
            for source, constraint in providers.items():
                with self.subTest(env=env, provider=source):
                    self.assertEqual(locked[source]["constraints"], constraint)
                    self.assertGreaterEqual(locked[source]["h1"], 2)

    def test_local_environment_needs_no_cloud_provider(self):
        """The local environment runs on fork pull requests: Docker only, no credentials."""
        self.assertEqual(set(required_providers(read("tofu/envs/local/versions.tf"))), {"kreuzwerker/docker"})

    def test_environment_tests_mock_every_provider(self):
        """The guard tests never need a credential or a network connection."""
        for env in ENVS:
            providers = {source.split("/")[1] for source in required_providers(read(f"tofu/envs/{env}/versions.tf"))}
            for path in sorted((ROOT / "tofu" / "envs" / env / "tests").glob("*.tftest.hcl")):
                text = strip_comments(read(path))
                with self.subTest(file=path.relative_to(ROOT).as_posix()):
                    self.assertEqual(set(re.findall(r'(?m)^mock_provider\s+"([^"]+)"', text)), providers)
                    self.assertNotRegex(text, r'(?m)^provider\s+"')

    def test_tunnel_token_is_never_read_in_a_plan(self):
        """Read-only plans leave fetch_tunnel_token false."""
        for env in ("demo", "showcase"):
            with self.subTest(env=env):
                block = re.search(r'(?s)variable "fetch_tunnel_token" \{.*?\n\}', read(f"tofu/envs/{env}/variables.tf"))
                self.assertIsNotNone(block)
                self.assertRegex(block.group(0), r"default\s*=\s*false")
        self.assertIn("TF_VAR_fetch_tunnel_token=false", read("scripts/tofu_env.sh"))


class StateTest(unittest.TestCase):
    """Encrypted state, in R2 with a lock file or in a local file."""

    S3_SETTINGS = {
        "bucket": '"luminare-tfstate"',
        "region": '"auto"',
        "use_lockfile": "true",
        "use_path_style": "true",
        "skip_credentials_validation": "true",
        "skip_region_validation": "true",
        "skip_requesting_account_id": "true",
        "skip_s3_checksum": "true",
        "skip_metadata_api_check": "true",
    }

    def backend(self, env: str) -> tuple[str, dict[str, str]]:
        text = strip_comments(read(f"tofu/envs/{env}/backend.tf"))
        m = re.search(r'(?s)backend\s+"([^"]+)"\s*\{(.*?)\n  \}', text)
        self.assertIsNotNone(m, env)
        return m.group(1), dict(re.findall(r'(?m)^\s*(\w+)\s*=\s*(.+?)\s*$', m.group(2)))

    def test_remote_environments_use_the_s3_backend_with_a_lock_file(self):
        for env in REMOTE_STATE_ENVS:
            kind, settings = self.backend(env)
            with self.subTest(env=env):
                self.assertEqual(kind, "s3")
                self.assertEqual(settings, {**self.S3_SETTINGS, "key": f'"{env}/terraform.tfstate"'})

    def test_no_endpoint_or_credential_in_the_backend(self):
        """The account-specific endpoint and the keys come from the environment (AWS_*)."""
        for env in ENVS:
            text = strip_comments(read(f"tofu/envs/{env}/backend.tf"))
            with self.subTest(env=env):
                self.assertNotRegex(text, r"\b(endpoints?|access_key|secret_key|token|profile)\s*=")

    def test_local_environment_keeps_a_local_state_file(self):
        kind, settings = self.backend("local")
        self.assertEqual((kind, settings), ("local", {"path": '"terraform.tfstate"'}))

    def test_one_encryption_file_for_every_environment(self):
        texts = {env: read(f"tofu/envs/{env}/encryption.tofu") for env in ENVS}
        self.assertEqual(len(set(texts.values())), 1, "encryption.tofu differs between environments")

    def test_encryption_is_enforced_for_state_and_plan(self):
        text = strip_comments(read("tofu/envs/local/encryption.tofu"))
        self.assertRegex(text, r'key_provider\s+"pbkdf2"\s+"main"\s*\{\s*passphrase\s*=\s*var\.state_passphrase\s*\}')
        self.assertRegex(text, r'method\s+"aes_gcm"\s+"main"\s*\{\s*keys\s*=\s*key_provider\.pbkdf2\.main\s*\}')
        for block in ("state", "plan"):
            with self.subTest(block=block):
                self.assertRegex(text, rf"(?s)\n    {block}\s*\{{\s*method\s*=\s*method\.aes_gcm\.main\s*"
                                       rf"enforced\s*=\s*true\s*\}}")
        # The migration fallback from a clear-text state is never committed.
        self.assertNotIn("unencrypted", text)
        self.assertNotIn("fallback", text)

    def test_passphrase_is_sensitive_and_long_enough(self):
        text = read("tofu/envs/local/encryption.tofu")
        block = re.search(r'(?s)variable "state_passphrase" \{.*?\n\}', text).group(0)
        self.assertRegex(block, r"sensitive\s*=\s*true")
        self.assertRegex(block, r"length\(var\.state_passphrase\)\s*>=\s*16")
        self.assertNotRegex(block, r"\bdefault\s*=")

    def test_only_encryption_tofu_is_opentofu_only(self):
        for env in ENVS:
            with self.subTest(env=env):
                self.assertEqual([p.name for p in (ROOT / "tofu" / "envs" / env).rglob("*.tofu")
                                  if ".terraform" not in p.parts], ["encryption.tofu"])
                for path in (ROOT / "tofu" / "envs" / env).glob("*.tf"):
                    self.assertNotIn("state_passphrase", read(path), path.name)


class EnvironmentTasksTest(unittest.TestCase):
    def test_tasks_take_every_environment(self):
        taskfile = read("Taskfile.yml")
        for task in ("init", "plan"):
            with self.subTest(task=task):
                block = re.search(rf"(?s)\n  {task}:\n(.*?)(?=\n  \w[\w:-]*:\n|\Z)", taskfile)
                self.assertIsNotNone(block)
                self.assertIn(f"enum: [{', '.join(('local', 'lab', 'demo', 'showcase'))}]", block.group(1))
                self.assertIn(f"bash scripts/tofu_env.sh {task} {{{{.ENV}}}}", block.group(1))
        self.assertIn("bash scripts/tofu_env.sh test {{.ENV}}", taskfile)

    def test_script_is_executable(self):
        self.assertTrue((ROOT / "scripts" / "tofu_env.sh").stat().st_mode & 0o111)


# Stand-ins for tofu and sops: each call is appended to $CALLS, every argument in brackets, so
# that the tests see the argument boundaries. The fake sops runs the command the way sops
# exec-env does (through /bin/sh) with a passphrase and an endpoint taken "from the file".
FAKE_TOFU = """#!/bin/sh
{ printf 'tofu'; printf ' [%s]' "$@"; printf ' fetch=%s\\n' "${TF_VAR_fetch_tunnel_token-unset}"; } >>"$CALLS"
"""
FAKE_SOPS = """#!/bin/sh
printf 'sops [%s] [%s]\\n' "$1" "$2" >>"$CALLS"
[ "$1" = exec-env ] || exit 9
TF_VAR_state_passphrase=passphrase-from-the-sops-file AWS_ENDPOINT_URL_S3=https://r2.example.com \\
  exec /bin/sh -c "$3"
"""


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class EnvironmentScriptTest(unittest.TestCase):
    """scripts/tofu_env.sh, run on a copy of the repository layout with fake tofu and sops."""

    PASSPHRASE = "passphrase-of-the-test-run"
    # Variables of the caller that would change what the script does.
    ENDPOINT = "https://0123456789abcdef0123456789abcdef.r2.example.com"
    CLEARED = ("BACKEND", "SECRETS", "TOFU_ENV_IN_SOPS", "TF_VAR_state_passphrase", "TF_VAR_fetch_tunnel_token",
               "AWS_ENDPOINT_URL_S3")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "scripts").mkdir()
        shutil.copy2(ROOT / "scripts" / "tofu_env.sh", self.root / "scripts" / "tofu_env.sh")
        for env in ENVS:
            (self.root / "tofu" / "envs" / env).mkdir(parents=True)
        (self.root / "secrets").mkdir()
        (self.root / "bin").mkdir()
        for name, body in (("tofu", FAKE_TOFU), ("sops", FAKE_SOPS)):
            fake = self.root / "bin" / name
            fake.write_text(body, encoding="utf-8")
            fake.chmod(0o755)
        self.calls_file = self.root / "calls.log"

    def run_script(self, *args: str, **env: str | None) -> subprocess.CompletedProcess:
        environ = {k: v for k, v in os.environ.items() if k not in self.CLEARED}
        environ.update(PATH=f"{self.root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
                       CALLS=str(self.calls_file), TF_VAR_state_passphrase=self.PASSPHRASE)
        for key, value in env.items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        return subprocess.run(["bash", str(self.root / "scripts" / "tofu_env.sh"), *args], env=environ,
                              capture_output=True, text=True, timeout=60, check=False)

    def calls(self) -> list[str]:
        return self.calls_file.read_text(encoding="utf-8").splitlines() if self.calls_file.exists() else []

    def override(self, env: str) -> Path:
        return self.root / "tofu" / "envs" / env / "backend_override.tf"

    def test_backend_local_writes_the_override(self):
        out = self.run_script("init", "lab", BACKEND="local")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(strip_comments(self.override("lab").read_text(encoding="utf-8")),
                         r'terraform\s*\{\s*backend\s+"local"\s*\{\s*path\s*=\s*"terraform\.tfstate"\s*\}\s*\}')
        self.assertEqual(self.calls(), ["tofu [-chdir=tofu/envs/lab] [init] [-input=false] [-reconfigure] fetch=unset"])

    def test_remote_backend_removes_the_override(self):
        self.override("demo").write_text("# left from an earlier BACKEND=local\n", encoding="utf-8")
        out = self.run_script("init", "demo", "-upgrade", AWS_ENDPOINT_URL_S3=self.ENDPOINT)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(self.override("demo").exists())
        self.assertEqual(self.calls(),
                         ["tofu [-chdir=tofu/envs/demo] [init] [-input=false] [-reconfigure] [-upgrade] fetch=unset"])

    def test_local_environment_never_gets_an_override(self):
        out = self.run_script("init", "local", BACKEND="local")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertFalse(self.override("local").exists())

    def test_plan_never_reads_the_tunnel_token(self):
        out = self.run_script("plan", "showcase", "-out=show case.tfplan", TF_VAR_fetch_tunnel_token="true",
                              AWS_ENDPOINT_URL_S3=self.ENDPOINT)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(),
                         ["tofu [-chdir=tofu/envs/showcase] [plan] [-input=false] [-out=show case.tfplan] fetch=false"])

    def test_init_and_plan_need_a_passphrase_of_16_characters(self):
        for action in ("init", "plan"):
            for env in ("local", "lab"):
                for passphrase in (None, "", "fifteen-chars-x"):
                    with self.subTest(action=action, env=env, passphrase=passphrase):
                        out = self.run_script(action, env, TF_VAR_state_passphrase=passphrase)
                        self.assertEqual(out.returncode, 2)
                        self.assertIn("TF_VAR_state_passphrase", out.stderr)
        self.assertEqual(self.calls(), [])
        out = self.run_script("init", "local", TF_VAR_state_passphrase="sixteen-chars-xx")
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_remote_state_needs_the_r2_endpoint(self):
        """Without AWS_ENDPOINT_URL_S3 the S3 backend would contact AWS: init and plan refuse."""
        for args in (("init", "lab"), ("plan", "lab"), ("init", "showcase", "-upgrade")):
            with self.subTest(args=args):
                out = self.run_script(*args)
                self.assertEqual(out.returncode, 2)
                self.assertIn("AWS_ENDPOINT_URL_S3", out.stderr)
        self.assertEqual(self.calls(), [])
        # A local state file and the local environment need no endpoint.
        for args, env in ((("init", "lab"), {"BACKEND": "local"}), (("plan", "lab"), {}),
                          (("init", "local"), {}), (("plan", "local"), {})):
            with self.subTest(args=args, env=env):
                out = self.run_script(*args, **env)
                self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(len(self.calls()), 4)

    def test_tests_need_no_backend_no_passphrase_and_no_sops(self):
        (self.root / "secrets" / "lab.enc.env").write_text("never read by a test run\n", encoding="utf-8")
        out = self.run_script("test", "lab", "-verbose", TF_VAR_state_passphrase=None)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), [
            "tofu [-chdir=tofu/envs/lab] [init] [-backend=false] [-input=false] [-lockfile=readonly] fetch=unset",
            "tofu [-chdir=tofu/envs/lab] [test] [-verbose] fetch=unset",
        ])

    def test_reads_the_sops_file_of_the_environment(self):
        """The passphrase exists only inside sops exec-env; arguments keep their boundaries."""
        (self.root / "secrets" / "lab.enc.env").write_text("read by the fake sops only\n", encoding="utf-8")
        out = self.run_script("plan", "lab", "-out=lab plan.tfplan", TF_VAR_state_passphrase=None)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), [
            "sops [exec-env] [secrets/lab.enc.env]",
            "tofu [-chdir=tofu/envs/lab] [plan] [-input=false] [-out=lab plan.tfplan] fetch=false",
        ])

    def test_secrets_names_another_sops_file(self):
        (self.root / "secrets" / "lab-ci.enc.env").write_text("read-only plan credentials\n", encoding="utf-8")
        out = self.run_script("plan", "lab", SECRETS="secrets/lab-ci.enc.env", TF_VAR_state_passphrase=None)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls()[0], "sops [exec-env] [secrets/lab-ci.enc.env]")

    def test_rejects_wrong_input_before_running_anything(self):
        cases = {
            "missing environment": (("init",), {}),
            "unknown action": (("import", "lab"), {}),
            "unknown environment": (("init", "prod"), {}),
            "unknown backend": (("init", "lab"), {"BACKEND": "s3"}),
            "missing SOPS file": (("plan", "lab"), {"SECRETS": "secrets/missing.enc.env"}),
        }
        for name, (args, env) in cases.items():
            with self.subTest(case=name):
                out = self.run_script(*args, **env)
                self.assertEqual(out.returncode, 2, out.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(list(self.root.rglob("backend_override.tf")), [])


    def test_apply_destroy_and_output_pass_their_arguments(self):
        """task up, task destroy and task inventory (scripts/environment.sh) run these."""
        for args in (("apply", "local", "-auto-approve"), ("destroy", "local", "-auto-approve"),
                     ("output", "local", "-json")):
            with self.subTest(args=args):
                out = self.run_script(*args)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(out.stdout, "", "output must print nothing but the outputs")
        self.assertEqual(self.calls(), [
            "tofu [-chdir=tofu/envs/local] [apply] [-auto-approve] fetch=unset",
            "tofu [-chdir=tofu/envs/local] [destroy] [-auto-approve] fetch=unset",
            "tofu [-chdir=tofu/envs/local] [output] [-json] fetch=unset",
        ])

    def test_remote_state_actions_follow_the_last_init(self):
        """Without the override file (the last init chose R2), every action needs the endpoint."""
        for action in ("apply", "destroy", "output"):
            with self.subTest(action=action):
                out = self.run_script(action, "lab")
                self.assertEqual(out.returncode, 2)
                self.assertIn("AWS_ENDPOINT_URL_S3", out.stderr)
        self.override("lab").write_text("# written by an init with BACKEND=local\n", encoding="utf-8")
        out = self.run_script("output", "lab", "-raw", "tunnel_id")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.calls(), ["tofu [-chdir=tofu/envs/lab] [output] [-raw] [tunnel_id] fetch=unset"])

    def test_showcase_is_never_destroyed(self):
        out = self.run_script("destroy", "showcase", "-auto-approve", AWS_ENDPOINT_URL_S3=self.ENDPOINT)
        self.assertEqual(out.returncode, 2)
        self.assertIn("refusing to destroy showcase", out.stderr)
        (self.root / "secrets" / "showcase.enc.env").write_text("never read\n", encoding="utf-8")
        out = self.run_script("destroy", "showcase", TF_VAR_state_passphrase=None)
        self.assertEqual(out.returncode, 2)
        self.assertEqual(self.calls(), [], "neither sops nor tofu may run")


class TerraformCompatibilityTest(unittest.TestCase):
    OPENTOFU_ONLY = {
        "state or plan encryption block": r"(?m)^\s*encryption\s*\{",
        "variable in prevent_destroy": r"prevent_destroy\s*=\s*(?!true\b|false\b)",
        "provider for_each": r'(?s)provider\s+"[^"]+"\s*\{[^}]*\bfor_each\b',
        "enabled meta-argument": r"(?s)lifecycle\s*\{[^}]*\benabled\s*=",
    }

    def test_no_tofu_files_in_modules(self):
        self.assertEqual([p for p in (ROOT / "tofu" / "modules").rglob("*.tofu") if ".terraform" not in p.parts], [])

    def test_no_opentofu_only_syntax(self):
        for path in code_files():
            if path.suffix == ".tofu":
                continue
            text = strip_comments(read(path))
            for name, pattern in self.OPENTOFU_ONLY.items():
                with self.subTest(file=path.relative_to(ROOT).as_posix(), construct=name):
                    self.assertNotRegex(text, pattern)

    def test_no_ssh_block_for_the_hypervisor_api(self):
        """bpg/proxmox needs SSH only for snippets and uploads, which this code never uses."""
        for path in code_files():
            with self.subTest(file=path.relative_to(ROOT).as_posix()):
                self.assertNotRegex(strip_comments(read(path)), r"(?m)^\s*ssh\s*\{")


class NoRealNamesTest(unittest.TestCase):
    """The zone is a variable; examples use documentation names and addresses only."""

    HOST_RE = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|tech|io|dev|at|de|eu|app|cloud)\b",
                         re.IGNORECASE)
    # cfargotunnel.com is the target of every tunnel CNAME; r2.cloudflarestorage.com is the
    # endpoint domain of R2 in comments, always below a placeholder account ID.
    ALLOWED_HOSTS = ("example.com", "example.net", "example.org", "cfargotunnel.com", "github.com",
                     "r2.cloudflarestorage.com")
    IPV4_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?:/\d{1,2})?(?![\w.])")
    DOC_NETWORKS = [ipaddress.ip_network(n) for n in
                    ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "127.0.0.0/8", "0.0.0.0/32")]

    def files(self) -> list[Path]:
        readmes = [p for p in sorted((ROOT / "tofu").rglob("README.md")) if ".terraform" not in p.parts]
        return code_files() + readmes + [ROOT / "images" / "systemd-host" / "Dockerfile"]

    def test_only_documentation_host_names(self):
        for path in self.files():
            hosts = {m.group(0).lower() for m in self.HOST_RE.finditer(read(path))}
            with self.subTest(file=path.relative_to(ROOT).as_posix()):
                unexpected = sorted(h for h in hosts
                                    if not any(h == a or h.endswith("." + a) for a in self.ALLOWED_HOSTS))
                self.assertEqual(unexpected, [])

    def test_only_documentation_addresses(self):
        for path in self.files():
            with self.subTest(file=path.relative_to(ROOT).as_posix()):
                for text in self.IPV4_RE.findall(read(path)):
                    address = ipaddress.ip_address(text)
                    self.assertTrue(any(address in net for net in self.DOC_NETWORKS), text)


class TunnelTokenTest(unittest.TestCase):
    def test_no_output_carries_a_tunnel_token(self):
        for path in (ROOT / "tofu").rglob("*.tf"):
            if ".terraform" in path.parts:
                continue
            for block in re.findall(r'(?s)output\s+"[^"]+"\s*\{.*?\n\}', read(path)):
                with self.subTest(file=path.relative_to(ROOT).as_posix(), output=block.split('"')[1]):
                    self.assertNotRegex(block, r"tunnel_cloudflared_token|tunnel_token|tunnel_secret")


class ToolchainTest(unittest.TestCase):
    def binaries(self) -> dict[str, dict[str, str]]:
        rows = {}
        inside = False
        for line in read("docs/toolchain.md").splitlines():
            if line.startswith("| Tool |"):
                inside = True
                continue
            if inside:
                if not line.startswith("|"):
                    break
                if line.startswith("|---"):
                    continue
                cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
                rows[cells[0].lower()] = {"version": cells[1], "file": cells[3], "sha256": cells[4]}
        return rows

    def test_installer_pins_match_the_toolchain(self):
        script = read("scripts/install_tofu_tools.sh")
        tools = self.binaries()
        for tool, name in (("opentofu", "TOFU"), ("tflint", "TFLINT"), ("terraform", "TERRAFORM"),
                           ("trivy", "TRIVY")):
            with self.subTest(tool=tool):
                self.assertIn(tool, tools)
                self.assertRegex(script, rf"(?m)^{name}_VERSION={re.escape(tools[tool]['version'])}$")
                self.assertRegex(script, rf"(?m)^{name}_SHA256={tools[tool]['sha256']}$")

    def test_ci_runs_every_step(self):
        ci = read(".github/workflows/ci.yml")
        job = ci.split("\n  tofu:\n", 1)
        self.assertEqual(len(job), 2, "ci.yml has no job named tofu")
        self.assertIn("bash scripts/install_tofu_tools.sh", job[1])
        for step in CHECK_STEPS:
            with self.subTest(step=step):
                self.assertIn(f"bash scripts/check_tofu.sh {step}\n", job[1])
        script = read("scripts/check_tofu.sh")
        for step in CHECK_STEPS:
            with self.subTest(script_step=step):
                self.assertIn(f"step_{step}()", script)

    def test_taskfile_runs_the_checks(self):
        self.assertIn("bash scripts/check_tofu.sh", read("Taskfile.yml"))

    def test_ci_installs_the_pinned_trivy(self):
        job = read(".github/workflows/ci.yml").split("\n  tofu:\n", 1)[1]
        self.assertRegex(job, r"bash scripts/install_tofu_tools\.sh \S+ tofu tflint trivy\n")
        script = read("scripts/check_tofu.sh")
        self.assertIn("trivy config --skip-check-update", script)
        self.assertIn("--exit-code 1", script)
        self.assertIn('--ignorefile "$root/.trivyignore.yaml"', script)

    def test_every_accepted_scan_finding_has_a_reason(self):
        text = read(".trivyignore.yaml")
        entries = re.split(r"\n  - id: ", text.split("misconfigurations:\n", 1)[1])[1:]
        self.assertGreaterEqual(len(entries), 1)
        for entry in entries:
            finding = entry.split("\n", 1)[0]
            with self.subTest(finding=finding):
                self.assertRegex(finding, r"^[A-Z]+-\d{4}$")
                self.assertRegex(entry, r"\n    paths:\n      - \S+")
                self.assertRegex(entry, r"\n    statement: >-\n      \S")

    def test_host_image_is_pinned_by_digest(self):
        froms = re.findall(r"(?m)^FROM\s+(\S+)", read("images/systemd-host/Dockerfile"))
        bases = [f for f in froms if not f.startswith("${")]
        self.assertEqual(len(bases), 2)
        for image in bases:
            with self.subTest(image=image):
                self.assertRegex(image, r"^[a-z0-9./-]+:[\w.-]+@sha256:[0-9a-f]{64}$")

    def test_dependabot_watches_the_host_image(self):
        self.assertRegex(read(".github/dependabot.yml"),
                         r"package-ecosystem: docker\n\s+directory: /images/systemd-host\n")


if __name__ == "__main__":
    unittest.main()
