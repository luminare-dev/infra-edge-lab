"""The pinned toolchain agrees everywhere it is written down.

docs/toolchain.md is the list of pins. These tests compare it with the workflow inputs that
download the same binaries, the hash-pinned requirements files, the Taskfile and the README, and
(when scripts/run_tests.sh runs them) with the versions really installed in the test environment.

Python versions live only in the requirements files, which Dependabot updates: the Python table of
docs/toolchain.md and the README name the file instead of the version, so an update pull request
passes these tests without a hand edit.
"""

from __future__ import annotations

import importlib.metadata
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLCHAIN = ROOT / "docs" / "toolchain.md"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==([^\s;\\]+)")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def table_rows(markdown: str, first_header: str) -> list[list[str]]:
    """Rows of the Markdown table whose header starts with `first_header`, cells stripped of `."""
    rows, inside = [], False
    for line in markdown.splitlines():
        if line.startswith(f"| {first_header} |"):
            inside = True
            continue
        if inside:
            if not line.startswith("|"):
                break
            if line.startswith("|---"):
                continue
            rows.append([cell.strip().strip("`") for cell in line.strip().strip("|").split("|")])
    return rows


def binaries() -> dict[str, dict[str, str]]:
    """Tool name (lower case) -> version, file and sha256 from the binary table."""
    return {row[0].lower(): {"version": row[1], "file": row[3], "sha256": row[4]}
            for row in table_rows(read("docs/toolchain.md"), "Tool")}


def python_packages() -> dict[str, str]:
    """Package name -> "Pinned in" cell of the Python table (extras in parentheses are dropped)."""
    return {row[0].split()[0].lower(): row[1] for row in table_rows(read("docs/toolchain.md"), "Package")}


def requirement_pins(rel: str) -> dict[str, str]:
    pins = {}
    for line in read(rel).splitlines():
        m = PIN_RE.match(line)
        if m:
            pins[m.group(1).lower()] = m.group(3)
    return pins


def workflow_default(rel: str, name: str) -> str:
    m = re.search(rf"^\s+{re.escape(name)}:\n(?:\s+(?:description|type):.*\n)*\s+default:\s*(\S+)",
                  read(rel), re.MULTILINE)
    if not m:
        raise AssertionError(f"{rel}: no default for input {name}")
    return m.group(1)


class BinaryPinsTest(unittest.TestCase):
    def test_every_binary_has_a_version_file_and_sha256(self):
        tools = binaries()
        self.assertGreaterEqual(len(tools), 9, tools)
        for name, pin in tools.items():
            with self.subTest(tool=name):
                self.assertRegex(pin["version"], r"^\d+(\.\d+){1,2}$")
                self.assertRegex(pin["sha256"], SHA256_RE)
                self.assertTrue(pin["file"], "file name missing")

    def test_workflow_downloads_match_the_toolchain(self):
        tools = binaries()
        for tool, rel in (("gitleaks", ".github/workflows/reusable-gitleaks.yml"),
                          ("actionlint", ".github/workflows/reusable-ci.yml")):
            with self.subTest(tool=tool):
                self.assertEqual(workflow_default(rel, f"{tool}-version"), tools[tool]["version"])
                self.assertEqual(workflow_default(rel, f"{tool}-sha256"), tools[tool]["sha256"])

    def test_markdownlint_version_matches_the_taskfile(self):
        pinned = re.search(r"markdownlint-cli2 \*\*(\d+\.\d+\.\d+)\*\*", read("docs/toolchain.md"))
        self.assertIsNotNone(pinned)
        self.assertIn(f"markdownlint-cli2@{pinned.group(1)} ", read("Taskfile.yml"))

    def test_readme_names_the_pinned_go_task(self):
        rows = [row for row in table_rows(read("README.md"), "Component") if row[0] == "go-task"]
        self.assertEqual(len(rows), 1)
        version = binaries()["go-task"]["version"]
        self.assertEqual(rows[0][1:], [version, version])


class TofuJobPinsTest(unittest.TestCase):
    def test_trivy_download_of_the_ci_job_matches_the_toolchain(self):
        """CI's tofu job installs Trivy with scripts/install_tofu_tools.sh and runs the scan."""
        pin = binaries()["trivy"]
        script = read("scripts/install_tofu_tools.sh")
        self.assertRegex(script, rf"(?m)^TRIVY_VERSION={re.escape(pin['version'])}$")
        self.assertRegex(script, rf"(?m)^TRIVY_SHA256={pin['sha256']}$")
        self.assertIn(pin["file"].replace(pin["version"], "${TRIVY_VERSION}"), script)
        job = read(".github/workflows/ci.yml").split("\n  tofu:\n", 1)[1]
        self.assertIn(" trivy\n", job.split("bash scripts/install_tofu_tools.sh", 1)[1].split("\n", 1)[0] + "\n")
        self.assertIn("bash scripts/check_tofu.sh iac\n", job)


