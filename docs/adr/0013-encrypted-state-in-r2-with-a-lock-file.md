# 0013. Encrypted state in R2 with a lock file

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The state of an environment holds addresses, resource IDs and secrets: the client secrets of the
Access service tokens and, for a cloud server started with a tunnel token, the first-boot user
data. The operator works from a workstation and CI plans from a runner, so the state must live
outside both, must not be readable by whoever gets a copy of the stored object or the laptop,
and must not be written by two runs at once. Cloudflare R2 is S3-compatible and has a free tier,
but it keeps no object versions, and its documentation does not mention OpenTofu's S3 lock file.
No R2 bucket exists yet for this project.

## Considered options

1. Local state files only, copied around by hand.
2. A managed backend service that stores and locks state.
3. The S3 backend on R2 with OpenTofu's lock file (`use_lockfile`), and the state and plan files
   encrypted by OpenTofu before they leave the machine.

## Decision

Chosen option: 3, because it needs no extra service or account beyond the zone's provider,
works the same on a workstation and in CI, and leaves the storage provider with ciphertext only.

- `lab`, `demo` and `showcase` keep their state in the bucket `luminare-tfstate`, one key per
  environment (`<env>/terraform.tfstate`), with `use_lockfile = true`. The account-specific
  endpoint and the credentials are not in the code: they come from `AWS_ENDPOINT_URL_S3`,
  `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in the environment's SOPS file
  ([ADR 0006](0006-sops-and-age-for-secrets.md)). Without the endpoint the S3 backend would
  send its requests to AWS, so `task init` and `task plan` refuse to use the remote backend
  without `AWS_ENDPOINT_URL_S3`.
- Every environment has the same `encryption.tofu`: a PBKDF2 key from `TF_VAR_state_passphrase`
  (at least 16 characters), AES-GCM, `enforced = true` for state and plan files. It is a
  `.tofu` file, so Terraform and TFLint never read it ([ADR 0005](0005-opentofu-instead-of-terraform.md)).
  No fallback is committed; a migration or a passphrase change adds one for one run only
  ([runbook](../runbook.md)).
- The `local` environment keeps its state in a local file, encrypted the same way, with a random
  passphrase per run: its containers and its state are thrown away together.
- `task init ENV=<env> BACKEND=local` writes a git-ignored `backend_override.tf`, so a remote
  environment can be planned or tried without the bucket, still encrypted.

## Consequences

- Good: a copy of the state object, a plan file or a stolen workstation without the passphrase
  reveals nothing; no endpoint, account ID or key is in the repository.
- Bad: the passphrase is the state. Lost passphrase, lost state: it is kept in the SOPS file and
  offline, and recovering without it means importing every resource again.
- Bad: the state can be read with OpenTofu only, not with Terraform.
- Bad: whether R2 honours the conditional write behind `use_lockfile` is not tested yet (no
  bucket). Until a lock test passes, the rule is one operator applying at a time, and a CI plan
  with a read-only token, which cannot write the lock file, runs with `-lock=false`.
- Bad: R2 keeps no old versions of an object; a backup of the state after each apply is a
  separate task.
