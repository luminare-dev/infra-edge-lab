#!/usr/bin/env bash
# End-to-end test of the local environment: rebuild it from nothing, configure it twice, check
# that nothing drifts, smoke-test it and throw it away again. "task e2e:local" and the CI
# workflow e2e-local run this script; it needs Docker (privileged containers), OpenTofu,
# ansible-playbook and ansible-galaxy on the PATH (task puts the tools of requirements-test.txt
# first), and no account and no secret.
#
# Steps, each timed; the destroy runs whatever happened before it:
#   1. tofu init and apply of tofu/envs/local: edge-01, db-01 and fx-01 as systemd containers
#   2. the inventory from the outputs (scripts/render_inventory.py)
#   3. the collections of ansible/requirements.yml into ansible/collections (skipped when
#      ANSIBLE_COLLECTIONS_PATH names a folder that already holds them)
#   4. playbooks/local_prepare.yml and playbooks/site.yml, the first run
#   5. playbooks/site.yml again: every host must report changed=0
#   6. tofu plan again: it must report no changes (-detailed-exitcode 0)
#   7. playbooks/smoke.yml: nginx 200 on loopback, MariaDB SELECT 1, the fake game server's
#      /info.json and every Prometheus target up, each checked inside its container
#   8. playbooks/restore_test.yml: on every host the database dumps (db) and a backup, then the
#      restore test of the newest snapshot
#   9. tofu destroy, and the generated inventory and secrets removed
# The state is encrypted with a random passphrase of this run (unless TF_VAR_state_passphrase is
# set) and lives only as long as the containers. A summary with the timings is printed at the
# end and, in GitHub Actions, written to the job summary. The log of each playbook run is kept
# in E2E_LOG_DIR (default: a temporary folder that is removed at the end).
set -euo pipefail

cd "$(dirname "$0")/.."

for tool in docker tofu ansible-playbook ansible-galaxy python3; do
  command -v "$tool" >/dev/null || { echo "$0: $tool is not on the PATH" >&2; exit 2; }
done

# A state file left by an earlier run belongs to containers that may still exist and is
# encrypted with that run's passphrase: never start over it.
if [ -f tofu/envs/local/terraform.tfstate ]; then
  echo "$0: tofu/envs/local/terraform.tfstate is left from an earlier run; destroy that run first" \
    "(TF_VAR_state_passphrase=<its passphrase> task destroy ENV=local), or, if no container named" \
    "lab-local-* exists any more, delete the file" >&2
  exit 2
fi

if [ -z "${TF_VAR_state_passphrase:-}" ]; then
  TF_VAR_state_passphrase=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
fi
export TF_VAR_state_passphrase
# The local environment has no tunnel; nothing here may ever start a connector.
unset TUNNEL_TOKEN
# Plain output, so that the recap lines can be read.
export ANSIBLE_NOCOLOR=1 ANSIBLE_FORCE_COLOR=0 PY_COLORS=0 TF_IN_AUTOMATION=1

log_dir=${E2E_LOG_DIR:-}
remove_log_dir=false
if [ -z "$log_dir" ]; then
  log_dir=$(mktemp -d)
  remove_log_dir=true
fi
mkdir -p "$log_dir"

summary=()
failed_step=""
current_step=""

# step <name> <command ...>: run one step, time it and remember the result.
step() {
  local name=$1 start status=0
  shift
  current_step=$name
  echo
  echo "=== $name"
  start=$(date +%s.%N)
  "$@" || status=$?
  local took
  took=$(python3 -c 'import sys; print(f"{float(sys.argv[2]) - float(sys.argv[1]):.1f}")' "$start" "$(date +%s.%N)")
  if [ "$status" -eq 0 ]; then
    summary+=("| $name | passed | $took |")
  else
    summary+=("| $name | failed (exit $status) | $took |")
    failed_step=${failed_step:-$name}
  fi
  current_step=""
  return "$status"
}

# A playbook run with its output in the log as well.
logged_playbook() {
  local log=$1
  shift
  bash scripts/environment.sh "$@" 2>&1 | tee "$log"
}

# Every PLAY RECAP line of the log must report changed=0, failed=0 and unreachable=0.
check_no_changes() {
  local log=$1 recap
  recap=$(grep -E '^[A-Za-z0-9._-]+ +: ok=[0-9]+ ' "$log" || true)
  if [ -z "$recap" ]; then
    echo "no PLAY RECAP in $log" >&2
    return 1
  fi
  echo "$recap"
  if grep -Ev ' changed=0 .* unreachable=0 +failed=0 ' <<<"$recap" >/dev/null; then
    echo "the second run changed something (the tasks marked \"changed:\" above):" >&2
    grep -E '^(changed|failed|fatal):' "$log" >&2 || true
    return 1
  fi
}

second_configure() {
  logged_playbook "$log_dir/site-2.log" configure local && check_no_changes "$log_dir/site-2.log"
}

plan_no_changes() {
  local status=0
  bash scripts/tofu_env.sh plan local -detailed-exitcode || status=$?
  case "$status" in
    0) echo "tofu plan: no changes" ;;
    2) echo "tofu plan found changes after the apply (exit 2)" >&2; return 1 ;;
    *) return "$status" ;;
  esac
}

collections() {
  if [ -n "${ANSIBLE_COLLECTIONS_PATH:-}" ]; then
    echo "using the collections in ANSIBLE_COLLECTIONS_PATH=$ANSIBLE_COLLECTIONS_PATH"
    (cd ansible && ansible-galaxy collection list luminare.infra_edge && ansible-galaxy collection list luminare.gameserver)
    return
  fi
  (cd ansible && ansible-galaxy collection install -r requirements.yml)
}

# Without a state file nothing was created (an apply writes the state also when it fails).
destroy() {
  if [ -f tofu/envs/local/terraform.tfstate ]; then
    bash scripts/environment.sh destroy local
  else
    echo "no state file: nothing to destroy"
  fi
}

finish() {
  local status=$?
  trap - EXIT
  if [ -n "$current_step" ]; then
    summary+=("| $current_step | interrupted | |")
    failed_step=${failed_step:-$current_step}
  fi
  step "destroy" destroy || status=1
  # Nothing of this run may be left on the Docker daemon.
  local left
  left=$(docker ps -aq --filter label=managed-by=tofu --filter label=env=local --filter name=lab-local- | wc -l)
  if [ "$left" -ne 0 ]; then
    echo "$left container(s) of the local environment are left on the Docker daemon" >&2
    status=1
  fi
  {
    echo
    echo "## e2e:local"
    echo
    echo "| Step | Result | Seconds |"
    echo "|---|---|---|"
    printf '%s\n' "${summary[@]}"
    echo
    if [ "$status" -eq 0 ]; then
      echo "Result: passed in ${SECONDS} s."
    else
      echo "Result: failed${failed_step:+ at \"$failed_step\"} (${SECONDS} s)."
    fi
  } | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  if [ "$remove_log_dir" = true ]; then
    rm -rf "$log_dir"
  fi
  exit "$status"
}
trap finish EXIT

step "tofu init" bash scripts/tofu_env.sh init local
step "tofu apply" bash scripts/tofu_env.sh apply local -auto-approve
step "inventory" bash scripts/environment.sh inventory local
step "collections" collections
step "configure (first run)" logged_playbook "$log_dir/site-1.log" configure local
step "configure (second run: changed=0)" second_configure
step "tofu plan (no changes)" plan_no_changes
step "smoke" bash scripts/environment.sh smoke local
step "restore test" bash scripts/environment.sh restore-test local -e restore_test_backup_now=true