class EndToEndWorkflowPinsTest(unittest.TestCase):
    def test_go_task_download_matches_the_toolchain(self):
        workflow = read(".github/workflows/e2e-local.yml")
        pin = binaries()["go-task"]
        self.assertIn(f"TASK_VERSION: {pin['version']}\n", workflow)
        self.assertIn(f"TASK_SHA256: {pin['sha256']}\n", workflow)
        self.assertIn(pin["file"], workflow)

    def test_prometheus_pin_matches_the_toolchain(self):
        monitoring = read("ansible/inventories/local/group_vars/monitoring.yml")
        version = re.search(r"(?m)^prometheus_version: (\S+)$", monitoring).group(1)
        sha256 = re.search(r"(?m)^site_prometheus_sha256: ([0-9a-f]{64})$", monitoring).group(1)
        toolchain = read("docs/toolchain.md")
        self.assertIn(f"`prometheus-{version}.linux-amd64.tar.gz` | `{sha256}`", toolchain)


class PythonPinsTest(unittest.TestCase):
    def test_compiled_file_has_a_hash_for_every_requirement(self):
        text = read("requirements-test.txt")
        blocks = re.split(r"\n(?=[A-Za-z0-9])", text.split("\n", 1)[1])
        pinned = [b for b in blocks if PIN_RE.match(b)]
        self.assertGreater(len(pinned), 10)
        for block in pinned:
            with self.subTest(requirement=block.split()[0]):
                self.assertRegex(block, r"--hash=sha256:[0-9a-f]{64}")
        unpinned = [line for line in text.splitlines()
                    if line and not line[0].isspace() and not line.startswith("#") and not PIN_RE.match(line)]
        self.assertEqual(unpinned, [])

    def test_top_level_pins_are_compiled_and_documented(self):
        top = requirement_pins("requirements-test.in")
        compiled = requirement_pins("requirements-test.txt")
        documented = python_packages()
        self.assertTrue({"ansible-core", "ansible-lint", "molecule", "molecule-plugins"} <= set(top), top)
        for name, version in top.items():
            with self.subTest(package=name):
                self.assertEqual(compiled.get(name), version)
                self.assertIn("requirements-test.in", documented.get(name, ""))

    def test_dev_tools_are_documented(self):
        dev = requirement_pins("requirements-dev.txt")
        documented = python_packages()
        for name in ("yamllint", "zizmor"):
            with self.subTest(package=name):
                self.assertIn(name, dev)
                self.assertIn("requirements-dev.txt", documented.get(name, ""))

    def test_docs_repeat_no_version_of_a_requirements_file(self):
        """Dependabot changes only the requirements files; a copied version would go stale."""
        doc_rows = [row for row in table_rows(read("docs/toolchain.md"), "Package")
                    if "requirements-" in row[1]]
        self.assertGreaterEqual(len(doc_rows), 6)
        readme_rows = table_rows(read("README.md"), "Component")
        pins = {**requirement_pins("requirements-dev.txt"), **requirement_pins("requirements-test.in")}
        for row in doc_rows + readme_rows:
            with self.subTest(row=row[0]):
                cells = " ".join(row)
                for name, version in pins.items():
                    self.assertNotRegex(cells, rf"(?<![\d.]){re.escape(version)}(?![\d.])", name)

    def test_compile_tools_agree(self):
        command = re.search(r"pip install --quiet (pip-tools==\S+) (click==\S+) &&", read("docs/toolchain.md"))
        self.assertIsNotNone(command)
        documented = python_packages()
        header = read("requirements-test.in")
        for pin in command.groups():
            name, version = pin.split("==")
            with self.subTest(package=name):
                self.assertIn(pin, documented.get(name, ""))
                self.assertRegex(header, rf"\b{re.escape(name)} {re.escape(version)}\b")

    def test_shared_dependencies_agree(self):
        """Both files are installed into one environment by "task venv"."""
        dev, test = requirement_pins("requirements-dev.txt"), requirement_pins("requirements-test.txt")
        for name in sorted(set(dev) & set(test)):
            with self.subTest(package=name):
                self.assertEqual(dev[name], test[name])

    @unittest.skipUnless(os.environ.get("REQUIREMENTS_TEST_INSTALLED") == "1",
                         "runs inside scripts/run_tests.sh, after requirements-test.txt is installed")
    def test_installed_versions_match_the_pins(self):
        for name, version in requirement_pins("requirements-test.txt").items():
            with self.subTest(package=name):
                self.assertEqual(importlib.metadata.version(name), version)


if __name__ == "__main__":
    unittest.main()
