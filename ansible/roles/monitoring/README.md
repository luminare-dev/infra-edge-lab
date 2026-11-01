# monitoring role

Knowing when something breaks: node_exporter on every host for host metrics, and optionally
Uptime Kuma on a host that watches the others. node_exporter comes from its release archive with
a pinned version and checksum and runs as a
sandboxed systemd service; it and Uptime Kuma listen on loopback or a private address only, never
on a public one. Uptime Kuma has no supported way to define monitors as code, so the role renders
the monitors to create into a checklist.

## Requirements

- Managed host: Debian 13 or Ubuntu 24.04 on x86_64 or arm64, reached as root or with
  `become: true`, with network access to GitHub's release downloads (node_exporter) and, for
  Uptime Kuma, to Docker Hub.
- Uptime Kuma: the [docker role](../docker/README.md) applied before this one, on a host other
  than the ones Uptime Kuma watches (a monitor that runs on the watched host goes down with it).
- Control node: the collection `community.docker` (in [ansible/requirements.yml](../../requirements.yml)).
- With the base role's firewall and `monitoring_node_exporter_allowed_sources`:
  `/etc/nftables.conf` and `nft`.

## Example playbook

```yaml
- name: Host metrics everywhere
  hosts: all
  become: true
  roles:
    - role: monitoring

- name: Uptime Kuma on the monitoring host
  hosts: monitoring
  become: true
  roles:
    - role: docker
    - role: monitoring
      vars:
        monitoring_uptime_kuma_enabled: true
        monitoring_monitors:
          - name: Web site
            type: http
            url: https://lab-demo.example.com/
            accepted_status_codes: 200-302
          - name: Game port
            type: port
            host: 192.0.2.13
            port: 30120
          - name: Backup age
            type: push
            interval: 93600
```

A Prometheus server on another host reaches node_exporter when it listens on a private address
and the server is an allowed source. On the lab's virtual machines the default address is a
private one (on a cloud server it is public, and the role would refuse it):

```yaml
monitoring_node_exporter_listen_address: "{{ ansible_facts['default_ipv4']['address'] }}"
monitoring_node_exporter_allowed_sources:
  - 192.0.2.20/32
```

## Controls

