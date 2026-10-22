#!/usr/bin/env bash
# OpenTofu checks for every module and environment under tofu/. CI's "tofu" job runs each step
# on its own; "task tofu" runs them all.
#
# Usage: scripts/check_tofu.sh [step ...]   (default: all)
#   fmt          tofu fmt -check -recursive tofu
#   validate     tofu init (no backend, lock file read-only) and tofu validate in each directory
#   tflint       TFLint with .tflint.hcl in each directory
#   iac          IaC security scan: trivy config of tofu/ and of images/ (the host image), offline
#                with the checks built into the pinned release; accepted findings are listed with
#                their reason in .trivyignore.yaml
#   test         tofu test in each directory: mocked providers, no credentials
#   integration  the docker_host test against the local Docker daemon (real systemd containers)
#   compat       terraform validate on a copy of the code, with Terraform downloaded into a
#                throwaway directory (scripts/install_tofu_tools.sh) and removed afterwards
#   all          every step above in this order
# tofu, tflint and trivy must be on the PATH in the versions of docs/toolchain.md; "validate"
# and "test" download the providers named in each .terraform.lock.hcl from the OpenTofu registry.
set -euo pipefail
shopt -s nullglob

cd "$(dirname "$0")/.."
root=$PWD

# In CI, share one provider cache between the directories of a run.
if [ -z "${TF_PLUGIN_CACHE_DIR:-}" ] && [ -n "${RUNNER_TEMP:-}" ]; then
  export TF_PLUGIN_CACHE_DIR="$RUNNER_TEMP/tofu-plugin-cache"
fi
if [ -n "${TF_PLUGIN_CACHE_DIR:-}" ]; then
  mkdir -p "$TF_PLUGIN_CACHE_DIR"
fi
export TF_IN_AUTOMATION=1

# Every module and environment directory that holds .tf files, sorted.
code_dirs() {
  local dir files
  for dir in tofu/modules/*/ tofu/envs/*/; do
    files=("$dir"*.tf)
    if [ ${#files[@]} -gt 0 ]; then
      echo "${dir%/}"
    fi
  done
}

init() {
  tofu -chdir="$1" init -backend=false -input=false -lockfile=readonly >/dev/null
}

step_fmt() {
  echo "== tofu fmt -check -recursive tofu"
  tofu fmt -check -recursive -diff tofu
}

step_validate() {
  local dir
  for dir in $(code_dirs); do
    echo "== tofu validate: $dir"
    init "$dir"
    tofu -chdir="$dir" validate
  done
}

step_tflint() {
  local dir
  tflint --version
  for dir in $(code_dirs); do
    echo "== tflint: $dir"
    tflint --chdir="$dir" --config="$root/.tflint.hcl"
  done
}

# Each folder is scanned on its own; the paths in .trivyignore.yaml are relative to the folder
# that holds them. Any finding that is not listed there fails the step.
step_iac() {
  local dir
  trivy --version
  for dir in tofu images; do
    echo "== trivy config: $dir"
    trivy config --skip-check-update --skip-version-check --quiet --exit-code 1 \
      --ignorefile "$root/.trivyignore.yaml" "$dir"
  done
}

step_test() {
  local dir
  for dir in $(code_dirs); do
    echo "== tofu test: $dir"
    init "$dir"
    tofu -chdir="$dir" test
  done
}

step_integration() {
  echo "== tofu test (real Docker): tofu/modules/docker_host/integration"
  init tofu/modules/docker_host
  tofu -chdir=tofu/modules/docker_host test -test-directory=integration
}

# The body runs in a subshell, so the throwaway provider cache, the lock-file flag below and the
# clean-up trap end with this step and never reach the steps that follow it.
step_compat() (
  local work dir
  work=$(mktemp -d)
  # shellcheck disable=SC2064 # expand $work now: the trap runs when the subshell exits
  trap "rm -rf '$work'" EXIT
  bash scripts/install_tofu_tools.sh "$work/bin" terraform >/dev/null
  "$work/bin/terraform" version
  # A copy without lock files and provider downloads: Terraform resolves the providers from its
  # own registry and must never rewrite the committed OpenTofu lock files. Local state, plan and
  # override files of an environment stay out as well (an encrypted state is unreadable for
  # Terraform, and the check is about the committed code). The copy holds images/ as well,
  # because docker_host reads its Dockerfile.
  mkdir -p "$work/src"
  tar -c --exclude=.terraform --exclude=.terraform.lock.hcl \
    --exclude='*.tfstate' --exclude='*.tfstate.*' --exclude=tfplan --exclude='*.tfplan' \
    --exclude=override.tf --exclude='*_override.tf' tofu images | tar -x -C "$work/src"
  export TF_PLUGIN_CACHE_DIR="$work/plugins" TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE=true
  mkdir -p "$TF_PLUGIN_CACHE_DIR"
  for dir in $(code_dirs); do
    echo "== terraform validate: $dir"
    "$work/bin/terraform" -chdir="$work/src/$dir" init -backend=false -input=false >/dev/null
    "$work/bin/terraform" -chdir="$work/src/$dir" validate
  done
)

if [ $# -eq 0 ]; then
  set -- all
fi
for step in "$@"; do
  case "$step" in
    fmt | validate | tflint | iac | test | integration | compat) "step_$step" ;;
    all)
      for each in fmt validate tflint iac test integration compat; do
        "step_$each"
      done
      ;;
    *)
      echo "$0: unknown step '$step' (fmt, validate, tflint, iac, test, integration, compat or all)" >&2
      exit 2
      ;;
  esac
done
