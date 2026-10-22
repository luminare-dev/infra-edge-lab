# The local environment keeps its state in a file next to this one (git-ignored), encrypted
# like every other state (encryption.tofu). It holds container names and addresses only and is
# thrown away together with the containers.

terraform {
  backend "local" {
    path = "terraform.tfstate"
  }
}
