"""Conventions of the OpenTofu code in tofu/ that "tofu validate" and "tofu test" do not check.

- Every module has the expected files, a required_version, a lock file for its providers and
  tests; no module configures a provider.
- The .tf and .tftest.hcl files stay valid for Terraform: no .tofu file and no OpenTofu-only
  construct in a module (docs/adr/0005).
- No real zone, host name or address: the zone is always a variable, and examples use
  documentation names and ranges (docs/adr/0009).
- The tunnel token is never an output (docs/adr/0011).
- The pins of scripts/install_tofu_tools.sh agree with docs/toolchain.md, the CI job "tofu" runs
  every step of scripts/check_tofu.sh (the IaC security scan with Trivy among them), every
  finding the scan accepts has a reason, and the host image is pinned by digest.

Standard library only, like the template's tests.
"""

from __future__ import annotations

import ipaddress
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ("cf_access_app", "cf_tunnel", "docker_host", "hcloud_vm", "pve_vm")
MODULE_FILES = ("versions.tf", "variables.tf", "main.tf", "outputs.tf", "README.md", ".terraform.lock.hcl")
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
    """provider address -> {version, constraints, h1 (number of h1 hashes)} from a lock file."""
    entries = {}
    for m in re.finditer(r'provider "registry\.opentofu\.org/([^"]+)" \{(.*?)\n\}', lock, re.DOTALL):
        body = m.group(2)
        entries[m.group(1)] = {
            "version": re.search(r'version\s*=\s*"([^"]+)"', body).group(1),
            "constraints": re.search(r'constraints\s*=\s*"([^"]+)"', body).group(1),
            "h1": len(re.findall(r'"h1:', body)),
        }
    return entries


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
        for module in MODULES:
            for source, constraint in required_providers(read(f"tofu/modules/{module}/versions.tf")).items():
                with self.subTest(module=module, provider=source):
                    self.assertEqual(seen.setdefault(source, constraint), constraint)

    def test_modules_configure_no_provider(self):
        for module in MODULES:
            for path in (ROOT / "tofu" / "modules" / module).glob("*.tf"):
                with self.subTest(file=path.relative_to(ROOT).as_posix()):
                    self.assertNotRegex(strip_comments(read(path)), r'(?m)^\s*provider\s+"')


class TerraformCompatibilityTest(unittest.TestCase):
    OPENTOFU_ONLY = {
        "state or plan encryption block": r"(?m)^\s*encryption\s*\{",
        "variable in prevent_destroy": r"prevent_destroy\s*=\s*(?!true\b|false\b)",
        "provider for_each": r'(?s)provider\s+"[^"]+"\s*\{[^}]*\bfor_each\b',
        "enabled meta-argument": r"(?s)lifecycle\s*\{[^}]*\benabled\s*=",
    }

    def test_no_tofu_files_in_modules(self):
        self.assertEqual(list((ROOT / "tofu" / "modules").rglob("*.tofu")), [])

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
    ALLOWED_HOSTS = ("example.com", "example.net", "example.org", "cfargotunnel.com", "github.com")
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
