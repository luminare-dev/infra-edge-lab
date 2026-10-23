#!/usr/bin/env bash
# End-to-end test of the tunnel (docs/adr/0024): the demo environment with substrate = docker, so
# its one host is a systemd container on the local Docker daemon, published through a real
# Cloudflare tunnel with its DNS records and Access applications, checked from outside through
# Cloudflare, and always taken down again. "task e2e:tunnel" and the CI workflow e2e-tunnel run
# this script; it works the same on a workstation and on a CI runner.
#
# Usage: scripts/e2e_tunnel.sh            the run
#        scripts/e2e_tunnel.sh cleanup    remove what an interrupted run left: its containers and,
#                                         through the sweeper, the Cloudflare objects it created
#
# Steps, each timed; the destroy, the sweep and the zone comparison run whatever happened before:
#   1. preflight: the token permissions, the zone ID, no unmanaged record under demo-*
#   2. a snapshot of every DNS record of the zone outside demo-* (kept in the work folder)
#   3. tofu init and plan of tofu/envs/demo (a copy in the work folder, local state encrypted
#      with a random passphrase of this run): tunnel demo-e2e, demo-web and demo-ssh with their
#      Access applications and service tokens, the container lab-e2e-demo-edge-01
#   4. preflight of the saved plan: it touches demo-* records only and none of them exists yet
#   5. tofu apply of exactly that plan, then the inventory from its outputs
#   6. the collections, playbooks/tunnel_e2e_prepare.yml (the test page) and playbooks/site.yml
#      with the tunnel token fetched for this one run (scripts/tunnel_token.py), then smoke.yml and
#      the test page through nginx on the host
#   7. through Cloudflare: the tunnel has a connector; https://demo-web.<zone>/ answers 200 with
#      the marker of this run with the service token, and a refusal without it; Ansible reaches
#      the host over SSH through demo-ssh (cloudflared access ssh with the other service token)
#   8. always: the connector stopped, tofu destroy, the containers removed, the sweeper for every
#      demo-* object created since the start of the run, and a second snapshot that must equal
#      the first one
# A summary with the timings is printed at the end and, in GitHub Actions, written to the job
# summary. Plans and applies are written to log files in the work folder, and only a summary by
# resource is printed (docs/adr/0023); in GitHub Actions every credential, ID and the zone are
# masked in the log.
#
# Needs: Docker (privileged containers), OpenTofu, ansible-playbook, ansible and ansible-galaxy
# (task puts the tools of requirements-test.txt first), python3, curl, ssh and ssh-keygen; the
# collections as for task e2e:local (or ANSIBLE_COLLECTIONS_PATH). cloudflared for the SSH check
# is downloaded at the pinned version and sha256 unless CLOUDFLARED names one.
# Credentials: CLOUDFLARE_API_TOKEN (the permissions that "task preflight ENV=demo" prints),
# TF_VAR_account_id, TF_VAR_zone_id, TF_VAR_zone and TF_VAR_access_team_name, read from
# secrets/demo-e2e.enc.env (or the file named by SECRETS) through sops exec-env when that file
# exists, otherwise from the caller's environment. No cloud server is created and no Hetzner
# token is needed. The work folder is E2E_TUNNEL_DIR (default: infra-edge-lab-e2e-tunnel in
# RUNNER_TEMP or TMPDIR); it is removed at the end.
set -euo pipefail

cd "$(dirname "$0")/.."

# cloudflared on the control node, for "cloudflared access ssh" (docs/toolchain.md; the
# connector on the host comes from the cloudflared role).
CLOUDFLARED_VERSION=2026.10.2
CLOUDFLARED_SHA256=35fbdd2beb378436c7da377d7358cea8e33f9c94a6705d1d8036bf9b0d6d8005
# Names of this test: the tunnel, and the prefix of the container, its network and its image.
TUNNEL_NAME=demo-e2e
NAME_PREFIX=lab-e2e-
CONTAINER=${NAME_PREFIX}demo-edge-01
# The sweeper removes demo objects created after the start of the run, minus this margin for a
# clock difference between this machine and Cloudflare.
SWEEP_MARGIN_MINUTES=5

