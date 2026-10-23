# 0028. The game server runs as the user `fxserver`

- **Status:** accepted
- **Date:** 2026-10-22

## Context

The game server role of `luminare.gameserver` runs the server as a system user, and two roles of
this repository depend on that name: `deploy_target` runs its deploy service as that user and
gives its group the spool directory, and `docker` refuses hosts of the game server group. The
first draft of plan 09 named the user after the game platform. Identifiers in these repositories
carry no platform or vendor brand, and the three repositories must agree on one name, because a
mismatch only shows up on a real host (a missing user, files the service cannot read).

## Considered options

1. A user named after the game platform, as in the first draft.
2. One neutral name for the user, the group, the inventory group and the paths, the same in both
   collections and here: `fxserver`.
3. No default: every inventory names the user.

## Decision

Chosen option: 2.

- User and group `fxserver`, home and base directory `/opt/fxserver`, unit `fxserver.service`
  (created by `luminare.gameserver.fxserver`), and the inventory group `fxserver` of the `hosts`
  output ([ADR 0021](0021-one-site-playbook-with-the-inventory-from-the-opentofu-outputs.md)).
- `deploy_target` defaults to `deploy_target_run_user: fxserver`,
  `deploy_target_run_group: fxserver` and `deploy_target_release_root: /opt/fxserver/releases`;
  the spool directory is `deploy:fxserver` with mode `2770`
  ([ADR 0020](0020-upload-only-deploy-key-and-a-path-unit.md)).
- `docker` refuses hosts in `docker_forbidden_groups`, by default `["fxserver"]`, so Docker never
  runs on a game server host ([ADR 0019](0019-docker-ports-on-loopback-and-a-firewall-that-restarts-docker.md)).
- A unit test keeps the defaults of `deploy_target` and `docker` on this name.

## Consequences

- Good: the roles of the collections and of this repository fit together without extra
  inventory values, and `task e2e:local` runs them together on one host.
- Bad: a host that already runs a game server under another user needs
  `deploy_target_run_user` and `deploy_target_run_group` set in its inventory.
