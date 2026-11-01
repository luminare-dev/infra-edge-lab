# The local environment: the hosts of the lab as systemd containers on the local Docker daemon,
# for a workstation or a CI runner. No Cloudflare, no hypervisor and no cloud
# account: nothing in it needs a credential, so it can run on every pull request, forks included.

# The local daemon: DOCKER_HOST, or the default socket.
provider "docker" {}

module "hosts" {
  source = "../../modules/docker_host"

  env         = "local"
  hosts       = var.hosts
  platform    = var.platform
  name_prefix = var.name_prefix
  subnet      = var.subnet
  keep_image  = var.keep_image
}