die() {
  echo "$0: $*" >&2
  exit 2
}

mode=run
case "${1:-}" in
  "") ;;
  cleanup) mode=cleanup ;;
  *) die "usage: $0 [cleanup]" ;;
esac

secrets=${SECRETS:-secrets/demo-e2e.enc.env}
if [ -n "${SECRETS:-}" ] && [ ! -f "$SECRETS" ]; then
  die "SECRETS names $SECRETS, which does not exist"
fi
if [ -f "$secrets" ] && [ "${SECRETS_LOADED:-}" != 1 ]; then
  command -v sops >/dev/null || die "sops is needed to read $secrets (docs/toolchain.md)"
  SECRETS_LOADED=1 TOFU_ENV_IN_SOPS=1 ENVIRONMENT_IN_SOPS=1 \
    exec sops exec-env "$secrets" "$(printf '%q ' bash scripts/e2e_tunnel.sh "$@")"
fi

# Every script that this one calls uses the credentials loaded here, never another SOPS file.
export SECRETS_LOADED=1 TOFU_ENV_IN_SOPS=1 ENVIRONMENT_IN_SOPS=1

umask 077
work=${E2E_TUNNEL_DIR:-${RUNNER_TEMP:-${TMPDIR:-/tmp}}/infra-edge-lab-e2e-tunnel}
tf="$work/repo/tofu/envs/demo"
repo=$PWD

# In GitHub Actions, never show a value of the account in the log, whatever prints it.
mask() {
  if [ "${GITHUB_ACTIONS:-}" = true ] && [ -n "${1:-}" ]; then
    printf '::add-mask::%s\n' "$1"
  fi
}

required=(CLOUDFLARE_API_TOKEN TF_VAR_account_id TF_VAR_zone_id TF_VAR_zone)
if [ "$mode" = run ]; then
  required+=(TF_VAR_access_team_name)
fi
for name in "${required[@]}"; do
  [ -n "${!name:-}" ] || die "$name is not set (from $secrets, or the caller's environment)"
done
zone=${TF_VAR_zone:-}
mask "$CLOUDFLARE_API_TOKEN"
mask "${TF_VAR_account_id:-}"
mask "${TF_VAR_zone_id:-}"
mask "$zone"
mask "${TF_VAR_access_team_name:-}"

for tool in docker python3; do
  command -v "$tool" >/dev/null || die "$tool is not on the PATH"
done

# Every container, network and image of this test carries these labels and the name prefix.
our_containers() {
  docker ps -aq --filter label=managed-by=tofu --filter label=env=demo --filter "name=${NAME_PREFIX}demo-"
}

remove_containers() {
  local ids
  ids=$(our_containers)
  if [ -n "$ids" ]; then
    # shellcheck disable=SC2086 # one ID per word
    docker rm -f $ids >/dev/null
    echo "removed $(wc -w <<<"$ids") container(s) named ${NAME_PREFIX}demo-*"
  fi
  if docker network inspect "${NAME_PREFIX}demo" >/dev/null 2>&1; then
    docker network rm "${NAME_PREFIX}demo" >/dev/null && echo "removed the network ${NAME_PREFIX}demo"
  fi
  local images
  images=$(docker image ls -q --filter label=managed-by=tofu --filter label=env=demo \
    --filter "reference=${NAME_PREFIX}systemd-host-*")
  if [ -n "$images" ]; then
    # shellcheck disable=SC2086 # one ID per word
    docker image rm -f $images >/dev/null && echo "removed the host image ${NAME_PREFIX}systemd-host-*"
  fi
}

sweep() {
  local since status=0
  since=$(cat "$work/started-at") || return 1
  python3 scripts/cloudflare_api.py sweep --delete --created-after "$since" || status=1
  # A second pass must find nothing (a tunnel with a connector is kept and fails the first one).
  python3 scripts/cloudflare_api.py sweep --created-after "$since" >"$work/sweep-check.log" || status=1
  cat "$work/sweep-check.log"
  grep -q '^sweep: no left-over demo object' "$work/sweep-check.log" || status=1
  return "$status"
}