| Control | How | Checked in Molecule |
|---|---|---|
| Pinned node_exporter | release archive of `monitoring_node_exporter_version` checked against `monitoring_node_exporter_checksums` before it is unpacked; `/usr/local/bin/node_exporter` links to that version | `node_exporter --version` is 1.12.1; the metrics show the build |
| Never on a public address | listen address and Uptime Kuma address must be loopback or private (127.0.0.0/8 or ::1, the RFC 1918 networks, the RFC 6598 shared address space or an IPv6 unique local address in fc00::/7); `0.0.0.0`, `::` and public addresses are refused | port 9100 listens on the configured address only (Debian: the instance's private address, Ubuntu: 127.0.0.1); `0.0.0.0` is refused |
| Firewall opening only for named sources | `/etc/nftables.d/50-monitoring.nft` with `ip saddr`/`ip6 saddr` accept rules for port 9100, only for a private listen address, checked with `nft --check` together with `/etc/nftables.conf`; removed again when the list is empty | the rules for the documentation ranges on Debian, no file on Ubuntu, `nft --check` |
| Sandboxed exporter | own system user without login, `NoNewPrivileges`, `ProtectSystem=strict`, no capabilities, restricted address families | unit properties |
| Textfile collector | `monitoring_node_exporter_textfile_dir` for metrics of other jobs (for example the age of the last backup) | a `.prom` file written in verify appears in the metrics |
| Uptime Kuma pinned and on loopback | image pinned by digest (refused otherwise), port published on `monitoring_uptime_kuma_bind_address`, data in a named volume, `no-new-privileges`, restart unless stopped | container running from the digest, port 3001 on `127.0.0.1` only, the web interface answers; a tag without digest is refused |
| Monitors as a checklist | `monitoring_monitors` and `monitoring_external_probes` rendered into `/etc/uptime-kuma/monitors.md` with the labels of Uptime Kuma's "Add New Monitor" dialog | every monitor and probe appears as its table row |
| External probes stay read-only | for hosts outside this environment: http, keyword, port or smtp only, by host name (never an IP address), no user name or password in a URL, at most every 5 minutes | a probe of an IP address is refused |

## Variables

The table is generated from [`meta/argument_specs.yml`](meta/argument_specs.yml), which Ansible
also uses to check the variables when the role starts.

<!-- argument-specs:monitoring:begin -->
| Variable | Type | Default | Description |
|---|---|---|---|
| `monitoring_node_exporter_enabled` | bool | `true` | Install and run node_exporter. |
| `monitoring_node_exporter_version` | str | `1.12.1` | node_exporter release to install. Change monitoring_node_exporter_checksums with it (from the release's sha256sums.txt). |
| `monitoring_node_exporter_checksums` | dict | `{"amd64": "b51d8a76aa2a9156a55d501aca6276fae09e262259a5e4e831d2c2222f084e63", "arm64": "ad35b605f9954b9f1ffddf5ba054bdc5a98d790b9eae5291e1eeb83f1ecbd0e7"}` | sha256 of the release archive for each architecture (amd64, arm64); the download fails when the archive differs. |
| `monitoring_node_exporter_download_url` | str | `https://github.com/prometheus/node_exporter/releases/download` | Base URL of the release archives; the role appends the release tag and the archive name of the version and architecture, as on the release page. |
| `monitoring_node_exporter_listen_address` | str | `127.0.0.1` | Address node_exporter listens on: loopback or a private address (127.0.0.0/8 or ::1, the RFC 1918 networks, the RFC 6598 shared address space or an IPv6 unique local address in fc00::/7). The role refuses any other, including 0.0.0.0 and ::. |
| `monitoring_node_exporter_port` | int | `9100` | TCP port of node_exporter. |
| `monitoring_node_exporter_textfile_dir` | str | `/var/lib/node_exporter/textfile` | Directory of the textfile collector: other jobs (for example a backup) write *.prom files here, and node_exporter exports their metrics. |
| `monitoring_node_exporter_extra_args` | list of str | `[]` | More command-line flags for node_exporter, for example --collector.systemd. Flags that set the listen address or the textfile directory are refused. |
| `monitoring_node_exporter_allowed_sources` | list of str | `[]` | IPv4 or IPv6 addresses or networks that may reach node_exporter (for example a Prometheus server), written as accept rules into /etc/nftables.d/50-monitoring.nft. Allowed only with a private (not loopback) listen address. Empty removes the drop-in. |
| `monitoring_firewall_manage` | bool | `false` | Write the drop-in even when /etc/nftables.d does not exist yet. Without it, the file is written only when the directory exists. |
| `monitoring_firewall_reload` | bool | `true` | Restart nftables.service after the drop-in changed. Molecule sets it to false (a container is no place to prove a loaded input ruleset; the drop-in is still validated). |
| `monitoring_uptime_kuma_enabled` | bool | `false` | Run Uptime Kuma in a container and render the monitor checklist. Needs Docker (the docker role). Place it on a host other than the ones it watches. |
| `monitoring_uptime_kuma_image` | str | `louislam/uptime-kuma:2.5.6-slim@sha256:5db97dbbef610276e1699f3ece586c3509c8fd35de75d45ff5109761a1b377dc` | Uptime Kuma image, pinned by digest. The slim variant has no embedded MariaDB and no browser engine; it stores its data in SQLite. |
| `monitoring_uptime_kuma_container_name` | str | `uptime-kuma` | Name of the Uptime Kuma container. |
| `monitoring_uptime_kuma_bind_address` | str | `127.0.0.1` | Address the Uptime Kuma port is published on: loopback or a private address, as for node_exporter. Reach it through a tunnel with access control, not from the internet. |
| `monitoring_uptime_kuma_port` | int | `3001` | Host port for the Uptime Kuma web interface (the container listens on 3001). |
| `monitoring_uptime_kuma_data_volume` | str | `uptime-kuma-data` | Docker volume that keeps the Uptime Kuma database (/app/data in the container). |
| `monitoring_uptime_kuma_checklist_path` | str | `/etc/uptime-kuma/monitors.md` | Where the role writes the checklist of monitors to create in Uptime Kuma (Markdown). |
| `monitoring_monitors` | list of dict | `[]` | Monitors for the checklist. Each item has name and type (http, keyword, port, ping, dns, push or smtp), the target (url for http and keyword, plus keyword; host for port, ping, dns and smtp, plus port for port and smtp) and optionally interval (seconds, at least 20, default 60), accepted_status_codes (default 200-299), upside_down (default false) and notes. Never put credentials into a monitor. |
| `monitoring_external_probes` | list of dict | `[]` | Read-only checks of hosts outside this environment, listed in their own section of the checklist. Same keys as monitoring_monitors, but only the types http, keyword, port and smtp, a host name (never an IP address) as target, no user name or password in a URL and an interval of at least 300 seconds. |
<!-- argument-specs:monitoring:end -->

## Limitations

- The monitors are created by hand in Uptime Kuma (about a minute per monitor), and so is the
  notification channel (for example a Discord webhook): the role does not configure alerts, and
  an alert after a real outage was not tested.
- Molecule runs Uptime Kuma in Docker inside the test container; reaching it through a tunnel
  with access control, and node_exporter scraped by a Prometheus server on another host, are not
  tested. The firewall drop-in is validated, not loaded, in Molecule.
- node_exporter and Uptime Kuma are not upgraded automatically: change the version and checksums
  (or the image digest) and run the role again.
