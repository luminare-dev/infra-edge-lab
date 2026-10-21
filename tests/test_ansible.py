"""Conventions of the Ansible part of this repository: the roles in ansible/roles, their variable
documentation, the shared Molecule configuration and its CI matrix, ansible/requirements.yml,
ansible/ansible.cfg, the firewall drop-ins and the pinned downloads.

The YAML checks need PyYAML (requirements-test.txt, which scripts/run_tests.sh installs); without
it they are skipped. The comparison with the bundled collections runs only inside
scripts/run_tests.sh, after requirements-test.txt is installed.
"""

from __future__ import annotations

import configparser
import importlib.metadata
import json
import os
import re
import unittest
from pathlib import Path

try:
    import yaml

    import role_docs
except ImportError:  # pragma: no cover - only without the test requirements
    yaml = None
    role_docs = None

ROOT = Path(__file__).resolve().parent.parent
ROLES = ROOT / "ansible" / "roles"
EXPECTED_ROLES = ["deploy_target", "docker", "monitoring"]
# Roles that live in the luminare collections; this repository keeps no copy of them.
COLLECTION_ROLES = ("base", "cloudflared", "nginx", "mariadb", "restic_backup", "fxserver", "txadmin",
                    "gameserver_observability")
INSTANCE_PREFIX = "lab-"
PLATFORM_NAME_RE = re.compile(r"lab-\$\{MOLECULE_ROLE:-role\}-([a-z0-9]+)")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def load_yaml(rel: str):
    return yaml.safe_load(read(rel))


def role_dirs() -> list[Path]:
    return [d for d in sorted(ROLES.iterdir()) if d.is_dir() and not d.name.startswith((".", "__"))]