# Everything of the work folder but the start time, so that a later cleanup can sweep again.
keep_start_time_only() {
  find "$work" -mindepth 1 -maxdepth 1 ! -name started-at -exec rm -rf {} +
  echo "kept $work/started-at: run \"bash scripts/e2e_tunnel.sh cleanup\" to sweep again" >&2
}

if [ "$mode" = cleanup ]; then
  echo "=== cleanup"
  remove_containers
  if [ -f "$work/started-at" ]; then
    if ! sweep; then
      keep_start_time_only
      exit 1
    fi
  else
    echo "no started run in $work: nothing to sweep"
  fi
  rm -rf "$work"
  exit 0
fi

for tool in tofu ansible-playbook ansible ansible-galaxy curl ssh ssh-keygen tar; do
  command -v "$tool" >/dev/null || die "$tool is not on the PATH"
done
if [ -e "$work" ]; then
  die "$work is left from an earlier run: remove what it created with \"bash scripts/e2e_tunnel.sh cleanup\""
fi
if [ -n "$(our_containers)" ]; then
  die "containers named ${NAME_PREFIX}demo-* exist already: remove them with \"bash scripts/e2e_tunnel.sh cleanup\""
fi

TF_VAR_state_passphrase=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
marker=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')
# The demo with its host as a container of this test; the tunnel token is read by the configure
# step, never by a plan. No variable file of the operator is read (the copy has none).
export TF_VAR_state_passphrase TF_VAR_substrate=docker TF_VAR_tunnel_name=$TUNNEL_NAME \
  TF_VAR_name_prefix=$NAME_PREFIX TF_VAR_platform=debian13 TF_VAR_fetch_tunnel_token=false TF_IN_AUTOMATION=1
unset TUNNEL_TOKEN TF_VAR_hosts TF_VAR_allowed_emails
export ANSIBLE_NOCOLOR=1 ANSIBLE_FORCE_COLOR=0 PY_COLORS=0

summary=()
failed_step=""
current_step=""

# step <name> <command ...>: run one step, time it and remember the result. A step function runs
# without errexit (it is called in a "||" list), so each one returns its first failure itself.
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

# quiet <log> <command ...>: the output goes to a log file in the work folder; only the result
# lines are shown, and on a failure the error messages. OpenTofu ends a "... complete" line with
# the object's ID ("[id=...]"); the apply runs before the IDs of the run are known and masked, so
# the IDs are cut from every line shown (docs/adr/0023: a summary by resource only).
quiet() {
  local log=$1 status=0
  shift
  "$@" >"$log" 2>&1 || status=$?
  grep -E 'successfully initialized|(Creation|Destruction|Modifications) complete|^(Apply|Destroy) complete|^Plan:|No changes' \
    "$log" | sed -E 's/ \[id=[^]]*\]//g' || true
  if [ "$status" -ne 0 ]; then
    grep -E -A 6 'Error' "$log" | head -n 80 | sed -E 's/ \[id=[^]]*\]//g' >&2 || true
  fi
  return "$status"
}

tofu_demo() {
  tofu -chdir="$tf" "$@"
}

# A copy of the demo environment and the modules, without the operator's state, override and
# variable files, with a local state file instead of the R2 backend.
copy_environment() {
  mkdir -p "$work/repo" || return 1
  tar -cf - --exclude=.terraform --exclude='*.tfstate*' --exclude='*_override.tf' --exclude='*_override.tofu' \
    --exclude='override.tf' --exclude='override.tofu' --exclude='*.tfvars' --exclude='*.tfvars.json' \
    --exclude='tfplan' --exclude='*.tfplan' tofu/modules tofu/envs/demo images | tar -C "$work/repo" -xf - || return 1
  cat >"$tf/backend_override.tf" <<'EOF'
# Written by scripts/e2e_tunnel.sh: the state of the test stays in this copy, encrypted with the
# passphrase of the run (encryption.tofu), and is thrown away with it.
terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
EOF
}

