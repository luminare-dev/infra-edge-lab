#!/usr/bin/env bash
# The cloud steps of the CI workflows plan, drift and apply (docs/adr/0023). Every one of them is
# behind the repository variable CLOUD_ENVS_ENABLED; this script is what they run once it is on.
#
# Usage: scripts/cloud_ci.sh <plan|drift|apply> <lab|demo|showcase>
#   plan   a read-only plan (secrets/<env>-ci.enc.env, no state lock): the summary by resource
#          goes to the log and the job summary, never the plan itself
#   drift  the same plan with -detailed-exitcode against an environment that exists; for demo
#          also the cloud servers labelled env=demo and the left-over demo-* objects in the zone.
#          Writes drift=true|false to GITHUB_OUTPUT and the report (no zone, no ID) to
#          $RUNNER_TEMP/drift-<env>.md for the issue "Drift detected: <env>"
#   apply  demo or showcase (lab is applied from the operator's workstation only): a plan that
#          reads the tunnel token for the first boot, the preflight of that plan
#          (scripts/cf_preflight.sh), a snapshot of the zone outside the environment, the apply
#          of exactly that plan, the same snapshot again (it must not differ), then the
#          inventory, configure and smoke (scripts/environment.sh) with secrets/<env>.enc.env
#
# Credentials come from the SOPS file, decrypted with the age key in SOPS_AGE_KEY (a secret of
# the job's GitHub environment, docs/runbook.md); the value of every key of secrets/env.example
# is masked in the log.
# A plan or drift run for an environment without its read-only file is skipped with a notice. The
# plan file and its JSON stay in a private folder of the runner and are never uploaded.
# lab is reached through Access (PROXMOX_VE_API_HEADERS); when it answers with a tunnel error,
# its plan reports "lab offline" and passes.
set -euo pipefail

cd "$(dirname "$0")/.."

die() {
  echo "$0: $*" >&2
  exit 2
}

if [ $# -ne 2 ]; then
  die "usage: $0 <plan|drift|apply> <lab|demo|showcase>"
fi
action=$1
env=$2
case "$action" in
  plan | drift) secrets=secrets/$env-ci.enc.env ;;
  apply) secrets=secrets/$env.enc.env ;;
  *) die "unknown action '$action' (plan, drift or apply)" ;;
esac
case "$env" in
  lab | demo | showcase) ;;
  *) die "unknown environment '$env' (lab, demo or showcase)" ;;
esac
if [ "$action" = apply ] && [ "$env" = lab ]; then
  die "lab is applied from the operator's workstation only: no write token of the lab leaves it (docs/adr/0023)"
fi

summary_file=${GITHUB_STEP_SUMMARY:-/dev/null}
output_file=${GITHUB_OUTPUT:-/dev/null}
work=${RUNNER_TEMP:-${TMPDIR:-/tmp}}/cloud-ci-$action-$env
report=${RUNNER_TEMP:-${TMPDIR:-/tmp}}/drift-$env.md

if [ ! -f "$secrets" ]; then
  if [ "$action" = apply ]; then
    die "$secrets does not exist: an apply of $env needs its write credentials (docs/runbook.md)"
  fi
  echo "::notice::$env: no read-only credentials ($secrets) in this commit, so there is nothing to $action: skipped"
  echo "$env: skipped, no $secrets in this commit" >>"$summary_file"
  [ "$action" = drift ] && echo "drift=false" >>"$output_file"
  exit 0
fi
if [ "${SECRETS_LOADED:-}" != 1 ]; then
  [ -n "${SOPS_AGE_KEY:-}" ] || die "SOPS_AGE_KEY is empty: the job's GitHub environment must hold the age key that decrypts $secrets"
  command -v sops >/dev/null || die "sops is needed to read $secrets (docs/toolchain.md)"
  SECRETS_LOADED=1 TOFU_ENV_IN_SOPS=1 ENVIRONMENT_IN_SOPS=1 SECRETS=$secrets \
    exec sops exec-env "$secrets" "$(printf '%q ' bash scripts/cloud_ci.sh "$@")"
fi

# Every value that a SOPS file can hold (the keys of secrets/env.example) is masked in the log,
# and so is each part of the Access headers.
mask() {
  if [ "${GITHUB_ACTIONS:-}" = true ] && [ -n "${1:-}" ]; then
    printf '::add-mask::%s\n' "$1"
  fi
}
while IFS='=' read -r key _; do
  mask "${!key:-}"
