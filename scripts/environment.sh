#!/usr/bin/env bash
# One environment from the OpenTofu outputs to configured, checked hosts. The tasks up, configure,
# inventory, smoke, restore-test, destroy and rebuild of Taskfile.yml call it; scripts/e2e_local.sh
# runs the same steps for the local environment.
#
# Usage: scripts/environment.sh <action> <local|lab|demo|showcase> [ansible-playbook arguments ...]
#   inventory  ansible/inventories/<env>/hosts.yml from "tofu output -json" of the environment
#              (scripts/render_inventory.py); written only when the outputs are valid.
#   configure  playbooks/site.yml on the inventory (arguments go to ansible-playbook). For local,
#              playbooks/local_prepare.yml first and never a tunnel (TUNNEL_TOKEN is cleared). For
#              the others, the tunnel token is fetched from the API for the tunnel_id output
#              (scripts/tunnel_token.py) and exists only in the environment of the playbook run;
#              a TUNNEL_TOKEN that is already set is used as it is.
#   smoke      playbooks/smoke.yml: web server, database, game server and Prometheus targets,
#              checked on each host through the inventory's connection.
#   restore-test
#              playbooks/restore_test.yml: the restore test of the backups on every host
#              (-e restore_test_backup_now=true takes the dumps and a backup first).
#   up         init, apply, inventory, configure and smoke in one go. The apply of local is
#              approved automatically (containers on the local Docker daemon only); every other
#              environment's apply asks first unless AUTO_APPROVE=1.
#   destroy    tofu destroy (local: without asking), then the generated inventory and, for
#              local, the empty state file and the generated secrets. Refused for showcase.
#   rebuild    destroy, then up, with the time it took. Refused for showcase (docs/adr/0014).
#
# Credentials and the state passphrase come from secrets/<env>.enc.env through sops exec-env when
# that file exists (scripts/tofu_env.sh), otherwise from the caller's environment; the local
# environment needs only TF_VAR_state_passphrase. ansible-playbook comes from the PATH (task
# puts the hash-pinned tools of requirements-test.txt first), the collections from
# ansible/requirements.yml ("task collections"; or the path in ANSIBLE_COLLECTIONS_PATH).
set -euo pipefail

cd "$(dirname "$0")/.."

die() {
  echo "$0: $*" >&2
  exit 2
}

if [ $# -lt 2 ]; then
  die "usage: $0 <inventory|configure|smoke|restore-test|up|destroy|rebuild> <local|lab|demo|showcase> [arguments ...]"
fi
action=$1
env=$2
shift 2

case "$action" in
  inventory | configure | smoke | restore-test | up | destroy | rebuild) ;;
  *) die "unknown action '$action' (inventory, configure, smoke, restore-test, up, destroy or rebuild)" ;;
esac
case "$env" in
  local | lab | demo | showcase) ;;
  *) die "unknown environment '$env' (local, lab, demo or showcase)" ;;
esac
if [ "$env" = showcase ] && { [ "$action" = destroy ] || [ "$action" = rebuild ]; }; then
  die "refusing to $action showcase: it is the protected long-lived environment (docs/adr/0014), taken down by hand only"
fi

inventory_dir="ansible/inventories/$env"
hosts_file="$inventory_dir/hosts.yml"
secrets=${SECRETS:-secrets/$env.enc.env}

# ansible-playbook from the ansible/ folder, where ansible.cfg is.
playbook() {
  (cd ansible && ANSIBLE_CONFIG=ansible.cfg ansible-playbook -i "inventories/$env" "$@")
}

require_inventory() {
  [ -f "$hosts_file" ] || die "$hosts_file does not exist: run \"task inventory ENV=$env\" (after the apply) first"
}

do_inventory() {
  local outputs
  outputs=$(bash scripts/tofu_env.sh output "$env" -json)
  printf '%s\n' "$outputs" | python3 scripts/render_inventory.py --env "$env" --output "$hosts_file"
  echo "$hosts_file written"
}

do_configure() {
  require_inventory
  command -v ansible-playbook >/dev/null || die "ansible-playbook is not on the PATH (task venv, then use the task targets)"
  if [ "$env" = local ]; then
    # The local environment has no tunnel (docs/adr/0014): a token from the caller's shell never
    # reaches its containers.
    unset TUNNEL_TOKEN
    playbook playbooks/local_prepare.yml
    playbook playbooks/site.yml "$@"
    return
  fi
  # The tunnel token and the API credentials exist only inside sops exec-env: run this step
  # again in there, as a child, so that "up" goes on with the smoke test afterwards.
  if [ -f "$secrets" ] && [ "${ENVIRONMENT_IN_SOPS:-}" != 1 ]; then
    command -v sops >/dev/null || die "sops is needed to read $secrets (docs/toolchain.md)"
    ENVIRONMENT_IN_SOPS=1 TOFU_ENV_IN_SOPS=1 sops exec-env "$secrets" \
      "$(printf '%q ' bash scripts/environment.sh configure "$env" "$@")"
    return
  fi
  if [ -z "${TUNNEL_TOKEN:-}" ]; then
    local tunnel_id
    tunnel_id=$(bash scripts/tofu_env.sh output "$env" -raw tunnel_id)
    TUNNEL_TOKEN=$(python3 scripts/tunnel_token.py --tunnel-id "$tunnel_id")
  fi
  export TUNNEL_TOKEN
  playbook playbooks/site.yml "$@"
}

do_smoke() {
  require_inventory
  playbook playbooks/smoke.yml "$@"
}

do_restore_test() {
  require_inventory
  playbook playbooks/restore_test.yml "$@"
}

do_destroy() {
  local approve=()
  if [ "$env" = local ] || [ "${AUTO_APPROVE:-}" = 1 ]; then
    approve=(-auto-approve)
  fi
  if [ "$env" = local ] && [ ! -f tofu/envs/local/terraform.tfstate ]; then
    # An apply always writes the state, so without it nothing of local exists (for example
    # before the first "task rebuild ENV=local").
    echo "local has no state file: nothing to destroy"
  else
    bash scripts/tofu_env.sh destroy "$env" "${approve[@]}"
  fi
  rm -f "$hosts_file"
  if [ "$env" = local ]; then
    # Everything of this run is gone: the state (now empty, but encrypted with this run's
    # passphrase, which the next run would not know) and the throwaway secrets, SSH key and fake
    # build (playbooks/local_prepare.yml).
    rm -f tofu/envs/local/terraform.tfstate tofu/envs/local/terraform.tfstate.backup
    rm -rf "$inventory_dir/.generated"
  fi
  echo "$env destroyed; $hosts_file removed"
}

do_up() {
  local approve=()
  if [ "$env" = local ] || [ "${AUTO_APPROVE:-}" = 1 ]; then
    approve=(-auto-approve)
  fi
  bash scripts/tofu_env.sh init "$env"
  bash scripts/tofu_env.sh apply "$env" "${approve[@]}"
  do_inventory
  do_configure "$@"
  do_smoke
}

case "$action" in
  inventory) do_inventory ;;
  configure) do_configure "$@" ;;
  smoke) do_smoke "$@" ;;
  restore-test) do_restore_test "$@" ;;
  destroy) do_destroy ;;
  up) do_up "$@" ;;
  rebuild)
    start=$SECONDS
    do_destroy
    do_up "$@"
    echo "rebuild of $env took $((SECONDS - start)) s"
    ;;
esac