do_init() {
  copy_environment || return 1
  quiet "$work/init.log" tofu_demo init -input=false -lockfile=readonly
}

do_plan() {
  quiet "$work/plan.log" tofu_demo plan -input=false -no-color -out="$work/tfplan" || return 1
  tofu_demo show -json "$work/tfplan" >"$work/plan.json" || return 1
  python3 scripts/plan_summary.py --title "Plan of the tunnel test (demo, substrate docker)" "$work/plan.json"
}

do_apply() {
  quiet "$work/apply.log" tofu_demo apply -input=false -no-color "$work/tfplan"
}

do_inventory() {
  mkdir -p "$work/inventory" || return 1
  ln -s "$repo/ansible/inventories/demo/group_vars" "$work/inventory/group_vars" || return 1
  tofu_demo output -json hosts | python3 scripts/render_inventory.py --env demo --output "$work/inventory/hosts.yml" \
    || return 1
  echo "$work/inventory/hosts.yml written"
}

# ansible-playbook from the ansible/ folder, where ansible.cfg is, on the inventory of this test.
playbook() {
  (cd ansible && ANSIBLE_CONFIG=ansible.cfg ansible-playbook -i "$work/inventory" -e "@$work/e2e-vars.json" "$@")
}

collections() {
  if [ -n "${ANSIBLE_COLLECTIONS_PATH:-}" ]; then
    echo "using the collections in ANSIBLE_COLLECTIONS_PATH=$ANSIBLE_COLLECTIONS_PATH"
    (cd ansible && ansible-galaxy collection list luminare.infra_edge && ansible-galaxy collection list luminare.gameserver)
    return
  fi
  (cd ansible && ansible-galaxy collection install -r requirements.yml)
}

# The values of this test that are not values of the demo environment: the site of demo-web,
# which proxies to the test page, and the marker that the page shows.
write_test_vars() {
  python3 - "$work/e2e-vars.json" "$zone" "$marker" <<'EOF'
import json, sys
path, zone, marker = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump({
        "tunnel_e2e_marker": marker,
        "nginx_sites": [{"name": "web", "server_name": f"demo-web.{zone}", "listen": "127.0.0.1:8080",
                         "upstream": "http://127.0.0.1:8000"}],
    }, handle, indent=1)
EOF
}

# One value of a map output: output_value <output> <key>.
output_value() {
  tofu_demo output -json "$1" | python3 -c 'import json, sys; print(json.load(sys.stdin)[sys.argv[1]])' "$2"
}

# The values that the checks through Cloudflare need, from the outputs; masked before any use.
read_outputs() {
  tunnel_id=$(tofu_demo output -raw tunnel_id) || return 1
  mask "$tunnel_id"
  web_id=$(output_value service_token_client_ids demo-web) || return 1
  ssh_id=$(output_value service_token_client_ids demo-ssh) || return 1
  web_secret=$(output_value service_token_client_secrets demo-web) || return 1
  ssh_secret=$(output_value service_token_client_secrets demo-ssh) || return 1
  local value
  for value in "$web_id" "$ssh_id" "$web_secret" "$ssh_secret"; do
    mask "$value"
  done
  printf 'CF-Access-Client-Id: %s\nCF-Access-Client-Secret: %s\n' "$web_id" "$web_secret" >"$work/web-headers"
}

do_configure() {
  read_outputs || return 1
  local token
  token=$(python3 scripts/tunnel_token.py --tunnel-id "$tunnel_id") || return 1
  mask "$token"
  TUNNEL_TOKEN=$token playbook playbooks/site.yml
}

