"""scripts/render_inventory.py: the Ansible inventory from the "hosts" output of an environment.

The renderer is the only link between OpenTofu and Ansible (docs/adr/0014), so these tests pin
the inventory it writes for each kind of host, the groups that are always present, the refusal
of every malformed input before anything is written, and the YAML that Ansible reads. Standard
library only, except the round trip through PyYAML (requirements-test.txt), which is skipped
without it.
"""

from __future__ import annotations

import json
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

import render_inventory  # noqa: E402

# The shape of "tofu output -json" of the local environment (documentation addresses).
LOCAL_HOSTS = {
    "edge-01": {"ansible_host": "lab-local-edge-01", "connection": "community.docker.docker",
                "groups": ["edge", "monitoring"], "ip": "192.0.2.2"},
    "db-01": {"ansible_host": "lab-local-db-01", "connection": "community.docker.docker",
              "groups": ["db"], "ip": "192.0.2.3"},
    "fx-01": {"ansible_host": "lab-local-fx-01", "connection": "community.docker.docker",
              "groups": ["fxserver"], "ip": "192.0.2.4"},
}
TOFU_OUTPUT = {
    "hosts": {"sensitive": False, "type": ["map", ["object", {}]], "value": LOCAL_HOSTS},
    "network_name": {"sensitive": False, "type": "string", "value": "lab-local"},
}


def run(*args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "render_inventory.py"), *args], input=stdin,
                          capture_output=True, text=True, timeout=30, check=False)


@unittest.skipIf(yaml is None, "PyYAML is not installed (pip install -r requirements-test.txt)")
class RenderTest(unittest.TestCase):
    def render(self, hosts=None, env: str = "local") -> dict:
        return yaml.safe_load(render_inventory.render(LOCAL_HOSTS if hosts is None else hosts, env))

    def test_hosts_get_their_connection_and_address(self):
        inventory = self.render()
        self.assertEqual(inventory["all"]["hosts"], {
            "db-01": {"ansible_host": "lab-local-db-01", "ansible_connection": "community.docker.docker",
                      "host_ip": "192.0.2.3"},
            "edge-01": {"ansible_host": "lab-local-edge-01", "ansible_connection": "community.docker.docker",
                        "host_ip": "192.0.2.2"},
            "fx-01": {"ansible_host": "lab-local-fx-01", "ansible_connection": "community.docker.docker",
                      "host_ip": "192.0.2.4"},
        })

    def test_every_group_is_present_and_holds_its_hosts(self):
        children = self.render()["all"]["children"]
        self.assertEqual(list(children), list(render_inventory.GROUPS))
        self.assertEqual(children["edge"], {"hosts": {"edge-01": {}}})
        self.assertEqual(children["monitoring"], {"hosts": {"edge-01": {}}})
        self.assertEqual(children["db"], {"hosts": {"db-01": {}}})
        self.assertEqual(children["fxserver"], {"hosts": {"fx-01": {}}})
        self.assertEqual(children["docker_hosts"], {}, "an empty group is still defined")

    def test_ssh_hosts_of_a_cloud_environment_go_through_the_tunnel(self):
        """A cloud server has no public SSH port: Ansible goes through <env>-ssh and Access."""
        for env, name in (("demo", "demo-ssh.example.com"), ("showcase", "show-ssh.example.com")):
            with self.subTest(env=env):
                hosts = {"edge-01": {"ansible_host": name, "connection": "ansible.builtin.ssh",
                                     "groups": ["edge", "db"], "ip": "2001:db8::10"}}
                inventory = self.render(hosts, env=env)
                host = inventory["all"]["hosts"]["edge-01"]
                self.assertEqual(host["ansible_host"], name)
                self.assertEqual(host["ansible_connection"], "ansible.builtin.ssh")
                self.assertEqual(host["host_ip"], "2001:db8::10")
                self.assertEqual(host["ansible_user"], "ansible")
                args = host["ansible_ssh_common_args"]
                self.assertIn('-o ProxyCommand="cloudflared access ssh --hostname %h"', args)
                self.assertIn("-o StrictHostKeyChecking=accept-new", args)
                self.assertIn("-o UserKnownHostsFile={{ inventory_dir }}/.generated/known_hosts", args)
                # The service token comes from the environment of the run, never from the inventory.
                self.assertNotIn("service-token", args)
                self.assertNotIn("TUNNEL_SERVICE_TOKEN", render_inventory.render(hosts, env))
                self.assertIn(f"tofu/envs/{env}", render_inventory.render(hosts, env))

    def test_only_cloud_ssh_hosts_get_the_tunnel(self):
        """Containers (also those of demo's tunnel test) and lab's machines connect directly."""
        container = {"edge-01": {"ansible_host": "lab-demo-edge-01", "connection": "community.docker.docker",
                                 "groups": ["edge", "db"], "ip": "192.0.2.10"}}
        lab = {"edge-01": {"ansible_host": "192.0.2.11", "connection": "ansible.builtin.ssh",
                           "groups": ["edge"], "ip": "192.0.2.11"}}
        for hosts, env in ((container, "demo"), (lab, "lab"), (LOCAL_HOSTS, "local")):
            with self.subTest(env=env):
                for host in self.render(hosts, env=env)["all"]["hosts"].values():
                    self.assertNotIn("ansible_ssh_common_args", host)
                    self.assertNotIn("ansible_user", host)

    def test_output_is_stable(self):
        shuffled = dict(reversed(list(LOCAL_HOSTS.items())))
        self.assertEqual(render_inventory.render(LOCAL_HOSTS, "local"), render_inventory.render(shuffled, "local"))

    def test_values_cannot_break_out_of_their_scalar(self):
        """Every value is a quoted scalar, so even an odd container name stays one string."""
        hosts = {"edge-01": {**LOCAL_HOSTS["edge-01"], "ansible_host": "lab-local-edge-01:x"}}
        self.assertEqual(self.render(hosts)["all"]["hosts"]["edge-01"]["ansible_host"], "lab-local-edge-01:x")


