#!/usr/bin/env bash
# OpenTofu in one environment under tofu/envs. The tasks of Taskfile.yml call it (task init
# ENV=lab, task plan ENV=lab, task test ENV=lab) and so does scripts/environment.sh (task up,
# task destroy, task inventory).
#
# Usage: scripts/tofu_env.sh <init|plan|test|apply|destroy|output> <local|lab|demo|showcase> [tofu arguments ...]
#   init     tofu init. lab, demo and showcase keep their state in the remote backend of
#            backend.tf; with BACKEND=local they keep it in a local file instead
#            (tofu/envs/<env>/terraform.tfstate, encrypted like the remote one): the script
#            writes the git-ignored tofu/envs/<env>/backend_override.tf, and removes it again
#            with BACKEND=remote (the default). The local environment always uses a local file.
#   plan     tofu plan, with fetch_tunnel_token set to false: a plan never reads the tunnel token.
#   test     tofu test with mocked providers: no backend, no credentials and no passphrase.
#   apply    tofu apply (it asks before it changes anything unless -auto-approve is given).
#   destroy  tofu destroy (asks the same way); refused for showcase, the protected long-lived
#            environment, which is never destroyed from here (docs/adr/0014).
#   output   tofu output (for example "output local -json"), the outputs only on standard output.
#
# Credentials and the state passphrase: when secrets/<env>.enc.env exists (or the file named by
# SECRETS, for example SECRETS=secrets/lab-ci.enc.env for a read-only plan), every action but
# test runs under "sops exec-env", so the values exist only in the environment of that one
# command and never on disk. Without the file they come from the caller's environment; for the
# local environment that is only TF_VAR_state_passphrase, for example a random one per run:
#   export TF_VAR_state_passphrase="$(openssl rand -base64 32)"
# Every action but test against the remote backend also needs AWS_ENDPOINT_URL_S3 (the R2
# endpoint), so that the S3 backend never contacts AWS instead.
set -euo pipefail

cd "$(dirname "$0")/.."

die() {
  echo "$0: $*" >&2
  exit 2
}

if [ $# -lt 2 ]; then
  die "usage: $0 <init|plan|test|apply|destroy|output> <local|lab|demo|showcase> [tofu arguments ...]"
fi
action=$1
env=$2
shift 2

case "$action" in
  init | plan | test | apply | destroy | output) ;;
  *) die "unknown action '$action' (init, plan, test, apply, destroy or output)" ;;
esac
case "$env" in
  local | lab | demo | showcase) ;;
  *) die "unknown environment '$env' (local, lab, demo or showcase)" ;;
esac
if [ "$action" = destroy ] && [ "$env" = showcase ]; then
  die "refusing to destroy showcase: it is the protected long-lived environment (docs/adr/0014); its server has delete protection, and it is taken down by hand only"
fi
backend=${BACKEND:-remote}
case "$backend" in
  remote | local) ;;
  *) die "BACKEND must be remote or local, not '$backend'" ;;
esac

dir="tofu/envs/$env"
override="$dir/backend_override.tf"
secrets=${SECRETS:-secrets/$env.enc.env}
if [ -n "${SECRETS:-}" ] && [ ! -f "$SECRETS" ]; then
  die "SECRETS names $SECRETS, which does not exist"
fi
export TF_IN_AUTOMATION=1

if [ "$action" = test ]; then
  tofu -chdir="$dir" init -backend=false -input=false -lockfile=readonly >/dev/null
  exec tofu -chdir="$dir" test "$@"
fi

# Run every action but test again under sops when the environment has an encrypted file.
if [ -f "$secrets" ] && [ "${TOFU_ENV_IN_SOPS:-}" != 1 ]; then
  command -v sops >/dev/null || die "sops is needed to read $secrets (docs/toolchain.md)"
  TOFU_ENV_IN_SOPS=1 exec sops exec-env "$secrets" "$(printf '%q ' bash scripts/tofu_env.sh "$action" "$env" "$@")"
fi

passphrase=${TF_VAR_state_passphrase:-}
if [ ${#passphrase} -lt 16 ]; then
  if [ "$env" = local ]; then
    die "TF_VAR_state_passphrase must hold the state passphrase (at least 16 characters); for the local environment export a random one per run: export TF_VAR_state_passphrase=\"\$(openssl rand -base64 32)\""
  fi
  die "TF_VAR_state_passphrase must hold the state passphrase of $env (at least 16 characters): keep it in $secrets (sops edit $secrets), which this script reads when it exists"
fi

# The remote backend takes the endpoint of the bucket from AWS_ENDPOINT_URL_S3 (backend.tf).
# Without it the S3 backend would send its requests, signed with the bucket's access key, to AWS.
# init follows BACKEND; every other action uses the backend that the last init chose (the
# override file exists exactly when that was BACKEND=local).
remote_state=false
if [ "$env" != local ]; then
  if [ "$action" = init ]; then
    if [ "$backend" = remote ]; then
      remote_state=true
    fi
  elif [ ! -f "$override" ]; then
    remote_state=true
  fi
fi
if [ "$remote_state" = true ] && [ -z "${AWS_ENDPOINT_URL_S3:-}" ]; then
  die "AWS_ENDPOINT_URL_S3 must hold the endpoint of the state bucket of $env (https://<account_id>.r2.cloudflarestorage.com): keep it in $secrets, or use BACKEND=local for a local state file"
fi

case "$action" in
  init)
    if [ "$env" != local ] && [ "$backend" = local ]; then
      cat >"$override" <<'EOF'
# Written by scripts/tofu_env.sh for BACKEND=local and ignored by git: the state of this
# environment stays in a local file, encrypted like the remote one (encryption.tofu).
# "task init ENV=<env>" without BACKEND=local removes this file again.
terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
EOF
      echo "$override written: the state of $env stays in $dir/terraform.tfstate"
    elif [ -f "$override" ]; then
      rm -f "$override"
      echo "$override removed: $env uses the backend of backend.tf"
    fi
    # -reconfigure: a change between the local and the remote backend never copies a state.
    exec tofu -chdir="$dir" init -input=false -reconfigure "$@"
    ;;
  plan)
    if [ -f "$override" ]; then
      echo "note: $env plans against its local state file ($override)"
    fi
    TF_VAR_fetch_tunnel_token=false exec tofu -chdir="$dir" plan -input=false "$@"
    ;;
  apply | destroy)
    # No -input=false: without -auto-approve, OpenTofu asks for the confirmation.
    exec tofu -chdir="$dir" "$action" "$@"
    ;;
  output)
    exec tofu -chdir="$dir" output "$@"
    ;;
esac
