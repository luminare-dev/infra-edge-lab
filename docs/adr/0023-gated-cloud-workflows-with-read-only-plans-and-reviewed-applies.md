# 0023. Gated cloud workflows with read-only plans and reviewed applies

- **Status:** accepted
- **Date:** 2026-10-22

## Context

`lab`, `demo` and `showcase` need CI that shows a plan before a merge, applies only after a
review, and notices drift; plan 09 asks for `plan.yml`, `apply.yml` and `drift.yml`. The
repository is public: anyone with a GitHub account can read its logs and job summaries, a full
plan shows every attribute, and a pull request from a fork must never reach a credential. At this
version no account, bucket or SOPS file of these environments exists, and CI must stay green
without them.

## Considered options

1. No cloud workflows until the accounts exist.
2. Workflows with the credentials as repository secrets, run on every pull request.
3. Workflows that are off until a repository variable turns them on, with one GitHub environment
   per level of trust and the credentials in SOPS files.

## Decision

Chosen option: 3, because the code can be reviewed and tested now and turned on without a change.

- Every job of `plan`, `apply`, `drift` and `e2e-tunnel` has `if: vars.CLOUD_ENVS_ENABLED == 'true'`
  (a repository variable is a string): unset, the jobs are skipped and CI stays green.
- `plan` runs for pull requests that change `tofu/` and on demand, never for a fork or Dependabot.
  `plan` and `drift` run in the environment `lab-plan` (no reviewer), whose only secret
  `SOPS_AGE_KEY` decrypts the read-only files `secrets/<env>-ci.enc.env`; a plan never reads the
  tunnel token and runs with `-lock=false` (a read-only token cannot write the lock).
- `apply` (demo or showcase, on demand) shows a read-only plan first, then waits in the
  environment of its input (`demo` or `showcase`, the owner as required reviewer). It plans again
  with the tunnel token for the first boot, checks that plan against the zone (ADR 0024), applies
  exactly that plan, compares the zone outside the environment before and after, and configures
  and smoke-tests the hosts. A cloud server has no public SSH port: Ansible reaches it through
  `cloudflared access ssh` to `<env>-ssh` with that application's service token from the outputs
  and the private key in the SOPS file (`SSH_PRIVATE_KEY_B64`). `lab` is applied from the
  workstation only.
- Plans and applies write into log files on the runner; the log, the job summary and an issue get
  only `scripts/plan_summary.py`: resource addresses and actions, and the counts. No plan file
  leaves the runner (the one artifact is the anonymised drift report below), and the value of
  every key in `secrets/env.example` is masked in the log.
- `drift` plans every night with `-detailed-exitcode`, skips an environment without resources
  and the lab while it is off, lists cloud servers labelled `env=demo` and left-over demo objects,
  and opens or updates the issue `Drift detected: <env>` with a report without zone or IDs. The
  jobs that decrypt the credentials can only read the repository; a second job without an
  environment or a secret, with the issues write permission only, posts the report, which it gets
  as an artifact of the run (kept for one day).
- One concurrency group per environment (`cloud-demo`, `cloud-showcase`), never cancelled, shared
  by every workflow that writes the same names.

## Consequences

- Good: nothing in a public log or issue shows more than the code does; forks get nothing.
- Good: the owner turns everything on with one variable once the environments, files and keys exist.
- Bad: none of the four workflows has run yet; the SSH path of `apply` through the tunnel is tested
  with stand-ins only.
- Bad: a read-only plan file holds the state's secrets while the job runs; the runner is
  ephemeral and the file is deleted at the end.
