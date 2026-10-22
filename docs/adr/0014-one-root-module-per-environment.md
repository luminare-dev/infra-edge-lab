# 0014. One root module per environment

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The same building blocks (machines, a tunnel, DNS records, Access applications) run in four
places with different lifetimes and risks: containers on a workstation or a CI runner, a lab on
Proxmox VE, a throw-away cloud server for demonstrations, and a long-lived public cloud server.
A mistake in the throw-away environment must never destroy the long-lived one, and a test on a
CI runner must not need a cloud account.

## Considered options

1. One root module with workspaces, the differences in variables.
2. One root module per environment under `tofu/envs/`, each with its own state, providers,
   names and tests, built from the shared modules.
3. A wrapper tool that generates the root modules.

## Decision

Chosen option: 2, because each environment's blast radius, credentials and protection are then
visible in its own files and checked by its own tests.

- `local`: systemd containers on the local Docker daemon (`docker_host`), no cloud provider and
  no secret, so it can run on every pull request, forks included.
- `lab`: Proxmox VE virtual machines (`pve_vm`), its tunnel and Access applications; every host
  in the group `db` must be protected.
- `demo`: one host that is thrown away after use, never protected. `substrate = "hcloud"` creates
  a cloud server; `substrate = "docker"` creates the same host as a container, so the tunnel can
  be tested end to end on a CI runner. Names and Access rules are the same for both.
- `showcase`: a skeleton for one long-lived cloud server; protection is a fixed value, not a
  variable, and its primary IPv4 address outlives the server for the DNS-only record `play`.
- Every environment returns the same `hosts` output (`ansible_host`, `connection`, `groups`,
  `ip`), so the inventory does not depend on the substrate
  ([ADR 0010](0010-systemd-containers-as-a-local-substrate.md)).
- Each environment has its own name prefix (`lab-`, `demo-`, `show-`/`play`) under the guard of
  [ADR 0009](0009-guard-rails-for-a-shared-dns-zone.md), and its own state key
  ([ADR 0013](0013-encrypted-state-in-r2-with-a-lock-file.md)).
- Guard tests per environment plan the whole root module against mocked providers: names and
  record types, protection, which hostnames sit behind Access, and the `hosts` output.

## Consequences

- Good: `demo` and `showcase` share no state, so a destroy of one cannot touch the other.
- Good: the guard tests run without credentials on every change.
- Bad: provider blocks, the backend and the encryption file repeat in each environment; tests
  check that the encryption file and the provider builds stay the same everywhere.
- Bad: `demo` with `substrate = "docker"` still starts the cloud provider, which refuses to start
  without a token; it gets a placeholder that the API would reject.
