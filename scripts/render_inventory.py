#!/usr/bin/env python3
"""Render an Ansible inventory from the OpenTofu outputs of one environment.

Every environment under tofu/envs returns the same "hosts" output (docs/adr/0014): a map from
host name to ansible_host, connection, groups and ip. This script turns it into the YAML
inventory that the playbooks read, so the inventory never depends on the substrate (containers,
Proxmox VE virtual machines or cloud servers):

    tofu -chdir=tofu/envs/local output -json | python3 scripts/render_inventory.py --env local \\
        --output ansible/inventories/local/hosts.yml

"task inventory ENV=<env>" runs exactly this. The input is the JSON of "tofu output -json" (all
outputs, of which only "hosts" is read) or of "tofu output -json hosts" (the map itself). The
output holds no secret: names, groups, addresses and the connection plugin only.

Each host gets these variables:
    ansible_host        what Ansible connects to (a container name, an address or a host name)
    ansible_connection  the connection plugin (community.docker.docker or ansible.builtin.ssh)
    host_ip             the host's address in the environment's network; group_vars use it for
                        listen addresses and firewall sources between the hosts
An SSH host of demo or showcase (a cloud server, which has no public SSH port) is reached through
the tunnel: it also gets
    ansible_user             the automation user that cloud-init and the base role create
    ansible_ssh_common_args  ProxyCommand "cloudflared access ssh --hostname %h", which carries
                             the connection to the <env>-ssh hostname behind Access with the
                             service token in TUNNEL_SERVICE_TOKEN_ID and
                             TUNNEL_SERVICE_TOKEN_SECRET (scripts/environment.sh sets both for
                             the playbook run), and the host key in .generated/known_hosts next
                             to the inventory, accepted on the first connection
Every group of the environments (edge, db, fxserver, monitoring, docker_hosts) is written, also
when it is empty, so that a play or a group_vars expression can rely on groups['<name>'].

Standard library only. Exit status 0 on success, 1 for an input that is not a valid hosts map.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

GROUPS = ("edge", "db", "fxserver", "monitoring", "docker_hosts")
CONNECTIONS = ("community.docker.docker", "ansible.builtin.ssh")
ENVS = ("local", "lab", "demo", "showcase")
# Environments whose SSH hosts are cloud servers without a public SSH port: Ansible reaches them
# through the tunnel and Access only (tofu/modules/hcloud_vm).
TUNNEL_SSH_ENVS = ("demo", "showcase")
# The automation user of the luminare.infra_edge base role, the user that cloud-init creates on a
# cloud server (tofu/modules/hcloud_vm, admin_user).
TUNNEL_SSH_USER = "ansible"
# cloudflared from the control node's PATH reads the service token from its environment, never
# from the command line. The host key of a new server is accepted once and kept next to the
# inventory (the destroy of the environment removes the file).
TUNNEL_SSH_ARGS = (
    '-o ProxyCommand="cloudflared access ssh --hostname %h" -o StrictHostKeyChecking=accept-new '
    "-o UserKnownHostsFile={{ inventory_dir }}/.generated/known_hosts"
)
# The host name rule of the OpenTofu modules (tofu/modules/*/variables.tf).
HOST_RE = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
# A container name, an IP address or a DNS name: no spaces, quotes or shell characters.
ANSIBLE_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$")


class InventoryError(ValueError):
    """The input is not a hosts map of the expected shape."""


def hosts_map(data: Any) -> dict[str, Any]:
    """The hosts map from "tofu output -json" (all outputs) or "tofu output -json hosts"."""
    if isinstance(data, dict) and isinstance(data.get("hosts"), dict) and "value" in data["hosts"]:
        data = data["hosts"]["value"]
    if not isinstance(data, dict) or not data:
        raise InventoryError("expected the non-empty hosts output of an environment (tofu output -json)")
    return data


def check_host(name: str, host: Any) -> dict[str, Any]:
    if not HOST_RE.match(name):
        raise InventoryError(f"host name {name!r} is not a lower-case name of letters, digits and hyphens")
    if not isinstance(host, dict):
        raise InventoryError(f"{name}: expected an object with ansible_host, connection, groups and ip")
    missing = {"ansible_host", "connection", "groups", "ip"} - set(host)
    if missing:
        raise InventoryError(f"{name}: missing {', '.join(sorted(missing))}")
    if not isinstance(host["ansible_host"], str) or not ANSIBLE_HOST_RE.match(host["ansible_host"]):
        raise InventoryError(f"{name}: ansible_host {host['ansible_host']!r} is not a host name or address")
    if host["connection"] not in CONNECTIONS:
        raise InventoryError(f"{name}: connection {host['connection']!r} is not one of {', '.join(CONNECTIONS)}")
    groups = host["groups"]
    if not isinstance(groups, list) or not groups or not all(isinstance(g, str) for g in groups):
        raise InventoryError(f"{name}: groups must be a non-empty list of group names")
    unknown = sorted(set(groups) - set(GROUPS))
    if unknown:
        raise InventoryError(f"{name}: unknown group(s) {', '.join(unknown)} (known: {', '.join(GROUPS)})")
    try:
        ip = ipaddress.ip_address(host["ip"])
    except (TypeError, ValueError):
        raise InventoryError(f"{name}: ip {host['ip']!r} is not an IP address") from None
    return {"ansible_host": host["ansible_host"], "connection": host["connection"],
            "groups": sorted(set(groups)), "ip": str(ip)}


def scalar(value: str) -> str:
    """A YAML double-quoted scalar (JSON string syntax is valid YAML)."""
    return json.dumps(value)


def render(hosts: dict[str, Any], env: str) -> str:
    checked = {name: check_host(name, host) for name, host in sorted(hosts.items())}
    lines = [
        f"# Inventory of the environment {env}, generated by scripts/render_inventory.py from the",
        f"# OpenTofu output \"hosts\" of tofu/envs/{env} (task inventory ENV={env}). Do not edit: the next",
        "# run writes it again. The values of the hosts and groups are in group_vars/ next to this file.",
        "all:",
        "  hosts:",
    ]
    for name, host in checked.items():
        lines += [
            f"    {name}:",
            f"      ansible_host: {scalar(host['ansible_host'])}",
            f"      ansible_connection: {scalar(host['connection'])}",
            f"      host_ip: {scalar(host['ip'])}",
        ]
        if env in TUNNEL_SSH_ENVS and host["connection"] == "ansible.builtin.ssh":
            lines += [
                f"      ansible_user: {scalar(TUNNEL_SSH_USER)}",
                f"      ansible_ssh_common_args: {scalar(TUNNEL_SSH_ARGS)}",
            ]
    lines.append("  children:")
    for group in GROUPS:
        members = [name for name, host in checked.items() if group in host["groups"]]
        if not members:
            lines.append(f"    {group}: {{}}")
            continue
        lines += [f"    {group}:", "      hosts:"]
        lines += [f"        {name}: {{}}" for name in members]
    return "\n".join(lines) + "\n"


def write_atomically(path: Path, text: str) -> None:
    """Replace the file in one step, so a failed run never leaves a half-written inventory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env", required=True, choices=ENVS, help="environment name, written into the header")
    parser.add_argument("--output", type=Path,
                        help="inventory file to write (default: standard output); written only when the input is valid")
    parser.add_argument("input", nargs="?", default="-",
                        help="JSON file from tofu output -json (default: standard input)")
    args = parser.parse_args(argv)
    try:
        if args.input == "-":
            data = json.load(sys.stdin)
        else:
            with open(args.input, encoding="utf-8") as handle:
                data = json.load(handle)
        text = render(hosts_map(data), args.env)
    except (InventoryError, json.JSONDecodeError, OSError) as exc:
        print(f"render_inventory.py: {exc}", file=sys.stderr)
        return 1
    if args.output is None:
        sys.stdout.write(text)
    else:
        write_atomically(args.output, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