done < <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' secrets/env.example)
IFS=',' read -r -a header_parts <<<"${PROXMOX_VE_API_HEADERS:-}"
for part in "${header_parts[@]}"; do
  mask "${part#*=}"
done

rm -rf "$work"
mkdir -p "$work"
chmod 0700 "$work"
trap 'rm -rf "$work"' EXIT
dir="tofu/envs/$env"

# The zone, the account and the zone ID never reach a report that leaves the log (an issue).
anonymise() {
  python3 -c 'import os, sys
text = sys.stdin.read()
for key, name in (("TF_VAR_zone", "<zone>"), ("TF_VAR_account_id", "<account_id>"), ("TF_VAR_zone_id", "<zone_id>")):
    value = os.environ.get(key, "")
    if value:
        text = text.replace(value, name)
sys.stdout.write(text)'
}

# quiet <log> <command ...>: the output stays in a log file; on a failure only the error
# messages are shown.
quiet() {
  local log=$1 status=0
  shift
  "$@" >"$log" 2>&1 || status=$?
  if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then
    grep -E -A 6 'Error' "$log" | head -n 80 >&2 || true
  fi
  return "$status"
}

# lab is reached through its Access application; a tunnel error means the lab is switched off.
lab_online() {
  [ "$env" = lab ] || return 0
  [ -n "${PROXMOX_VE_ENDPOINT:-}" ] || die "PROXMOX_VE_ENDPOINT is not set in $secrets"
  : >"$work/pve-headers"
  local part
  for part in "${header_parts[@]}"; do
    [ -n "$part" ] && printf '%s: %s\n' "${part%%=*}" "${part#*=}" >>"$work/pve-headers"
  done
  local code
  code=$(curl -sS -o "$work/pve.body" -w '%{http_code}' --max-time 20 -H "@$work/pve-headers" \
    "${PROXMOX_VE_ENDPOINT%/}/api2/json/version" 2>/dev/null || true)
  case "${code:-000}" in
    000 | 502 | 503 | 504 | 52[0-9] | 530)
      echo "::notice::lab offline (HTTP ${code:-none} from its Access endpoint): skipped"
      echo "lab offline (HTTP ${code:-none}): skipped" >>"$summary_file"
      return 1
      ;;
  esac
  if grep -qE 'error code: (1016|1033)' "$work/pve.body" 2>/dev/null; then
    echo "::notice::lab offline (tunnel error from its Access endpoint): skipped"
    echo "lab offline: skipped" >>"$summary_file"
    return 1
  fi
}

summarise() {
  tofu -chdir="$dir" show -json "$work/tfplan" >"$work/plan.json"
  python3 scripts/plan_summary.py --title "$1" "$work/plan.json" | tee "$work/summary.md" >>"$summary_file"
  cat "$work/summary.md"
}

# Whether the state of the environment holds any resource (an environment that was destroyed,
# or never applied, has nothing to drift): exit 0 yes, 1 no, 2 the state could not be read.
state_has_resources() {
  tofu -chdir="$dir" show -json >"$work/state.json" || return 2
  python3 - "$work/state.json" <<'EOF'
import json, sys
try:
    state = json.load(open(sys.argv[1], encoding="utf-8"))
except ValueError:
    sys.exit(2)
def count(module):
    return len(module.get("resources", [])) + sum(count(m) for m in module.get("child_modules", []))
sys.exit(0 if count((state.get("values") or {}).get("root_module") or {}) else 1)
EOF
}