# The smoke test of every environment, then the web origin of demo-web on the host itself: nginx
# must serve the test page with this run's marker (a status 200 alone could come from another site).
smoke_on_host() {
  playbook playbooks/smoke.yml || return 1
  local args
  args=$(python3 -c 'import json, sys
print(json.dumps({"url": "http://127.0.0.1:8080/", "return_content": True, "headers": {"Host": sys.argv[1]}}))' \
    "demo-web.$zone") || return 1
  (cd ansible && ANSIBLE_CONFIG=ansible.cfg ansible -i "$work/inventory" edge -m ansible.builtin.uri -a "$args") \
    >"$work/page.log" || { cat "$work/page.log"; return 1; }
  grep -qF "$marker" "$work/page.log" || { echo "nginx did not serve the test page for demo-web" >&2; return 1; }
  echo "nginx serves the test page for demo-web on 127.0.0.1:8080"
}

tunnel_connected() {
  python3 scripts/cloudflare_api.py tunnel-status --tunnel-id "$tunnel_id" --wait 180
}

# https://demo-web.<zone>/ through Cloudflare: 200 with the marker with the service token (the
# first answers can fail while the new name and the Access application reach the edge), then a
# refusal without it.
web_through_access() {
  local url="https://demo-web.$zone/" code="" attempt passed=false
  for attempt in $(seq 1 30); do
    rm -f "$work/web.html"
    code=$(curl -sS -o "$work/web.html" -w '%{http_code}' --max-time 20 -H "@$work/web-headers" "$url" || true)
    if [ "$code" = 200 ] && grep -qF "$marker" "$work/web.html" 2>/dev/null; then
      echo "with the service token: HTTP 200 with the marker of this run (attempt $attempt)"
      passed=true
      break
    fi
    echo "with the service token: HTTP ${code:-none} without the marker, retrying in 10 s (attempt $attempt of 30)"
    sleep 10
  done
  [ "$passed" = true ] || { echo "demo-web never served the test page with the service token" >&2; return 1; }
  rm -f "$work/web-refused.html"
  code=$(curl -sS -o "$work/web-refused.html" -w '%{http_code}' --max-time 20 "$url" || true)
  if grep -qF "$marker" "$work/web-refused.html" 2>/dev/null; then
    echo "without the service token the test page was served (HTTP $code): Access did not refuse" >&2
    return 1
  fi
  # 401 (service_auth_401_redirect of the module), 403, or a redirect to the Access login page.
  case "$code" in
    302 | 401 | 403)
      echo "without the service token: HTTP $code, refused by Access"
      ;;
    *)
      echo "without the service token: HTTP ${code:-none}, expected a refusal by Access (302, 401 or 403)" >&2
      return 1
      ;;
  esac
}

# Ansible over SSH through demo-ssh: cloudflared access ssh carries the connection to Access with
# the service token of demo-ssh (from its environment, never on a command line), the tunnel brings
# it to ssh://localhost:22 on the host, and the automation user logs in with the throwaway key.
ssh_through_access() {
  local cloudflared=${CLOUDFLARED:-$work/bin/cloudflared}
  if [ -z "${CLOUDFLARED:-}" ]; then
    [ "$(uname -s)-$(uname -m)" = Linux-x86_64 ] \
      || { echo "set CLOUDFLARED to a cloudflared binary: the pinned download is for Linux x86_64" >&2; return 1; }
    mkdir -p "$work/bin" || return 1
    curl -fsSL --retry 3 -o "$cloudflared" \
      "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-amd64" \
      || return 1
    echo "$CLOUDFLARED_SHA256  $cloudflared" | sha256sum -c --quiet - || return 1
    chmod 0700 "$cloudflared" || return 1
  fi
  "$cloudflared" --version || return 1
  python3 - "$work" "demo-ssh.$zone" "$cloudflared" <<'EOF' || return 1
import json, sys
work, host, cloudflared = sys.argv[1:]
args = (f'-o ProxyCommand="{cloudflared} access ssh --hostname %h" -o IdentitiesOnly=yes '
        f'-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={work}/known_hosts')
inventory = {"all": {"hosts": {"demo-ssh": {
    "ansible_host": host, "ansible_connection": "ansible.builtin.ssh", "ansible_user": "ansible",
    "ansible_ssh_private_key_file": f"{work}/ssh_key", "ansible_ssh_common_args": args}}}}
with open(f"{work}/ssh-inventory.yml", "w", encoding="utf-8") as handle:
    json.dump(inventory, handle, indent=1)
with open(f"{work}/ssh-ansible.cfg", "w", encoding="utf-8") as handle:
    handle.write("[defaults]\ninterpreter_python = auto_silent\n")
EOF
  local attempt
  for attempt in $(seq 1 12); do
    if TUNNEL_SERVICE_TOKEN_ID=$ssh_id TUNNEL_SERVICE_TOKEN_SECRET=$ssh_secret ANSIBLE_CONFIG="$work/ssh-ansible.cfg" \
      ansible -i "$work/ssh-inventory.yml" all -m ansible.builtin.ping; then
      echo "SSH through demo-ssh: pong (attempt $attempt)"
      return 0
    fi
    echo "SSH through demo-ssh failed, retrying in 10 s (attempt $attempt of 12)"
    sleep 10
  done
  return 1
}

