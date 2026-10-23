# 0022. An end-to-end run of the local environment on every pull request

- **Status:** accepted
- **Date:** 2026-10-22

## Context

The repository promises an environment that can be rebuilt from nothing with one command and is
tested on every change. The roles are tested one by one with Molecule, and the modules with
mocked providers, but neither shows that the whole chain works: OpenTofu outputs, the inventory,
all roles together on several hosts with their firewall drop-ins between them, a second run that
changes nothing, and a working service at the end. Pull requests from forks get no secret, and no
cloud account is available to CI.

## Considered options

1. `task e2e:local`: the `local` environment (systemd containers, [ADR 0010](0010-systemd-containers-as-a-local-substrate.md))
   from apply to destroy, with test doubles for what needs an account or a licence, on every pull
   request.
2. A scheduled run against a cloud server.
3. A Molecule scenario with all hosts.

## Decision

Chosen option: 1, because it needs nothing but Docker and runs on fork pull requests.

- `scripts/e2e_local.sh` runs, each step timed: `tofu init` and `apply` (a random state
  passphrase per run), the inventory, the collections, `site.yml` twice (the second run must report
  `changed=0` for every host), `tofu plan -detailed-exitcode` (no changes), the smoke test, the
  restore test (`playbooks/restore_test.yml`: the database dumps and a backup on every host, then
  the newest snapshot restored and compared), and always `destroy`. It refuses to start over a state file of an earlier run, and the destroy
  removes the empty state with the run's secrets.
- Test doubles, all in `ansible/inventories/local/` and `playbooks/local_prepare.yml`, never in
  `site.yml`: the game server is the fake build of `tests/fake-artifact/` (a stand-in that
  answers the server's HTTP endpoints); every password is generated on first use into the
  git-ignored `.generated/` folder; the users get a throwaway SSH key; the backup repository is a
  folder on the host; there is no tunnel (`TUNNEL_TOKEN` is cleared).
- The base firewall is loaded in each container's own network namespace, so the drop-ins between
  the hosts are tested for real. Its `flush ruleset` also removes the NAT rules through which a
  container reaches Docker's DNS server; `local_prepare.yml` writes
  `/etc/nftables.d/05-local-container-dns.nft`, which puts the same two translations back with
  the ports that server listens on in the container. A real host never gets this file.
- The CI workflow `e2e-local` runs the same `task e2e:local` on `pull_request` and on demand,
  with read-only permissions, no secrets, and OpenTofu and go-task checked by sha256. It installs
  `ansible/requirements.yml` (the luminare collections from their git tags), which supersedes the
  point of [ADR 0016](0016-collections-from-git-tags-and-one-pinned-bundle.md) that CI never
  installs it; the unit tests, ansible-lint and Molecule still do not.

## Consequences

- Good: a change that breaks the composition of the roles fails a pull request. The first runs
  found two such faults: firewall reloads from several roles within a minute exhausted Docker's
  start limit and left Docker stopped (the `docker` role now allows 10 starts in 60 seconds), and
  an empty state file of a destroyed run blocked the next run.
- Bad: containers are not virtual machines (kernel, boot, real interfaces), the fake build is not
  the real server, and there is no tunnel; those checks stay for real environments.
- Bad: the workflow needs GitHub and Ansible Galaxy at the collection step; the collection
  repositories are public and tagged (since 2026-10-22), and a change of a collection can be
  tried before its release only on a workstation, through `ANSIBLE_COLLECTIONS_PATH`.
- Bad: a run takes about 13 minutes on a workstation (810 s with the tagged collections and the
  restore test on 2026-10-22; 767 to 811 s in earlier runs without it), most of it the two
  playbook runs.
