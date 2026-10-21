# 0008. go-task as the single entry point

- **Status:** accepted
- **Date:** 2026-10-21

## Context

Working on the repository means running several tools in the right order with the right flags:
the repository checks, linters, the secret scan, the tests, and later the provisioning and
configuration steps per environment. Contributors and CI must run the same commands, and the
commands must be readable without knowing each tool.

## Considered options

1. A Makefile.
2. Shell scripts only.
3. go-task (`Taskfile.yml`).
4. just (`justfile`).

## Decision

Chosen option: 3, go-task 3.54.0 (pinned in [toolchain.md](../toolchain.md)), because it is one
static binary with a published checksum, its YAML file lists every target with a description
(`task --list`), and it supports variables per call (`task lint VENV=…`) without Make's tab and
quoting rules.

- `task lint` runs the checks of CI's `lint-test` job and the secret scan, plus `tofu fmt`.
- `task test` runs `scripts/run_tests.sh`, which is also the `test-command` of CI and of the
  release workflow, so the tests run the same way everywhere.
- CI does not depend on go-task: workflows call the scripts directly, so a broken task runner
  cannot hide a failing check.

## Consequences

- Good: one place to look for how anything is run; the same test command locally and in CI.
- Bad: one more binary to install and bump by hand.
