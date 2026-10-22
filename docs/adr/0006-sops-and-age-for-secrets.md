# 0006. SOPS and age for secrets

- **Status:** accepted
- **Date:** 2026-10-21

## Context

Applying an environment needs API tokens for the hypervisor, the DNS and tunnel provider, the
cloud provider and the state storage, plus the state encryption passphrase. The operator and CI
both need some of them; CI should only ever get read-only tokens for plans. The repository is
public, so a plaintext secret in any commit is leaked for good.

## Considered options

1. GitHub environment secrets only.
2. Ansible Vault files.
3. SOPS-encrypted dotenv files with age keys, one pair of files per environment.
4. A secrets server (for example HashiCorp Vault or OpenBao).

## Decision

Chosen option: 3, because the encrypted files are versioned and reviewed with the code, work the
same on a workstation and in CI, need no server, and age keys are short and easy to back up.

- `secrets/<env>.enc.env` holds the write credentials; `secrets/<env>-ci.enc.env` holds
  read-only credentials for CI plans. Path-based SOPS creation rules choose the recipients: the
  operator's key and an offline break-glass key everywhere, the CI key of an environment only
  where CI needs it.
- The creation rules live in `.sops.yaml` at the repository root, which is committed and holds
  public age keys only; private keys never enter the repository. A fork replaces the recipients
  with its own keys. [env.example](../../secrets/env.example) lists the keys a file can hold.
- Values reach a command only through its environment
  (`sops exec-env secrets/<env>.enc.env '<command>'`); decrypted copies are never written to disk,
  and `.gitignore` ignores every other file in `secrets/`.

## Consequences

- Good: no secret in Git history in clear text, and access per environment is visible in one
  reviewed file.
- Good: losing the workstation does not lose the secrets (break-glass key).
- Bad: rotating a recipient means re-encrypting the files (`sops updatekeys`).
- Bad: a lost age key with no break-glass copy makes the files unreadable for good.