class RoleLayoutTest(unittest.TestCase):
    def test_the_roles_of_this_repository(self):
        self.assertEqual([d.name for d in role_dirs()], EXPECTED_ROLES)

    def test_no_copy_of_a_collection_role(self):
        for name in COLLECTION_ROLES:
            with self.subTest(role=name):
                self.assertFalse((ROLES / name).exists(), f"{name} belongs to a luminare collection")

    def test_every_role_has_its_files_and_a_molecule_scenario(self):
        """CI tests only the roles with a scenario, so a role without one would go untested."""
        for role in role_dirs():
            for rel in ("README.md", "defaults/main.yml", "meta/argument_specs.yml", "tasks/main.yml",
                        "handlers/main.yml", "molecule/default/molecule.yml", "molecule/default/converge.yml",
                        "molecule/default/verify.yml"):
                with self.subTest(role=role.name, file=rel):
                    self.assertTrue((role / rel).is_file())


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class ArgumentSpecsTest(unittest.TestCase):
    def test_every_role_has_argument_specs(self):
        self.assertEqual([d.name for d in role_dirs()], role_docs.role_names())

    def test_defaults_match_argument_specs(self):
        for role in role_docs.role_names():
            with self.subTest(role=role):
                options = role_docs.load_options(role)
                defaults = yaml.safe_load((ROLES / role / "defaults" / "main.yml").read_text(encoding="utf-8"))
                self.assertEqual(sorted(defaults), sorted(options),
                                 "defaults/main.yml and argument_specs.yml list different variables")
                for name, spec in options.items():
                    self.assertTrue(name.startswith(f"{role}_"), f"{name}: variables start with the role name")
                    self.assertIn("default", spec, f"{name}: argument_specs.yml has no default")
                    self.assertEqual(spec["default"], defaults[name], f"{name}: defaults differ")
                    self.assertTrue(role_docs.render_description(spec), f"{name}: no description")
                    if "choices" in spec:
                        self.assertIn(defaults[name], spec["choices"], f"{name}: default is not one of the choices")

    def test_internal_variables_keep_the_role_prefix(self):
        for role in role_docs.role_names():
            internal = yaml.safe_load((ROLES / role / "vars" / "main.yml").read_text(encoding="utf-8")) or {}
            for name in internal:
                with self.subTest(role=role, variable=name):
                    self.assertTrue(name.startswith(f"__{role}_"), name)

    def test_variable_tables_are_generated(self):
        for path in role_docs.doc_files():
            with self.subTest(file=str(path.relative_to(ROOT))):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(text, role_docs.render_file(text), "run: python3 tests/role_docs.py --write")

    def test_every_role_readme_and_the_configuration_page_have_a_table(self):
        configuration = read("docs/configuration.md")
        for role in role_docs.role_names():
            with self.subTest(role=role):
                marker = f"<!-- argument-specs:{role}:begin -->"
                self.assertIn(marker, (ROLES / role / "README.md").read_text(encoding="utf-8"))
                self.assertIn(marker, configuration)


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class SecureDefaultsTest(unittest.TestCase):
    """The defaults that the contract of this repository fixes (loopback binding, game server
    user, write-only uploads); a change must be deliberate."""

    def defaults(self, role: str) -> dict:
        return yaml.safe_load((ROLES / role / "defaults" / "main.yml").read_text(encoding="utf-8"))

    def test_docker(self):
        d = self.defaults("docker")
        self.assertEqual(d["docker_default_bind_ip"], "127.0.0.1")
        self.assertIn("fxserver", d["docker_forbidden_groups"])
        self.assertEqual(d["docker_users"], [])
        self.assertRegex(d["docker_apt_key_checksum"], r"^sha256:[0-9a-f]{64}$")

    def test_monitoring(self):
        d = self.defaults("monitoring")
        self.assertEqual(d["monitoring_node_exporter_listen_address"], "127.0.0.1")
        self.assertEqual(d["monitoring_node_exporter_port"], 9100)
        self.assertEqual(d["monitoring_uptime_kuma_bind_address"], "127.0.0.1")
        self.assertRegex(d["monitoring_uptime_kuma_image"], r"@sha256:[0-9a-f]{64}$")
        self.assertEqual(sorted(d["monitoring_node_exporter_checksums"]), ["amd64", "arm64"])
        for value in d["monitoring_node_exporter_checksums"].values():
            self.assertRegex(value, SHA256_RE)

    def test_deploy_target(self):
        d = self.defaults("deploy_target")
        self.assertEqual((d["deploy_target_run_user"], d["deploy_target_run_group"]), ("fxserver", "fxserver"))
        self.assertEqual(d["deploy_target_rrsync_options"], ["-wo", "-no-del"])
        self.assertEqual(d["deploy_target_spool_dir"], "/srv/luminare/incoming")
        self.assertEqual(d["deploy_target_release_root"], "/opt/fxserver/releases")

    def test_deploy_units_and_key_options(self):
        path_unit = read("ansible/roles/deploy_target/templates/luminare-deploy.path.j2")
        self.assertIn("PathExistsGlob={{ deploy_target_spool_dir }}/*.ready", path_unit)
        self.assertNotIn("PathChanged", path_unit)
        service = read("ansible/roles/deploy_target/templates/luminare-deploy.service.j2")
        self.assertIn("User={{ deploy_target_run_user }}", service)
        self.assertIn("NoNewPrivileges=yes", service)
        keys = read("ansible/roles/deploy_target/templates/authorized_keys.j2")
        self.assertRegex(keys, r'(?m)^restrict,.*command="\{\{ __deploy_target_forced_command \}\}" ')
        tasks = read("ansible/roles/deploy_target/tasks/account.yml") + read(
            "ansible/roles/deploy_target/tasks/directories.yml")
        self.assertIn("shell: /bin/sh", tasks)
        self.assertIn('mode: "2770"', tasks)


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class PrivateAddressPatternTest(unittest.TestCase):
    """The address check of the docker and monitoring roles (Jinja's "match" test uses Python's
    re.match, so the pattern behaves the same here)."""

    @classmethod
    def setUpClass(cls):
        cls.patterns = {
            role: yaml.safe_load((ROLES / role / "vars" / "main.yml").read_text(encoding="utf-8"))[
                f"__{role}_private_address_re"]
            for role in ("docker", "monitoring")
        }

    @staticmethod
    def dotted(*parts: int) -> str:
        # Private addresses are built from numbers, so that no RFC 1918 literal is written into
        # the repository (only documentation ranges and loopback appear as text).
        return ".".join(str(p) for p in parts)

    def test_both_roles_use_the_same_pattern(self):
        self.assertEqual(self.patterns["docker"], self.patterns["monitoring"])

    def test_accepts_loopback_and_private_addresses(self):
        pattern = self.patterns["docker"]
        for address in ("127.0.0.1", self.dotted(127, 0, 1, 1), "::1", self.dotted(10, 0, 0, 5),
                        self.dotted(172, 16, 0, 1), self.dotted(172, 31, 255, 254), self.dotted(192, 168, 1, 10),
                        self.dotted(100, 64, 0, 1), self.dotted(100, 127, 255, 1), "fd00::1", "fc12:3456::9"):
            with self.subTest(address=address):
                self.assertTrue(re.match(pattern, address))

    def test_refuses_wildcards_and_public_addresses(self):
        pattern = self.patterns["docker"]
        for address in ("0.0.0.0", "::", "", "192.0.2.10", "198.51.100.7", "203.0.113.1", "2001:db8::1",
                        self.dotted(172, 15, 0, 1), self.dotted(172, 32, 0, 1), self.dotted(100, 63, 0, 1),
                        self.dotted(100, 128, 0, 1), self.dotted(11, 0, 0, 1), "fe80::1", "localhost",
                        "127.0.0.1:9100", "127.0.0.1 "):
            with self.subTest(address=address):
                self.assertIsNone(re.match(pattern, address))


