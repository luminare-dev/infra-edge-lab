# 0026. TLS between the tunnel connector and its origins

- **Status:** accepted
- **Date:** 2026-10-22

## Context

Visitors reach the published hostnames through Cloudflare's edge and the tunnel; that part is
encrypted end to end between the edge and the connector (`cloudflared`) on the host in the group
`edge` ([ADR 0011](0011-remotely-managed-tunnel-and-its-token.md)). From the connector, each
ingress rule forwards to an origin: a service on the same host, or a service on another host of
the environment's network, such as the hypervisor's web interface or the game server's admin
panel in `lab`. That last hop is not covered by the tunnel.

## Considered options

1. HTTPS to every origin with certificates from an internal certificate authority, checked by the
   connector (`origin_server_name`, `ca_pool`).
2. Loopback for origins on the connector's host; origins on other hosts only inside the
   environment's private network, over HTTP, or over HTTPS without verification where the origin
   has a self-signed certificate.
3. A connector on every host that serves an origin, so that every origin is on loopback.

## Decision

Chosen option: 2 for this version, because it needs no certificate authority while every origin
stays inside one private network that this repository builds.

- Origins on the edge host use `127.0.0.1` or `localhost`: the web server (`lab-demo`,
  `demo-web`, `show-web`), the status page (`lab-status`), SSH (`demo-ssh`, `show-ssh`) and the
  admin panel when the game server shares the host (`demo-tx`, `show-tx`). The web server and the
  status page listen on loopback only.
- Origins on other hosts exist in `lab` only: `lab-tx` forwards to port 40120 of the game server
  host over HTTP, and `lab-pve` and `lab-pveapi` to the Proxmox VE API over HTTPS with
  `no_tls_verify`, because the host has a self-signed certificate.
- Every one of these cross-host hostnames sits behind Access with `access.required = true`, so the
  connector itself rejects a request without a valid Access token before it opens the origin.
- `cf_tunnel` accepts `origin_server_name` and `ca_pool` in each rule, so option 1 can follow
  without a module change.

## Consequences

- Good: no certificate authority, no certificate renewal and nothing on the hosts to keep in sync.
- Bad: inside the lab network, the admin panel traffic is plain HTTP and the hypervisor's
  certificate is not checked; anyone who can read or redirect traffic on that network sees or
  intercepts it. The lab network must hold only the lab's own machines.
- Bad: option 1 (or option 3 for the game server host) is open work before a cross-host origin
  is used outside a private lab network.
