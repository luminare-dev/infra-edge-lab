# 0016. Collections from git tags, and one pinned bundle for the tests

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The generic roles (base hardening, tunnel, web server, database, backups) and the game server
roles live in their own collections, `luminare.infra_edge` and `luminare.gameserver`, each in its
own repository; this repository keeps only the roles that belong to this environment and pins the
collections. The collections are not published on Ansible Galaxy. The roles here, ansible-lint
and the Molecule Docker driver also need community collections (`community.docker`,
`ansible.posix`, `community.sops`), and a test should never depend on what Galaxy serves on the
day it runs.

## Considered options

1. `ansible/requirements.yml` with the luminare collections as `type: git` at a release tag, the
   community collections at exact versions; CI takes the community collections from the
   hash-pinned `ansible` package of `requirements-test.txt`.
2. Everything from Ansible Galaxy, with version ranges.
3. Copies of the collection roles in this repository.

## Decision

Chosen option: 1.

- `luminare.infra_edge` and `luminare.gameserver` are installed from
  `https://github.com/luminare-dev/ansible-collection-<name>.git` at a tag (`v0.2.0`), so a run
  always gets the reviewed release, and this repository holds no copy of their roles (a unit test
  checks that `ansible/roles` has none of them).
- The community collections are pinned to exactly the versions that the `ansible` package
  (14.5.0) bundles; a unit test compares both after the hash-pinned install, so lint, Molecule
  and a real run use the same versions. `devsec.hardening`, which the bundle does not include,
  is pinned to the newest release of the range `luminare.infra_edge` declares.
- `ansible.cfg` installs collections into `ansible/collections` (git-ignored), never into the
  user's collection path.
- CI never installs `requirements.yml`: the roles of this repository do not need the luminare
  collections, ansible-lint runs offline, and the Molecule dependency step is disabled.

## Consequences

- Good: pip checks every collection used in CI against a sha256; Galaxy can be down or changed
  without breaking a test.
- Good: a Dependabot update of the `ansible` package fails the unit test until
  `ansible/requirements.yml` follows, so the two cannot drift apart.
- Bad: a new collection release reaches this repository only with the next `ansible` package
  (about once a month).
- Bad: `ansible-galaxy collection install -r requirements.yml` needs the tagged collection
  repositories to exist and to be readable; until then it fails.
