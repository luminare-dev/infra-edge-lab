# 0018. Uptime Kuma monitors as a checklist

- **Status:** accepted
- **Date:** 2026-10-21

## Context

Uptime Kuma checks the public names, ports and jobs of the environment from a host that is not
one of the hosts it watches. It keeps its monitors in its own database. It has no supported
configuration file and no supported API for creating monitors; the existing clients use its
internal Socket.IO interface, and whether they work with Uptime Kuma 2.x was not verified.

## Considered options

1. The role runs Uptime Kuma (image pinned by digest) and renders the monitors from a variable
   into a checklist that an operator follows once in the web interface.
2. A client of Uptime Kuma's internal interface (a community Python library or collection) that
   creates the monitors.
3. A different checker with configuration as code (for example a Prometheus blackbox exporter
   with alert rules).

## Decision

Chosen option: 1.

- `monitoring_monitors` lists each monitor with the fields of Uptime Kuma's "Add New Monitor"
  dialog; the role checks them (URL without user name or password, ports, interval) and writes
  `/etc/uptime-kuma/monitors.md`.
- `monitoring_external_probes` is a separate, stricter list for hosts outside this environment:
  read-only types only, a host name instead of an IP address, and at most one check every five
  minutes.
- Notifications (for example a Discord webhook) are set up by hand as well, so no webhook URL is
  stored in a variable or on disk by the role.
- The image is the `slim` variant (no embedded MariaDB, no browser engine), published on loopback
  and reached through a tunnel with access control.

Option 2 depends on an interface the project does not promise to keep. Option 3 is planned for
metrics and alerts in the observability pack; it does not replace a simple status page.

## Consequences

- Good: no unofficial client, and the list of monitors is reviewed in the inventory like any
  other setting.
- Bad: creating the monitors takes about a minute each by hand, and a monitor changed in the web
  interface is not compared with the list.