class FirewallDropInTest(unittest.TestCase):
    """Drop-ins of /etc/nftables.d hold accept rules only (the base ruleset drops by default)."""

    TEMPLATES = {
        "ansible/roles/docker/templates/60-docker.nft.j2": "forward",
        "ansible/roles/monitoring/templates/50-monitoring.nft.j2": "input",
    }

    def test_only_accept_rules(self):
        for rel, chain in self.TEMPLATES.items():
            rules = [ln for ln in read(rel).splitlines() if ln.strip() and not ln.startswith(("#", "{%"))]
            with self.subTest(file=rel):
                self.assertTrue(rules)
                for line in rules:
                    self.assertRegex(line, rf"^add rule inet filter {chain} .* accept$")
                    self.assertNotIn(" drop", line)

    def test_drop_ins_are_validated_with_the_whole_ruleset(self):
        for rel in ("ansible/roles/docker/tasks/firewall.yml", "ansible/roles/monitoring/tasks/firewall.yml"):
            with self.subTest(file=rel):
                self.assertIn("cat /etc/nftables.conf %s | nft --check --file /dev/stdin", read(rel))


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class MoleculeConfigTest(unittest.TestCase):
    def test_platforms(self):
        cfg = load_yaml(".config/molecule/config.yml")
        self.assertEqual(cfg["driver"]["name"], "docker")
        self.assertFalse(cfg["dependency"].get("enabled", True), "collections come from requirements-test.txt")
        platforms = cfg["platforms"]
        self.assertEqual([p["image"] for p in platforms], ["lab-molecule-debian13", "lab-molecule-ubuntu2404"])
        stages = re.findall(r"(?m)^FROM \S+@sha256:[0-9a-f]{64} AS (\S+)$", read("images/systemd-host/Dockerfile"))
        self.assertEqual(stages, ["debian13", "ubuntu2404"])
        for p, stage in zip(platforms, stages):
            with self.subTest(platform=p["name"]):
                self.assertTrue(p["name"].startswith(INSTANCE_PREFIX), p["name"])
                self.assertEqual(p["buildargs"], {"BASE": stage})
                self.assertFalse(p["pre_build_image"])
                self.assertTrue(p["privileged"])
                self.assertEqual(p["cgroupns_mode"], "host")
                self.assertEqual(p["volumes"], ["/sys/fs/cgroup:/sys/fs/cgroup:rw"])
                self.assertEqual(p["tmpfs"][:2], ["/run", "/run/lock"])
                self.assertEqual(p["command"], "/lib/systemd/systemd")
                scenario_dir = ROLES / "role" / "molecule" / "default"
                self.assertEqual((scenario_dir / p["dockerfile"]).resolve(),
                                 ROOT / "images" / "systemd-host" / "Dockerfile")

    def test_test_sequence(self):
        sequence = load_yaml(".config/molecule/config.yml")["scenario"]["test_sequence"]
        self.assertEqual(sequence, ["dependency", "destroy", "syntax", "create", "prepare", "converge",
                                    "idempotence", "verify", "destroy"])

    def test_scenarios_keep_the_shared_platforms(self):
        for scenario in sorted(ROLES.glob("*/molecule/*/molecule.yml")):
            data = yaml.safe_load(scenario.read_text(encoding="utf-8")) or {}
            with self.subTest(scenario=str(scenario.relative_to(ROOT))):
                self.assertNotIn("platforms", data)
                self.assertNotIn("driver", data)

    def test_ci_matrix_is_role_by_platform(self):
        """ci.yml runs one job per role and platform; its platforms are exactly those of config.yml."""
        suffixes = []
        for p in load_yaml(".config/molecule/config.yml")["platforms"]:
            match = PLATFORM_NAME_RE.fullmatch(p["name"])
            self.assertIsNotNone(match, p["name"])
            suffixes.append(match.group(1))
            self.assertEqual(p["image"], f"lab-molecule-{match.group(1)}")
        workflow = load_yaml(".github/workflows/ci.yml")
        jobs = workflow["jobs"]
        job = jobs["molecule-scenario"]
        matrix = job["strategy"]["matrix"]
        self.assertEqual(sorted(matrix), ["platform", "role"])
        self.assertEqual(matrix["platform"], suffixes)
        self.assertEqual(job["name"], "molecule-scenario (${{ matrix.role }}, ${{ matrix.platform }})")
        step = next(s for s in job["steps"] if "molecule test" in s.get("run", ""))
        self.assertEqual(step["working-directory"], "ansible/roles/${{ matrix.role }}")
        self.assertEqual(step["env"]["MOLECULE_ROLE"], "${{ matrix.role }}")
        self.assertEqual(step["env"]["PLATFORM"], "${{ matrix.platform }}")
        self.assertEqual(step["run"].strip(), 'molecule test --platform-name "lab-${MOLECULE_ROLE}-${PLATFORM}"')
        self.assertIn("ansible/roles/*/molecule/default/molecule.yml", jobs["plan"]["steps"][1]["run"])
        self.assertEqual(jobs["molecule"]["name"], "molecule")
        self.assertEqual(jobs["molecule"]["needs"], ["plan", "molecule-scenario"])
        # PyYAML reads the key "on" as True.
        triggers = workflow.get("on", workflow.get(True))
        for event in ("pull_request", "workflow_dispatch", "schedule"):
            self.assertIn(event, triggers)


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class RequirementsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.collections = load_yaml("ansible/requirements.yml")["collections"]

    def test_luminare_collections_come_from_git_tags(self):
        luminare = {c["name"]: c for c in self.collections if c["name"].startswith("luminare.")}
        self.assertEqual(sorted(luminare), ["luminare.gameserver", "luminare.infra_edge"])
        for name, entry in luminare.items():
            with self.subTest(collection=name):
                slug = "ansible-collection-" + name.split(".", 1)[1]
                self.assertEqual(entry["type"], "git")
                self.assertEqual(entry["source"], f"https://github.com/luminare-dev/{slug}.git")
                self.assertRegex(entry["version"], r"^v\d+\.\d+\.\d+$")

    def test_community_collections_are_pinned(self):
        for entry in self.collections:
            if entry["name"].startswith("luminare."):
                continue
            with self.subTest(collection=entry["name"]):
                self.assertNotIn("type", entry)
                self.assertNotIn("source", entry)
                self.assertRegex(str(entry["version"]), r"^\d+\.\d+\.\d+$")

    def test_the_roles_find_their_collections(self):
        names = {c["name"] for c in self.collections}
        self.assertIn("community.docker", names)  # monitoring: Uptime Kuma container
        self.assertIn("community.sops", names)    # ansible.cfg: SOPS vars plugin
        used = set(re.findall(r"\b(community\.[a-z_]+|ansible\.(?:posix|utils|mariadb))\.[a-z_]+:",
                              "".join(p.read_text(encoding="utf-8") for p in ROLES.glob("*/tasks/*.yml"))))
        self.assertTrue(used <= names, used - names)

    @unittest.skipUnless(os.environ.get("REQUIREMENTS_TEST_INSTALLED") == "1",
                         "runs inside scripts/run_tests.sh, after requirements-test.txt is installed")
    def test_pins_equal_the_collections_that_lint_and_molecule_use(self):
        dist = importlib.metadata.distribution("ansible")
        checked = 0
        for entry in self.collections:
            namespace, name = entry["name"].split(".", 1)
            manifest = Path(dist.locate_file(f"ansible_collections/{namespace}/{name}/MANIFEST.json"))
            if entry["name"].startswith("luminare.") or not manifest.is_file():
                continue
            with self.subTest(collection=entry["name"]):
                bundled = json.loads(manifest.read_text(encoding="utf-8"))["collection_info"]["version"]
                self.assertEqual(str(entry["version"]), bundled)
                checked += 1
        self.assertGreaterEqual(checked, 4)


