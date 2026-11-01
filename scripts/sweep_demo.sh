#!/usr/bin/env bash
# The sweeper of the demo environment: "task sweep:demo" lists the demo objects
# that are left in Cloudflare after a run that could not destroy them, and
# "task sweep:demo -- --delete" removes them. The objects are those that the cf_tunnel and
# cf_access_app modules create for demo, recognised by their names and markers:
#   Access applications demo-* for demo-*.<zone>, the policies "demo-* service auth" and
#   "demo allow listed e-mail addresses", the service tokens "demo-* service token",
#   DNS records demo-*.<zone> with the comment "managed-by-tofu env=demo", and tunnels demo-*.
# A tunnel that has a connector is never deleted. Nothing of lab or showcase matches.
#
# The demo has no long-lived objects, so anything listed is left over, unless a demo is in use
# right now (an apply of demo, or a tunnel test that is running): list first, and delete only
# then. The tunnel test itself sweeps with --created-after (its own start), so it never touches
# what existed before it.
#
# Usage: scripts/sweep_demo.sh [--delete] [--created-after <ISO 8601 time>]
# Credentials: CLOUDFLARE_API_TOKEN, TF_VAR_account_id, TF_VAR_zone_id and TF_VAR_zone, read from
# secrets/demo.enc.env (or the file named by SECRETS) through sops exec-env when that file exists,
# otherwise from the caller's environment.
set -euo pipefail

cd "$(dirname "$0")/.."

die() {
  echo "$0: $*" >&2
  exit 2
}

for arg in "$@"; do
  case "$arg" in
    --delete | --created-after | --created-after=* | [0-9]*) ;;
    *) die "usage: $0 [--delete] [--created-after <ISO 8601 time>]" ;;
  esac
done

secrets=${SECRETS:-secrets/demo.enc.env}
if [ -n "${SECRETS:-}" ] && [ ! -f "$SECRETS" ]; then
  die "SECRETS names $SECRETS, which does not exist"
fi
if [ -f "$secrets" ] && [ "${SECRETS_LOADED:-}" != 1 ]; then
  command -v sops >/dev/null || die "sops is needed to read $secrets (docs/toolchain.md)"
  SECRETS_LOADED=1 exec sops exec-env "$secrets" "$(printf '%q ' bash scripts/sweep_demo.sh "$@")"
fi

exec python3 scripts/cloudflare_api.py sweep "$@"