destroy() {
  if [ -n "$(our_containers)" ]; then
    # The connector goes first, so that the tunnel has no connection when it is deleted.
    docker exec "$CONTAINER" systemctl stop cloudflared.service >/dev/null 2>&1 || true
  fi
  local status=0
  if [ -f "$tf/terraform.tfstate" ]; then
    quiet "$work/destroy.log" tofu_demo destroy -input=false -no-color -auto-approve || status=$?
  else
    echo "no state file: nothing to destroy"
  fi
  # Whatever the destroy left on the Docker daemon.
  remove_containers || status=1
  return "$status"
}

zone_unchanged() {
  python3 scripts/cloudflare_api.py snapshot --exclude-env demo --output "$work/zone-after.json" || return 1
  python3 scripts/cloudflare_api.py compare "$work/zone-before.json" "$work/zone-after.json"
}

finish() {
  local status=$?
  trap - EXIT
  if [ -n "$current_step" ]; then
    summary+=("| $current_step | interrupted | |")
    failed_step=${failed_step:-$current_step}
  fi
  local swept=true
  step "destroy" destroy || status=1
  step "sweep" sweep || { status=1; swept=false; }
  if [ -f "$work/zone-before.json" ]; then
    step "zone outside demo-* unchanged" zone_unchanged || status=1
  fi
  if [ -n "$(our_containers)" ]; then
    echo "containers named ${NAME_PREFIX}demo-* are left on the Docker daemon" >&2
    status=1
  fi
  {
    echo
    echo "## e2e:tunnel"
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
  if [ "$swept" = true ]; then
    rm -rf "$work"
  else
    keep_start_time_only
  fi
  exit "$status"
}

# The start of the run (minus the margin) is the oldest creation time the sweeper deletes; it is
# written before anything is created.
mkdir -p "$work"
chmod 0700 "$work"
trap finish EXIT
python3 -c 'import datetime as d, sys
start = d.datetime.now(d.timezone.utc) - d.timedelta(minutes=int(sys.argv[1]))
print(start.strftime("%Y-%m-%dT%H:%M:%SZ"))' "$SWEEP_MARGIN_MINUTES" >"$work/started-at"
ssh-keygen -q -t ed25519 -N "" -C tunnel-e2e -f "$work/ssh_key"
TF_VAR_ssh_public_key=$(cat "$work/ssh_key.pub")
export TF_VAR_ssh_public_key
write_test_vars

step "preflight" bash scripts/cf_preflight.sh demo
step "zone snapshot" python3 scripts/cloudflare_api.py snapshot --exclude-env demo --output "$work/zone-before.json"
step "tofu init" do_init
step "tofu plan" do_plan
step "preflight of the plan" bash scripts/cf_preflight.sh demo "$work/plan.json"
step "tofu apply" do_apply
step "inventory" do_inventory
step "collections" collections
step "prepare (test page)" playbook playbooks/tunnel_e2e_prepare.yml
step "configure (site.yml with the tunnel token)" do_configure
step "smoke (on the host)" smoke_on_host
step "tunnel connected" tunnel_connected
step "demo-web through Access" web_through_access
step "SSH through demo-ssh" ssh_through_access