class AnsibleConfigTest(unittest.TestCase):
    def test_settings(self):
        cfg = configparser.ConfigParser()
        cfg.read_string(read("ansible/ansible.cfg"))
        defaults = cfg["defaults"]
        self.assertEqual(defaults["roles_path"], "roles")
        self.assertEqual(defaults["collections_path"], "collections")
        self.assertEqual(defaults["vars_plugins_enabled"].split(","), ["host_group_vars", "community.sops.sops"])
        self.assertEqual(cfg["ssh_connection"]["pipelining"], "true")

    def test_installed_collections_are_ignored(self):
        self.assertIn("ansible/collections/", read(".gitignore").splitlines())
        self.assertIn("ansible/collections/", read(".yamllint.yml"))
        self.assertIn("ansible/collections/", read(".ansible-lint"))


class PinnedDownloadsTest(unittest.TestCase):
    """docs/toolchain.md lists what the roles download; the values must be the ones in the roles."""

    def test_toolchain_page_names_the_role_pins(self):
        toolchain = read("docs/toolchain.md")
        for rel in ("ansible/roles/monitoring/defaults/main.yml", "ansible/roles/docker/defaults/main.yml"):
            text = read(rel)
            for value in re.findall(r"[0-9a-f]{64}", text):
                with self.subTest(file=rel, value=value[:12]):
                    self.assertIn(value, toolchain)
        self.assertIn("node_exporter-1.12.1.linux-amd64.tar.gz", toolchain)
        self.assertIn('"1.12.1"', read("ansible/roles/monitoring/defaults/main.yml"))


if __name__ == "__main__":
    unittest.main()