class InputTest(unittest.TestCase):
    def test_accepts_all_outputs_or_the_hosts_map(self):
        self.assertEqual(render_inventory.hosts_map(TOFU_OUTPUT), LOCAL_HOSTS)
        self.assertEqual(render_inventory.hosts_map(LOCAL_HOSTS), LOCAL_HOSTS)

    def test_refuses_malformed_hosts(self):
        good = LOCAL_HOSTS["edge-01"]
        cases = {
            "empty output": {},
            "upper-case name": {"Edge-01": good},
            "name with a dot": {"edge.01": good},
            "missing ip": {"edge-01": {k: v for k, v in good.items() if k != "ip"}},
            "bad ip": {"edge-01": {**good, "ip": "192.0.2.300"}},
            "unknown connection": {"edge-01": {**good, "connection": "community.general.lxd"}},
            "unknown group": {"edge-01": {**good, "groups": ["web"]}},
            "no group": {"edge-01": {**good, "groups": []}},
            "shell characters in ansible_host": {"edge-01": {**good, "ansible_host": "x; rm -rf /"}},
            "not an object": {"edge-01": "lab-local-edge-01"},
        }
        for label, hosts in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(render_inventory.InventoryError):
                    render_inventory.render(render_inventory.hosts_map(hosts), "local")


class CommandLineTest(unittest.TestCase):
    def test_writes_the_inventory_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "inventories" / "local" / "hosts.yml"
            out = run("--env", "local", "--output", str(target), stdin=json.dumps(TOFU_OUTPUT))
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout, "")
            self.assertEqual(target.read_text(encoding="utf-8"), render_inventory.render(LOCAL_HOSTS, "local"))

    def test_invalid_input_leaves_the_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "hosts.yml"
            target.write_text("# the inventory of the last good run\n", encoding="utf-8")
            for stdin in ("not json", json.dumps({"hosts": {"value": {}}}),
                          json.dumps({"edge-01": {**LOCAL_HOSTS["edge-01"], "groups": ["web"]}})):
                with self.subTest(stdin=stdin[:30]):
                    out = run("--env", "local", "--output", str(target), stdin=stdin)
                    self.assertEqual(out.returncode, 1)
                    self.assertIn("render_inventory.py:", out.stderr)
                    self.assertEqual(target.read_text(encoding="utf-8"), "# the inventory of the last good run\n")
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["hosts.yml"], "no temporary file is left")

    def test_reads_a_file_and_writes_standard_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "outputs.json"
            source.write_text(json.dumps(TOFU_OUTPUT), encoding="utf-8")
            out = run("--env", "lab", str(source))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith("# Inventory of the environment lab"))

    def test_refuses_an_unknown_environment(self):
        out = run("--env", "prod", stdin=json.dumps(TOFU_OUTPUT))
        self.assertEqual(out.returncode, 2)


if __name__ == "__main__":
    unittest.main()
