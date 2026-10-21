# 0012. Provider choices, version constraints and lock files

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The modules need providers for Proxmox VE, Cloudflare, Hetzner Cloud and Docker. Two Proxmox VE
providers exist; the Cloudflare provider renamed its resources in major version 5; the Docker
provider is at major version 4. A provider release can change behaviour, and the code must also
stay valid for Terraform ([ADR 0005](0005-opentofu-instead-of-terraform.md)).

## Considered options

1. Constraints only, no lock files.
2. Exact versions in the constraints.
3. Ranges in the constraints, lock files committed for every module, and the lowest version of
   each range tested.

## Decision

Chosen option: 3.

- Providers: `bpg/proxmox` (the Telmate provider publishes only release candidates of its
  current major version), `cloudflare/cloudflare` 5.x, `hetznercloud/hcloud` and
  `kreuzwerker/docker` 4.x.
- Constraints: `bpg/proxmox ~> 0.114.0` (below 1.0 a minor release may break, so patch releases
  only), `cloudflare ~> 5.25`, `hcloud ~> 1.69`, `docker ~> 4.6`. `tofu test` and `tofu validate`
  were also run with the lowest version of each range.
- Every module directory commits its `.terraform.lock.hcl`, written with
  `tofu providers lock -platform=linux_amd64 -platform=darwin_arm64`: package checksums (`h1:`)
  for those two platforms plus the registry's signed checksums (`zh:`) of every platform's
  archive. CI runs `tofu init -lockfile=readonly`, so a provider that does not match the lock
  file fails the job.
- A lock file takes a release only after the 7-day cooldown that Dependabot keeps, unless the
  release fixes a security problem. The one exception at this version: `cloudflare` 5.28.1,
  published less than a day before it was locked, is a rebuild that distrusts certificate
  authorities revoked for compromise ([docs/toolchain.md](../toolchain.md)).
- Dependabot's `opentofu` ecosystem proposes updates of the constraints and lock files
  ([ADR 0007](0007-dependabot-instead-of-renovate.md)); `bpg/proxmox` gets its own pull request.
- The Terraform compatibility check resolves the same constraints from Terraform's registry in a
  throwaway copy; it never writes the committed lock files.

## Consequences

- Good: every run uses the same provider builds, verified by checksum.
- Good: the ranges are honest: their lower ends pass the tests as well.
- Bad: a provider update changes the lock file of every module that uses the provider (three
  for Cloudflare); Dependabot groups them into one pull request.
