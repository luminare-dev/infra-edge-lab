# 0017. node_exporter from the release archive with a pinned checksum

- **Status:** accepted
- **Date:** 2026-10-21

## Context

Every host exports its metrics with node_exporter, which a Prometheus server, the observability
pack and the backup jobs (through the textfile collector) build on. The version must be the same
on Debian 13 and Ubuntu 24.04, the download must be checked, and the exporter must never listen
on a public address.

## Considered options

1. The release archive from GitHub, checked against a sha256 pinned in the role, unpacked into a
   versioned folder and run by a unit the role writes.
2. The `prometheus.prometheus.node_exporter` role.
3. The distribution package `prometheus-node-exporter`.

## Decision

Chosen option: 1, version 1.12.1, because it gives one version on both platforms and a checksum
that a reviewer can compare with the release's `sha256sums.txt`.

- The role pins `monitoring_node_exporter_version` and a sha256 per architecture (amd64, arm64),
  checked on 2026-10-21 against the release's `sha256sums.txt` and GitHub's asset digests.
  `get_url` refuses an archive with another checksum.
- `/usr/local/bin/node_exporter` links to the unpacked version, so an upgrade or a rollback is a
  change of the version and the checksums, and a restart.
- The unit runs as its own system user without login, with `NoNewPrivileges`,
  `ProtectSystem=strict`, no capabilities and restricted address families.
- The listen address must be loopback or private; a firewall drop-in opens the port for named
  sources only.

Option 2 checks the archive against a checksum file fetched from the same release at run time,
which only proves the transfer, and adds a collection that the `ansible` package does not bundle
([ADR 0016](0016-collections-from-git-tags-and-one-pinned-bundle.md)). Option 3 gives different
versions per distribution (Debian 13 and Ubuntu 24.04 ship different releases) and older
collectors.

## Consequences

- Good: the same binary everywhere, verified against a value under review.
- Bad: updates are manual: version and both checksums change together in one pull request.
- Bad: the role keeps a unit file of its own instead of the one a package or a shared role
  would maintain.
