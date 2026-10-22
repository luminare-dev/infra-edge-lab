"""Conventions of the playbooks in ansible/playbooks and the local inventory.

playbooks/site.yml is the one playbook of every environment; these tests pin its shape (which
group gets which role, in which order), that every role it names is either in ansible/roles or in
a collection of ansible/requirements.yml and mocked for the offline ansible-lint, that the local
environment's group_vars hold no secret and no real server build, and that the e2e workflow runs
"task e2e:local" without secrets. The run itself is task e2e:local. The YAML checks need PyYAML
(requirements-test.txt); without it they are skipped.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - only without the test requirements
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
PLAYBOOKS = ROOT / "ansible" / "playbooks"
LOCAL_VARS = ROOT / "ansible" / "inventories" / "local" / "group_vars"


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def load(rel: str):
    return yaml.safe_load(read(rel))


def role_name(entry) -> str:
    return entry if isinstance(entry, str) else entry["role"]


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class SitePlaybookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plays = load("ansible/playbooks/site.yml")
        cls.order = [(play["hosts"], [role_name(r) for r in play.get("roles", [])]) for play in cls.plays]

    def test_plays_and_roles_in_order(self):
        self.assertEqual(self.order, [
            ("all", ["luminare.infra_edge.base"]),
            ("monitoring:docker_hosts", ["docker"]),
            ("all", ["monitoring"]),
            ("edge", ["luminare.infra_edge.cloudflared", "luminare.infra_edge.nginx"]),
            ("db", ["luminare.infra_edge.mariadb"]),
            ("fxserver", ["luminare.gameserver.fxserver", "luminare.gameserver.txadmin", "deploy_target"]),
            ("monitoring", ["prometheus.prometheus.prometheus", "luminare.gameserver.gameserver_observability"]),
            ("all", ["luminare.infra_edge.restic_backup"]),
        ])

    def test_every_play_becomes_root_and_gathers_facts(self):
        for play in self.plays:
            with self.subTest(play=play["name"]):
                self.assertIs(play["become"], True)
                self.assertIs(play["gather_facts"], True)

    def test_tunnel_connector_only_with_a_token(self):
        edge = next(p for p in self.plays if p["hosts"] == "edge")
        cloudflared = next(r for r in edge["roles"] if role_name(r) == "luminare.infra_edge.cloudflared")
        self.assertIn("TUNNEL_TOKEN", cloudflared["when"])
        self.assertIn("| length > 0", cloudflared["when"])

    def test_game_servers_one_at_a_time(self):
        play = next(p for p in self.plays if p["hosts"] == "fxserver")
        self.assertEqual((play["serial"], play["max_fail_percentage"]), (1, 0))
        txadmin = next(r for r in play["roles"] if role_name(r) == "luminare.gameserver.txadmin")
        self.assertIn("fxserver_mode", txadmin["when"])

    def test_prometheus_never_listens_on_a_public_address(self):
        """The prometheus role's default is 0.0.0.0:9090; site.yml refuses any public address."""
        play = next(p for p in self.plays if p["hosts"] == "monitoring")
        role_pattern = yaml.safe_load(read("ansible/roles/monitoring/vars/main.yml"))["__monitoring_private_address_re"]
        self.assertEqual(play["vars"]["site_private_address_re"], role_pattern)
        check = play["pre_tasks"][0]["ansible.builtin.assert"]["that"]
        self.assertEqual(check, ["site_prometheus_listen_host is match(site_private_address_re)"])
        self.assertIn("default('0.0.0.0:9090')", play["vars"]["site_prometheus_listen_host"])
        self.assertEqual(play["roles"][0], {"role": "prometheus.prometheus.prometheus"})

    def test_prometheus_archive_is_checked_against_the_pin_before_the_role(self):
        """The pinned archive is downloaded into the role's cache and checked before the role runs."""
        play = next(p for p in self.plays if p["hosts"] == "monitoring")
        before = play["pre_tasks"][1]
        self.assertEqual(before["when"], "site_prometheus_sha256 | default('') | length > 0")
        download = before["block"][-1]["ansible.builtin.get_url"]
        self.assertEqual(download["checksum"], "sha256:{{ site_prometheus_sha256 }}")
        self.assertEqual(download["dest"],
                         "{{ prometheus_local_cache_path }}/prometheus-{{ prometheus_version }}.linux-amd64.tar.gz")
        self.assertIn("/releases/download/v{{ prometheus_version }}/prometheus-{{ prometheus_version }}.linux-amd64.tar.gz",
                      download["url"])
        self.assertEqual(before["block"][-1]["delegate_to"], "localhost")
        # After the role, the archive it unpacked is compared with the pin once more.
        after = yaml.safe_dump(play["post_tasks"])
        self.assertIn("site_prometheus_sha256", after)
        self.assertIn("checksum_algorithm: sha256", after)
        pinned = load("ansible/inventories/local/group_vars/monitoring.yml")
        self.assertRegex(pinned["site_prometheus_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("prometheus_local_cache_path", pinned)


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class RoleSourcesTest(unittest.TestCase):
    """Every role comes from ansible/roles or from a pinned collection, and lint mocks the latter."""

    @classmethod
    def setUpClass(cls):
        cls.used = set()
        for path in sorted(PLAYBOOKS.glob("*.yml")):
            for play in yaml.safe_load(path.read_text(encoding="utf-8")):
                cls.used |= {role_name(r) for r in play.get("roles", [])}
        cls.local = {d.name for d in (ROOT / "ansible" / "roles").iterdir() if d.is_dir()}
        cls.external = {r for r in cls.used if "." in r}

    def test_short_names_are_roles_of_this_repository(self):
        self.assertEqual(self.used - self.external, self.local)

    def test_collection_roles_are_pinned_in_requirements(self):
        pinned = {c["name"] for c in load("ansible/requirements.yml")["collections"]}
        for role in sorted(self.external):
            with self.subTest(role=role):
                self.assertIn(role.rsplit(".", 1)[0], pinned)

    def test_offline_lint_mocks_exactly_the_collection_roles(self):
        self.assertEqual(set(load(".ansible-lint")["mock_roles"]), self.external)

    def test_lint_finds_the_roles_of_this_repository(self):
        self.assertIn('ANSIBLE_ROLES_PATH="$PWD/ansible/roles" ansible-lint', read("scripts/run_tests.sh"))


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class LocalInventoryTest(unittest.TestCase):
    SECRET_NAME_RE = re.compile(r"(password|token|_key|secret|hash)$")

    @classmethod
    def setUpClass(cls):
        cls.vars = {}
        for path in sorted(LOCAL_VARS.glob("*.yml")):
            cls.vars.update(yaml.safe_load(path.read_text(encoding="utf-8")))

    def secrets(self) -> dict:
        found = {}

        def walk(name, value):
            if isinstance(value, dict):
                for key, item in value.items():
                    walk(f"{name}.{key}" if name else key, item)
            elif isinstance(value, list):
                for item in value:
                    walk(name, item)
            elif self.SECRET_NAME_RE.search(name.rsplit(".", 1)[-1]):
                found[name] = value

        walk("", self.vars)
        return found

    def test_every_secret_is_generated_or_taken_from_another_variable(self):
        secrets = self.secrets()
        self.assertGreaterEqual(len(secrets), 6, secrets)
        for name, value in secrets.items():
            with self.subTest(variable=name):
                self.assertIsInstance(value, str)
                self.assertTrue(value.strip().startswith("{{") and value.strip().endswith("}}"),
                                f"{name} holds a literal value")
                if "password" in name or "token" in name or "license" in name:
                    self.assertTrue("ansible.builtin.password" in value or re.fullmatch(r"\{\{ \w+ \}\}", value),
                                    f"{name} is neither generated nor another variable")

    def test_generated_files_stay_in_the_ignored_folder(self):
        self.assertEqual(self.vars["local_generated_dir"], "{{ inventory_dir }}/.generated")
        for path in sorted(LOCAL_VARS.glob("*.yml")):
            for lookup in re.findall(r"lookup\('ansible\.builtin\.(?:password|file)', ([^,)]+)", path.read_text(
                    encoding="utf-8")):
                with self.subTest(file=path.name, lookup=lookup):
                    self.assertTrue(lookup.startswith("local_generated_dir ~ '/"), lookup)
        self.assertIn("ansible/inventories/*/.generated/", read(".gitignore").splitlines())

    def test_fake_build_and_no_tunnel(self):
        self.assertTrue(self.vars["fxserver_artifact_url"].startswith("file:///"))
        self.assertNotIn("cloudflared_token", self.vars)
        self.assertEqual(self.vars["base_ssh_allow_mode"], "loopback")

    def test_node_targets_of_game_servers_carry_the_server_label(self):
        """The observability pack's host and build alerts name a game server by its server label."""
        node = next(job for job in self.vars["prometheus_scrape_configs"] if job["job_name"] == "node")
        self.assertEqual(node["static_configs"], "{{ local_node_static_configs }}")
        expression = self.vars["local_node_static_configs"]
        self.assertIn("reject('in', groups['fxserver'])", expression)
        self.assertIn("map('community.general.dict_kv', 'server')", expression)
        self.assertIn("map('community.general.dict_kv', 'labels')", expression)
        # The same label value as the observability jobs: the host name of the game server.
        self.assertIn("groups['fxserver'] | map('community.general.dict_kv', 'server')",
                      self.vars["gameserver_observability_targets"])

    def test_ports_stay_closed_to_everyone(self):
        self.assertEqual(self.vars["prometheus_web_listen_address"], "127.0.0.1:9090")
        self.assertIn("groups['edge']", self.vars["txadmin_firewall_sources"])
        self.assertIn("groups['monitoring']", self.vars["monitoring_node_exporter_allowed_sources"])
        self.assertIn("groups['fxserver']", self.vars["mariadb_allowed_app_hosts"])
        for site in self.vars["nginx_sites"]:
            with self.subTest(site=site["name"]):
                self.assertTrue(site["listen"].startswith("127.0.0.1:"))


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class RestoreTestPlaybookTest(unittest.TestCase):
    """playbooks/restore_test.yml: task restore-test and the last step of task e2e:local."""

    @classmethod
    def setUpClass(cls):
        cls.plays = load("ansible/playbooks/restore_test.yml")

    def test_restores_on_every_host_and_changes_nothing_by_default(self):
        self.assertEqual(len(self.plays), 1)
        play = self.plays[0]
        self.assertEqual((play["hosts"], play["become"]), ("all", True))
        self.assertIs(play["vars"]["restore_test_backup_now"], False)
        self.assertEqual(play["vars"]["restore_test_script"], "/usr/local/sbin/restic-restore-test")
        tasks = {task["name"]: task for task in play["tasks"]}
        restore = tasks["Restore the newest snapshot and compare it with the snapshot"]
        self.assertEqual(restore["ansible.builtin.command"]["cmd"], "{{ restore_test_script }}")
        self.assertIs(restore["changed_when"], False)
        for name, unit in (("Take the database dumps now", "mariadb-dump.service"),
                           ("Take a backup now", "restic-backup.service")):
            with self.subTest(task=name):
                self.assertEqual(tasks[name]["ansible.builtin.systemd_service"]["name"], unit)
                self.assertIn("restore_test_backup_now | bool", json.dumps(tasks[name]["when"]))
        self.assertIn("inventory_hostname in groups['db']", tasks["Take the database dumps now"]["when"])

    def test_task_and_end_to_end_run_use_it(self):
        taskfile = read("Taskfile.yml")
        self.assertIn("bash scripts/environment.sh restore-test {{.ENV}}", taskfile)
        self.assertIn("{{if .BACKUP_NOW}}-e restore_test_backup_now=true{{end}}", taskfile)
        self.assertIn("playbook playbooks/restore_test.yml", read("scripts/environment.sh"))


class SmokeAndPrepareTest(unittest.TestCase):
    def test_smoke_checks_the_four_services(self):
        smoke = read("ansible/playbooks/smoke.yml")
        for needle in ("hosts: edge", "status_code: 200", "SELECT 1", "hosts: fxserver", "/info.json",
                       "hosts: monitoring", "/api/v1/targets", "'health', 'equalto', 'up'",
                       "smoke_node_servers == groups['fxserver'] | sort"):
            with self.subTest(check=needle):
                self.assertIn(needle, smoke)
        self.assertNotIn("players.json", smoke)

    def test_local_prepare_writes_the_dns_drop_in_before_any_firewall_load(self):
        prepare = read("ansible/playbooks/local_prepare.yml")
        self.assertIn("/etc/nftables.d/05-local-container-dns.nft", prepare)
        self.assertIn("table ip local_container_dns", prepare)
        self.assertNotIn("table inet filter", prepare.split("table ip local_container_dns")[1].split("- name:")[0])


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class EndToEndWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(".github/workflows/e2e-local.yml")
        cls.workflow = yaml.safe_load(cls.text)

    def test_pull_requests_and_on_demand_only(self):
        # PyYAML reads the key "on" as True.
        triggers = self.workflow.get("on", self.workflow.get(True))
        self.assertEqual(sorted(triggers), ["pull_request", "workflow_dispatch"])

    def test_no_secrets_and_read_only(self):
        self.assertNotIn("secrets.", self.text)
        self.assertEqual(self.workflow["permissions"], {})
        job = self.workflow["jobs"]["e2e-local"]
        self.assertEqual(job["permissions"], {"contents": "read"})
        self.assertEqual(job["runs-on"], "ubuntu-24.04")

    def test_runs_the_same_target_as_the_taskfile(self):
        steps = self.workflow["jobs"]["e2e-local"]["steps"]
        self.assertEqual(steps[-1]["run"].strip(), "task e2e:local")
        self.assertIn("bash scripts/e2e_local.sh", read("Taskfile.yml"))
        self.assertIn("scripts/install_tofu_tools.sh", self.text)
        self.assertIn("sha256sum -c -", self.text)


class TaskfileTest(unittest.TestCase):
    def test_environment_targets(self):
        taskfile = read("Taskfile.yml")
        for task in ("inventory", "configure", "smoke", "up", "destroy", "rebuild"):
            with self.subTest(task=task):
                block = re.search(rf"(?s)\n  {task}:\n(.*?)(?=\n  [\w:-]+:\n|\Z)", taskfile)
                self.assertIsNotNone(block)
                self.assertIn(f"bash scripts/environment.sh {task} {{{{.ENV}}}}", block.group(1))
                self.assertIn("enum: [local, lab, demo, showcase]", block.group(1))
        self.assertRegex(taskfile, r"\n  e2e:local:\n    desc: ")
        self.assertRegex(taskfile, r"\n  collections:\n    desc: ")


if __name__ == "__main__":
    unittest.main()
