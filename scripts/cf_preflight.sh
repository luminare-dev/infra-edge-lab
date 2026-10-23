#!/usr/bin/env bash
# The Cloudflare check before an apply of lab, demo or showcase (docs/adr/0024): it prints the
# API token permissions the environment needs, checks what a read can show of them, and refuses
# (exit 1) when the zone holds a record outside the environment's managed names that the apply
# would touch. "task preflight ENV=<env>" and "task up ENV=<env>" run it, and so do the tunnel
# end-to-end test and the apply workflow, there with the saved plan.
#
# Usage: scripts/cf_preflight.sh <lab|demo|showcase> [plan.json]
#   Without a plan: every record whose label has the environment's prefix (lab-*, demo-*, show-*
#   or play) must carry the comment "managed-by-tofu env=<env>", so that no apply can collide
#   with a record this repository did not create.
#   With plan.json (tofu show -json of the saved plan): every DNS record the plan creates,
#   changes or deletes must have the environment's prefix; a record it creates must not exist
#   yet, and a record it changes or deletes must carry the comment. A tunnel or an Access
#   application that the plan creates must not exist yet either.
# In both cases the zone ID must belong to the zone (every record name ends with the zone).
#
# Credentials: CLOUDFLARE_API_TOKEN, TF_VAR_account_id, TF_VAR_zone_id and TF_VAR_zone, read from
# secrets/<env>.enc.env (or the file named by SECRETS) through sops exec-env when that file
# exists, otherwise from the caller's environment. Only reads are sent; nothing is changed.
set -euo pipefail

cd "$(dirname "$0")/.."

die() {
  echo "$0: $*" >&2
  exit 2
}

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  die "usage: $0 <lab|demo|showcase> [plan.json]"
fi
env=$1
plan_json=${2:-}
case "$env" in
  lab | demo | showcase) ;;
  local) die "the local environment has no Cloudflare objects: nothing to check" ;;
  *) die "unknown environment '$env' (lab, demo or showcase)" ;;
esac
if [ -n "$plan_json" ] && [ ! -f "$plan_json" ]; then
  die "$plan_json does not exist (tofu show -json <planfile> > $plan_json)"
fi

secrets=${SECRETS:-secrets/$env.enc.env}
if [ -n "${SECRETS:-}" ] && [ ! -f "$SECRETS" ]; then
  die "SECRETS names $SECRETS, which does not exist"
fi
if [ -f "$secrets" ] && [ "${SECRETS_LOADED:-}" != 1 ]; then
  command -v sops >/dev/null || die "sops is needed to read $secrets (docs/toolchain.md)"
  SECRETS_LOADED=1 exec sops exec-env "$secrets" "$(printf '%q ' bash scripts/cf_preflight.sh "$@")"
fi

python3 scripts/cloudflare_api.py permissions --env "$env"
echo
if [ -n "$plan_json" ]; then
  exec python3 scripts/cloudflare_api.py preflight --env "$env" --plan-json "$plan_json"
fi
exec python3 scripts/cloudflare_api.py preflight --env "$env"
