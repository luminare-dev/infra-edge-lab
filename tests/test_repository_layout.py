"""Repository conventions of infra-edge-lab: layout, ignored files, secrets folder, Dependabot,
the shared test command and the collection tags in the README.

Standard library only, like the template's tests, so they run on any python3 >= 3.10.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONVENTIONAL_PREFIXES = {"build", "ci", "chore", "test"}


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def in_git_work_tree() -> bool:
    if not shutil.which("git"):
        return False
    out = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT,
                         capture_output=True, text=True)
    return out.returncode == 0 and out.stdout.strip() == "true"


class LayoutTest(unittest.TestCase):
    def test_top_level_folders_exist(self):
        for rel in ("tofu/modules", "tofu/envs", "ansible/playbooks", "ansible/inventories",
                    "ansible/roles", "secrets", "scripts"):
            with self.subTest(folder=rel):
                self.assertTrue((ROOT / rel).is_dir())

    def test_template_only_files_are_gone(self):
        for rel in ("PUBLISHING.md", "PLACEHOLDERS.md", "licenses"):
            with self.subTest(path=rel):
                self.assertFalse((ROOT / rel).exists())


@unittest.skipUnless(in_git_work_tree(), "needs git and a work tree")
class GitignoreTest(unittest.TestCase):
    IGNORED = (
        "tofu/envs/lab/.terraform/providers/x",
        "tofu/envs/lab/terraform.tfstate",
        "tofu/envs/lab/terraform.tfstate.backup",
        "tofu/envs/lab/tfplan",
        "tofu/envs/lab/lab.tfplan",
        "tofu/envs/lab/backend_override.tf",
        "tofu/envs/lab/override.tofu",
        "tofu/envs/lab/terraform.tfvars",
        "tofu/envs/lab/lab.auto.tfvars",
        "tofu/envs/demo/demo.auto.tfvars.json",
        "ansible/inventories/lab/hosts.yml",
        "ansible/inventories/local/hosts.yml",
        "ansible/inventories/local/.generated/perf_password",
        "ansible/inventories/local/.generated/fake-artifact/35245/fx.tar.xz",
        "ansible/collections/ansible_collections/community/docker/MANIFEST.json",
        "secrets/lab.env",
        "secrets/lab.enc.env.bak",
        "group_vars/all.dec.yaml",
        ".task/checksum/venv",
        ".venv/bin/python",
        "backups/dns/20261022T103000Z.zone.age",
        "ansible/inventories/demo/.generated/restic_password",
    )
    KEPT = (
        "tofu/envs/lab/main.tf",
        "tofu/envs/lab/encryption.tofu",
        "tofu/envs/lab/.terraform.lock.hcl",
        "ansible/inventories/lab/group_vars/all.sops.yaml",
        "ansible/inventories/local/group_vars/all.yml",
        "ansible/playbooks/site.yml",
        "tests/fake-artifact/build.py",
        "ansible/requirements.yml",
        "ansible/ansible.cfg",
        "ansible/roles/docker/tasks/main.yml",
        ".sops.yaml",
        "secrets/lab.enc.env",
        "secrets/lab-ci.enc.env",
        "secrets/demo-e2e.enc.env",
        "ansible/inventories/demo/group_vars/all.yml",
        "secrets/README.md",
        "secrets/env.example",
    )

    def ignored(self, rel: str) -> bool:
        return subprocess.run(["git", "check-ignore", "-q", "--no-index", rel], cwd=ROOT).returncode == 0

    def test_generated_and_secret_files_are_ignored(self):
        for rel in self.IGNORED:
            with self.subTest(path=rel):
                self.assertTrue(self.ignored(rel))

    def test_code_lock_files_and_encrypted_files_are_kept(self):
        for rel in self.KEPT:
            with self.subTest(path=rel):
                self.assertFalse(self.ignored(rel))


def secrets_files() -> list[Path]:
    """Files in secrets/ that can be committed.

    In a git work tree these are the tracked files plus the untracked ones that .gitignore does
    not ignore, so an ignored local file (secrets/lab.env, an editor backup) is not reported.
    Without git, every file in the folder counts.
    """
    if in_git_work_tree():
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                              "--", "secrets/"], cwd=ROOT, capture_output=True, text=True, check=True)
        paths = {ROOT / rel for rel in out.stdout.split("\0") if rel}
    else:
        paths = {path for path in (ROOT / "secrets").rglob("*") if not path.is_dir()}
    return sorted(path for path in paths if path.is_file())


class SecretsFolderTest(unittest.TestCase):
    def test_only_readme_examples_and_encrypted_files(self):
        files = secrets_files()
        self.assertIn(ROOT / "secrets" / "README.md", files)
        for path in files:
            rel = path.relative_to(ROOT / "secrets").as_posix()
            with self.subTest(file=rel):
                self.assertTrue(rel == "README.md" or ("/" not in rel and rel.endswith((".example", ".enc.env"))),
                                rel)

    def test_examples_hold_no_values(self):
        for path in (p for p in secrets_files() if p.name.endswith(".example")):
            for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line and not line.startswith("#"):
                    with self.subTest(file=path.name, line=no):
                        self.assertRegex(line, r"^[A-Za-z_][A-Za-z0-9_]*=$")

    def test_encrypted_files_hold_only_encrypted_values(self):
        for path in (p for p in secrets_files() if p.name.endswith(".enc.env")):
            lines = [line for line in path.read_text(encoding="utf-8").splitlines()
                     if line and not line.startswith("#")]
            with self.subTest(file=path.name):
                self.assertTrue(any(line.startswith("sops_mac=") for line in lines), "no SOPS metadata")
                for line in lines:
                    key, _, value = line.partition("=")
                    if not key.startswith("sops_"):
                        self.assertTrue(value.startswith("ENC["), f"{key} is not encrypted")


class DependabotTest(unittest.TestCase):
    def blocks(self) -> list[str]:
        return re.split(r"\n(?=  - package-ecosystem:)", read(".github/dependabot.yml"))[1:]

    def test_every_ecosystem_passes_the_pr_title_check(self):
        blocks = self.blocks()
        self.assertGreaterEqual(len(blocks), 3)
        for block in blocks:
            ecosystem = re.search(r"package-ecosystem:\s*(\S+)", block).group(1)
            with self.subTest(ecosystem=ecosystem):
                prefix = re.search(r"\n\s+prefix:\s*(\S+)", block)
                self.assertIsNotNone(prefix)
                self.assertIn(prefix.group(1), CONVENTIONAL_PREFIXES)
                self.assertRegex(block, r"\n\s+include:\s*scope\b")
                self.assertRegex(block, r"\n\s+labels:\s*\[dependencies\]")
                self.assertRegex(block, r"\n\s+default-days:\s*\d+")

    def test_every_module_and_environment_is_watched(self):
        tofu = [b for b in self.blocks() if re.search(r"package-ecosystem:\s*opentofu\b", b)]
        self.assertEqual(len(tofu), 1)
        for pattern in ("/tofu/modules/*", "/tofu/envs/*"):
            self.assertIn(f"- {pattern}\n", tofu[0] + "\n")

    def test_python_requirements_are_watched(self):
        pip = [b for b in self.blocks() if re.search(r"package-ecosystem:\s*pip\b", b)]
        self.assertEqual(len(pip), 1)
        self.assertRegex(pip[0], r"directory:\s*/\n")
        self.assertTrue((ROOT / "requirements-test.in").is_file(), "Dependabot recompiles from the .in file")


class TestCommandTest(unittest.TestCase):
    def test_ci_and_release_run_the_same_test_command(self):
        commands = []
        for rel in (".github/workflows/ci.yml", ".github/workflows/release.yml"):
            m = re.search(r"^\s+test-command:\s*(.+)$", read(rel), re.MULTILINE)
            self.assertIsNotNone(m, rel)
            commands.append(m.group(1).strip())
        self.assertEqual(commands, ["bash scripts/run_tests.sh"] * 2)

    def test_runner_installs_hash_pinned_wheels_only(self):
        script = read("scripts/run_tests.sh")
        self.assertIn("--require-hashes --only-binary=:all: -r requirements-test.txt", script)
        self.assertTrue(os.access(ROOT / "scripts" / "run_tests.sh", os.X_OK))

    def test_taskfile_has_lint_and_test(self):
        taskfile = read("Taskfile.yml")
        for task in ("venv", "lint", "test"):
            with self.subTest(task=task):
                self.assertRegex(taskfile, rf"\n  {task}:\n    desc: ")
        self.assertIn("bash scripts/run_tests.sh", taskfile)


class PreCommitTest(unittest.TestCase):
    """.pre-commit-config.yaml: hooks of other repositories pinned to a commit, the expected checks."""

    def repos(self) -> list[tuple[str, str]]:
        """(repo, rev line) of every repository block."""
        return re.findall(r"(?m)^  - repo: (\S+)\n(?:    rev: (.+)\n)?", read(".pre-commit-config.yaml"))

    def test_other_repositories_are_pinned_to_a_commit_with_its_tag(self):
        remote = [(repo, rev) for repo, rev in self.repos() if repo != "local"]
        self.assertGreaterEqual(len(remote), 3)
        for repo, rev in remote:
            with self.subTest(repo=repo):
                self.assertTrue(repo.startswith("https://github.com/"), repo)
                self.assertRegex(rev, r"^[0-9a-f]{40}  # frozen: v\d+(\.\d+)+$")

    def test_hooks_cover_the_hygiene_checks(self):
        text = read(".pre-commit-config.yaml")
        hooks = set(re.findall(r"(?m)^      - id: (\S+)$", text))
        expected = {"end-of-file-fixer", "trailing-whitespace", "shellcheck", "gitleaks-system", "yamllint",
                    "sops-encrypted", "tofu-fmt", "tflint", "ansible-lint"}
        self.assertLessEqual(expected, hooks)
        self.assertIn("sops filestatus", text)
        self.assertIn(r"files: ^secrets/.*\.enc\.env$", text)
        self.assertRegex(text, r"(?m)^      - id: gitleaks-system\n        pass_filenames: false$")


def luminare_collections() -> dict[str, tuple[str, str]]:
    """Name -> (type, version) of the luminare collections in ansible/requirements.yml."""
    found = {}
    for block in re.split(r"\n(?=  - name: )", read("ansible/requirements.yml")):
        name = re.search(r"^  - name: (luminare\.\w+)$", block, re.MULTILINE)
        if name:
            kind = re.search(r"^    type: (\S+)$", block, re.MULTILINE)
            version = re.search(r"^    version: (\S+)$", block, re.MULTILINE)
            found[name.group(1)] = (kind.group(1) if kind else "", version.group(1) if version else "")
    return found


def readme_component_rows() -> dict[str, list[str]]:
    """First cell (without backquotes) -> cells of the README's "Supported versions" table."""
    rows, inside = {}, False
    for line in read("README.md").splitlines():
        if line.startswith("| Component |"):
            inside = True
            continue
        if inside:
            if not line.startswith("|"):
                break
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            rows[cells[0].strip("`")] = cells
    return rows


class CollectionTagsTest(unittest.TestCase):
    """The luminare collections come from git tags, and the README names the pinned tags."""

    def test_luminare_collections_are_pinned_to_release_tags(self):
        collections = luminare_collections()
        self.assertEqual(sorted(collections), ["luminare.gameserver", "luminare.infra_edge"])
        for name, (kind, version) in collections.items():
            with self.subTest(collection=name):
                self.assertEqual(kind, "git")
                self.assertRegex(version, r"^v\d+\.\d+\.\d+$")

    def test_readme_names_the_pinned_tags(self):
        rows = readme_component_rows()
        for name, (_, version) in luminare_collections().items():
            with self.subTest(collection=name):
                self.assertIn(name, rows, "a row of the Supported versions table")
                self.assertTrue(rows[name][1].startswith(f"`{version}`"), rows[name][1])


if __name__ == "__main__":
    unittest.main()
