# 0024. A tunnel test guarded by a zone preflight, a comparison and a sweeper

- **Status:** accepted
- **Date:** 2026-10-22

## Context

`task e2e:local` has no tunnel, so the tunnel, its DNS records, Access and the token fetch are
tested with mocks only. A real test writes into the shared zone (ADR 0009), whose token can edit
every record, and an interrupted run leaves objects behind that cost nothing but block the next
run and clutter the zone. Plan 09 asks for `dns-backup` before every apply, a tunnel test with
`demo-*` names and a sweeper for orphans.

## Considered options

1. A tunnel test against a cloud server.
2. The `demo` environment with `substrate = "docker"` on the runner, guarded by the API.
3. No live test; mocks only.

## Decision

Chosen option: 2, because it needs no cloud server and runs the same on a workstation.

- `scripts/e2e_tunnel.sh` (`task e2e:tunnel`, workflow `e2e-tunnel`) plans a copy of `tofu/envs/demo`
  with local encrypted state: tunnel `demo-e2e`, `demo-web` and `demo-ssh` behind Access with a
  service token each, and the container `lab-e2e-demo-edge-01`. It configures the host with
  `site.yml` and checks from outside: `demo-web` serves a page with the run's marker only with the
  token, and Ansible pings the host over SSH through `demo-ssh` with the other token.
- Preflight (`scripts/cf_preflight.sh`): prints the token permissions, checks what reads can show,
  and refuses when the zone ID is not the zone's, when a record under the prefix lacks the
  environment's comment, or when a saved plan would touch a name outside the prefix, create a
  name that exists or change a record without the comment. `task up` and `apply` run it too.
- Every record outside `demo-*` is snapshotted before and compared after the run;
  `task dns-backup` keeps an age-encrypted zone file locally (`task up` runs it before an apply).
- The sweeper deletes demo objects by their names and markers, never a tunnel with a connector;
  the test sweeps only what was created since its start (minus five minutes for clock skew).
- The test and `apply` of demo share one concurrency group, because they use the same names.

## Consequences

- Good: the whole tunnel chain is testable with a zone token, without a cloud server.
- Bad: the test writes into the real zone for some minutes; the guards bound that to `demo-*`.
- Bad: it has not run at this version (no write token); its parts were tested against a
  stand-in API and the host part on a container without the tunnel.
