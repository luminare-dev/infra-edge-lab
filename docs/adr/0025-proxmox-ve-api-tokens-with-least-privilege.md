# 0025. Proxmox VE API tokens with least privilege, instead of the root account

- **Status:** accepted
- **Date:** 2026-10-22

## Context

The `lab` environment clones virtual machines on a Proxmox VE host through the bpg/proxmox
provider ([ADR 0012](0012-provider-pins-and-lock-files.md)). The provider can log in with a user
and password, with an API token, and for some features over SSH. The account that applies the lab
and the account that CI uses for read-only plans hold credentials that may leak: a token of
`root@pam` would give whoever has it the whole host, its storage and its network.

## Considered options

1. `root@pam` with its password, or an API token of `root@pam`.
2. One dedicated user with a broad built-in role (`PVEAdmin`) on `/`.
3. Two dedicated users, `tofu@pve` (apply) and `ci-plan@pve` (plan), each with a
   privilege-separated API token, and a custom role granted only on the objects the lab uses.

## Decision

Chosen option: 3, because a leaked token can then only do what the lab itself does.

- The provider talks to the API only: no `ssh` block, no snippets and no file uploads, so no
  SSH account on the host is needed (`tofu/modules/pve_vm`).
- `tofu@pve` gets the role `TofuProvisioner` with `VM.Allocate VM.Audit VM.Clone VM.Config.CDROM
  VM.Config.CPU VM.Config.Cloudinit VM.Config.Disk VM.Config.HWType VM.Config.Memory
  VM.Config.Network VM.Config.Options VM.PowerMgmt VM.GuestAgent.Audit Datastore.AllocateSpace
  Datastore.Audit SDN.Use Sys.Audit Pool.Audit`, granted on `/pool/lab`, `/storage/local-lvm`,
  `/sdn/zones/localnetwork` and `/nodes/<node>`, never on `/`. The template (VM ID 9000) and every
  lab machine sit in the pool `lab`, so the clone rights cover exactly them.
- `ci-plan@pve` gets the built-in read-only role `PVEAuditor` on the same four paths.
- Each user has one API token created with `--privsep 1`; such a token has only the rights that
  are granted to both the token and its user, so every ACL names the user and its token. The
  token reaches the provider as `PROXMOX_VE_API_TOKEN` from the environment's SOPS file
  ([ADR 0006](0006-sops-and-age-for-secrets.md)); the plan token is in `secrets/lab-ci.enc.env`.
- CI reaches the API only through the Access application `lab-pveapi` with a service token
  (`PROXMOX_VE_API_HEADERS`); this repository never publishes the API port to the internet.
- The setup is a manual procedure on the host
  ([runbook](../runbook.md#procedure-set-up-the-proxmox-ve-users-of-the-lab)). Each privilege
  added later is recorded in a new ADR that supersedes this one.

## Consequences

- Good: a leaked apply token can create, change and delete machines in the pool `lab` only; it
  cannot change the host, other guests, users or the network configuration. A leaked plan token
  can read, not write.
- Bad: no Proxmox VE host was used for this version, so the privilege list is the plan's and has
  not been proven by an apply; a missing privilege shows up as a `403` in the first apply.
- Bad: the identities live on the host, not in this repository; rebuilding the host means running
  the procedure again.
