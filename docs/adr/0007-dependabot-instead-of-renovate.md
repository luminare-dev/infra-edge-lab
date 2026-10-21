# 0007. Dependabot instead of Renovate

- **Status:** accepted
- **Date:** 2026-10-21

## Context

Three kinds of pins need regular updates: the commit SHAs of workflow actions, the hash-pinned
Python tools and the OpenTofu providers of every module and environment. Each update pull request
must pass the PR-title check (a Conventional Commit type) like any other pull request. The
organization's template already configures Dependabot for actions and Python tools.

## Considered options

1. Renovate (GitHub App).
2. Dependabot version updates.
3. Manual updates only.

## Decision

Chosen option: 2, because it needs no third-party app installed on the organization, the template
configuration already passes the PR-title check, and it covers all three kinds of pins:

- `github-actions` (prefix `ci`), `pip` (prefix `build`; it recompiles `requirements-test.txt`
  from `requirements-test.in` with pip-compile) and `opentofu` (prefix `build`), each with
  `include: scope`, the `dependencies` label and a 7-day cooldown.
- The `opentofu` ecosystem (supported since December 2025) is used rather than `terraform`,
  because the providers are resolved from the OpenTofu registry and the lock files are written
  by OpenTofu. It watches `tofu/modules/*` and `tofu/envs/*`, so every new module or environment
  is covered without a configuration change.
- Provider updates come as one weekly group; `bpg/proxmox`, which is below 1.0 and may break in a
  minor release, gets its own pull request.

## Consequences

- Good: one tool, configured in one reviewed file; no app permission to grant.
- Good: every update pull request runs the full CI before it can be merged, and it can pass
  without a hand edit: the versions of the Python tools are written only in the requirements
  files, and [toolchain.md](../toolchain.md) and the README name those files instead.
- Bad: binaries pinned by version and sha256 (OpenTofu CLI, go-task, gitleaks and others in
  [toolchain.md](../toolchain.md)) are not seen by Dependabot and are bumped by hand monthly.
- Bad: Renovate's finer controls (for example custom regex managers for those binaries) are not
  available.
