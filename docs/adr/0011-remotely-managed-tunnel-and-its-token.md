# 0011. Remotely managed tunnel, and where its token goes

- **Status:** accepted
- **Date:** 2026-10-21

## Context

Hosts are published through a Cloudflare tunnel instead of open ports. A tunnel is either
locally managed (a credentials file and a configuration file on the host) or remotely managed
(the configuration lives at Cloudflare, the connector authenticates with a tunnel token). The
token is a secret. Reading it through the provider's data source needs an API token with tunnel
write permission, and data sources are read during every plan, including read-only plans in CI.

## Considered options

1. Locally managed tunnel with a `tunnel_secret` in the code and a credentials file on the host.
2. Remotely managed tunnel; the token is an output of the tunnel module.
3. Remotely managed tunnel; the token is never an output and is fetched when it is needed.

## Decision

Chosen option: 3.

- `cf_tunnel` creates the tunnel with `config_src = "cloudflare"` and no `tunnel_secret`, holds
  the ingress rules in code (always ending with `http_status:404`) and outputs only the tunnel ID
  and names, never the token.
- When a host is configured, the token is fetched from the API with the tunnel ID and handed to
  the playbook in its environment only; it is not written to disk on the workstation.
- For a cloud server's first boot, `hcloud_vm` can read the token itself, only when
  `fetch_tunnel_token = true` (read-only plans leave it false). The token then travels in the
  user data, so it is stored in the server's metadata at Hetzner and in the encrypted state.
  This is accepted for the short-lived `demo` environment; on the server it is written to a 0600
  file and read with `--token-file`, never placed on a command line.

## Consequences

- Good: read-only plans work with a read-only API token; no secret appears in outputs or logs.
- Good: the ingress rules are reviewed in pull requests like any other code.
- Bad: the first boot of a cloud server with a token leaves a copy in the provider's metadata;
  rotating the token after the cloudflared role has taken over removes its value.
