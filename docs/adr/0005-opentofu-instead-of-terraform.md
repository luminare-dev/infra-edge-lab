# 0005. OpenTofu instead of Terraform

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The environment (virtual machines, DNS records, tunnel and access rules) is described as code
and applied with one CLI. The repository is Apache-2.0 and public, its state holds credentials,
and a reader may want to run the same code with Terraform. Terraform is under the Business
Source License 1.1 since version 1.6; OpenTofu is its MPL-2.0 fork under the Linux Foundation,
reads the same HCL and providers, and encrypts state and plan files on its own (since 1.7).

## Considered options

1. Terraform.
2. OpenTofu, with the `.tf` files kept compatible with Terraform.
3. OpenTofu using its own syntax everywhere.

## Decision

Chosen option: 2, OpenTofu 1.13.1 (pinned in [toolchain.md](../toolchain.md)), because it is
open source, encrypts state without an extra service, and still lets Terraform users read and
validate the code. The rules that follow:

- `.tf` files contain only syntax that Terraform also accepts. Settings that only OpenTofu knows,
  such as the state and plan encryption block, go into `.tofu` files, which OpenTofu reads in
  place of a `.tf` file of the same name and which Terraform and TFLint ignore.
- The code lives in `tofu/`: reusable modules in `tofu/modules/`, one root module with its own
  state per environment in `tofu/envs/`.
- Provider credentials are read from environment variables only, never from files in the
  repository.

## Consequences

- Good: no licence question for users of the public code; encrypted state needs no wrapper.
- Good: reviewers who know Terraform can read every `.tf` file without learning a new syntax.
- Bad: features that exist only in OpenTofu (for example dynamic `prevent_destroy`) cannot be
  used in `.tf` files; provider-level protection flags are used instead.
- Bad: two tools must be checked when the compatibility promise is tested.