# demo only: cloud servers labelled env=demo (the demo is destroyed after each use) and demo-*
# objects in Cloudflare that no state holds any more. Exit 0 when it found something.
demo_leftovers() {
  local found=1
  if [ -n "${HCLOUD_TOKEN:-}" ]; then
    printf 'Authorization: Bearer %s\n' "$HCLOUD_TOKEN" >"$work/hcloud-headers"
    if curl -fsS --max-time 30 -H "@$work/hcloud-headers" \
      "https://api.hetzner.cloud/v1/servers?label_selector=env%3Ddemo" >"$work/servers.json"; then
      if python3 - "$work/servers.json" >"$work/servers.md" <<'EOF'; then
import json, sys
servers = json.load(open(sys.argv[1], encoding="utf-8")).get("servers") or []
for server in servers:
    print(f"- cloud server {server.get('name')} ({server.get('status')}), created {server.get('created')}")
sys.exit(0 if servers else 1)
EOF
        found=0
        { echo "Cloud servers labelled env=demo are running; the demo is destroyed after each use:"; echo
          cat "$work/servers.md"; echo; } >>"$work/report.md"
      fi
    else
      echo "::warning::demo: the cloud servers could not be listed"
    fi
  fi
  if python3 scripts/cloudflare_api.py sweep >"$work/sweep.log"; then
    if grep -q '^sweep: would' "$work/sweep.log"; then
      found=0
      { echo "demo-* objects in Cloudflare that no run removed (task sweep:demo lists and deletes them):"; echo
        grep '^sweep: would' "$work/sweep.log" | sed 's/^sweep: /- /'; echo; } >>"$work/report.md"
    fi
  else
    echo "::warning::demo: the left-over demo-* objects could not be listed"
  fi
  return "$found"
}

do_plan() {
  lab_online || return 0
  quiet "$work/init.log" bash scripts/tofu_env.sh init "$env" -lockfile=readonly
  local status=0
  quiet "$work/plan.log" bash scripts/tofu_env.sh plan "$env" -lock=false -no-color -out="$work/tfplan" || status=$?
  [ "$status" -eq 0 ] || return "$status"
  summarise "Plan of $env (read-only)"
}

do_drift() {
  : >"$work/report.md"
  local drift=false
  if lab_online; then
    quiet "$work/init.log" bash scripts/tofu_env.sh init "$env" -lockfile=readonly
    local exists=0
    state_has_resources || exists=$?
    [ "$exists" -le 1 ] || { echo "$0: the state of $env could not be read" >&2; return 1; }
    if [ "$exists" -eq 0 ]; then
      local status=0
      quiet "$work/plan.log" bash scripts/tofu_env.sh plan "$env" -lock=false -no-color -detailed-exitcode \
        -out="$work/tfplan" || status=$?
      case "$status" in
        0) summarise "Drift check of $env: no changes" ;;
        2)
          drift=true
          summarise "Drift check of $env: the plan has changes"
          { echo "The nightly plan of $env (read-only) differs from its state:"; echo
            sed '1,2d' "$work/summary.md"; echo; } >>"$work/report.md"
          ;;
        *) return "$status" ;;
      esac
    else
      echo "no $env environment exists (its state holds no resource): nothing to drift"
      echo "$env: no environment exists, skipped" >>"$summary_file"
    fi
  fi
  if [ "$env" = demo ] && demo_leftovers; then
    drift=true
  fi
  echo "drift=$drift" >>"$output_file"
  if [ "$drift" = true ]; then
    { cat "$work/report.md"
      echo "Run: ${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}/actions/runs/${GITHUB_RUN_ID:-}"
    } | anonymise >"$report"
    echo "::warning::$env: drift or a forgotten demo found (see the job summary)"
    cat "$report" >>"$summary_file"
  fi
}

do_apply() {
  quiet "$work/init.log" bash scripts/tofu_env.sh init "$env" -lockfile=readonly
  # A cloud server starts its connector at the first boot, so this plan reads the tunnel token
  # (write permission); it lands in the encrypted plan and state only (docs/adr/0011).
  quiet "$work/plan.log" env TF_VAR_fetch_tunnel_token=true \
    tofu -chdir="$dir" plan -input=false -no-color -out="$work/tfplan"
  summarise "Plan of $env (applied below)"
  bash scripts/cf_preflight.sh "$env" "$work/plan.json"
  python3 scripts/cloudflare_api.py snapshot --exclude-env "$env" --output "$work/zone-before.json"
  quiet "$work/apply.log" tofu -chdir="$dir" apply -input=false -no-color "$work/tfplan"
  grep -E '^Apply complete' "$work/apply.log"
  python3 scripts/cloudflare_api.py snapshot --exclude-env "$env" --output "$work/zone-after.json"
  python3 scripts/cloudflare_api.py compare "$work/zone-before.json" "$work/zone-after.json"
  bash scripts/environment.sh inventory "$env"
  bash scripts/environment.sh configure "$env"
  bash scripts/environment.sh smoke "$env"
}

case "$action" in
  plan) do_plan ;;
  drift) do_drift ;;
  apply) do_apply ;;
esac
