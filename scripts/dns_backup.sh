#!/usr/bin/env bash
# A copy of the whole DNS zone before an apply: the zone file from the Cloudflare
# API (GET /zones/<zone_id>/dns_records/export, BIND format), encrypted with age before it
# touches the disk, in a local folder. "task dns-backup ENV=<env>" and "task up" for lab, demo and
# showcase run it; the runbook explains how to restore a record from it.
#
# Usage: scripts/dns_backup.sh <lab|demo|showcase>
#   The environment selects the credentials only: every environment shares the one zone.
#   Output: $DNS_BACKUP_DIR (default backups/dns, git-ignored) /<UTC time>.zone.age, mode 0600.
#
# Recipients (who can decrypt the copy), in this order:
#   DNS_BACKUP_RECIPIENTS       age public keys (age1...), separated by spaces
#   DNS_BACKUP_RECIPIENTS_FILE  a file of public keys, one per line (age -R)
#   otherwise the public key of the operator's age key, the one SOPS uses:
#   SOPS_AGE_KEY_FILE, or ~/.config/sops/age/keys.txt; the copy is then decrypted once with
#   that key to prove it can be read.
#
# Credentials: CLOUDFLARE_API_TOKEN (Zone · DNS · Read is enough), TF_VAR_zone_id and TF_VAR_zone,
# read from secrets/<env>.enc.env (or the file named by SECRETS) through sops exec-env when that
# file exists, otherwise from the caller's environment. The clear text exists only in the pipe
# between the API call and age.
set -euo pipefail

cd "$(dirname "$0")/.."

die() {
  echo "$0: $*" >&2
  exit 2
}

if [ $# -ne 1 ]; then
  die "usage: $0 <lab|demo|showcase>"
fi
env=$1
case "$env" in
  lab | demo | showcase) ;;
  local) die "the local environment has no DNS zone: nothing to back up" ;;
  *) die "unknown environment '$env' (lab, demo or showcase)" ;;
esac

secrets=${SECRETS:-secrets/$env.enc.env}
if [ -n "${SECRETS:-}" ] && [ ! -f "$SECRETS" ]; then
  die "SECRETS names $SECRETS, which does not exist"
fi
if [ -f "$secrets" ] && [ "${SECRETS_LOADED:-}" != 1 ]; then
  command -v sops >/dev/null || die "sops is needed to read $secrets (docs/toolchain.md)"
  SECRETS_LOADED=1 exec sops exec-env "$secrets" "$(printf '%q ' bash scripts/dns_backup.sh "$@")"
fi

command -v age >/dev/null || die "age is needed to encrypt the copy (docs/toolchain.md)"

recipients=()
identity=""
if [ -n "${DNS_BACKUP_RECIPIENTS:-}" ]; then
  for key in $DNS_BACKUP_RECIPIENTS; do
    [[ "$key" =~ ^age1[0-9a-z]{20,}$ ]] || die "DNS_BACKUP_RECIPIENTS holds '$key', which is not an age public key"
    recipients+=(-r "$key")
  done
elif [ -n "${DNS_BACKUP_RECIPIENTS_FILE:-}" ]; then
  [ -s "$DNS_BACKUP_RECIPIENTS_FILE" ] || die "DNS_BACKUP_RECIPIENTS_FILE names $DNS_BACKUP_RECIPIENTS_FILE, which is missing or empty"
  recipients+=(-R "$DNS_BACKUP_RECIPIENTS_FILE")
else
  identity=${SOPS_AGE_KEY_FILE:-$HOME/.config/sops/age/keys.txt}
  [ -f "$identity" ] || die "no recipient: set DNS_BACKUP_RECIPIENTS (age public keys), or keep the operator's age key in $identity"
  command -v age-keygen >/dev/null || die "age-keygen is needed to read the public key of $identity"
  for key in $(age-keygen -y "$identity"); do
    recipients+=(-r "$key")
  done
  [ ${#recipients[@]} -gt 0 ] || die "$identity holds no age key"
fi

dir=${DNS_BACKUP_DIR:-backups/dns}
mkdir -p "$dir"
chmod 0700 "$dir"
target="$dir/$(date -u +%Y%m%dT%H%M%SZ).zone.age"
partial=$(mktemp "$dir/.partial.XXXXXX")
trap 'rm -f "$partial"' EXIT

# age writes into the partial file; only a complete export is renamed to its final name.
python3 scripts/cloudflare_api.py export | age --encrypt "${recipients[@]}" --output "$partial"
if [ -n "$identity" ]; then
  # wc reads to the end, so age never stops on a closed pipe.
  plain_bytes=$(age --decrypt --identity "$identity" "$partial" | wc -c)
  [ "$plain_bytes" -gt 0 ] || { echo "$0: the encrypted copy cannot be read back with $identity" >&2; exit 1; }
fi
chmod 0600 "$partial"
mv "$partial" "$target"
trap - EXIT
echo "dns-backup: $target ($(wc -c <"$target") bytes, sha256 $(sha256sum "$target" | cut -d' ' -f1))"
