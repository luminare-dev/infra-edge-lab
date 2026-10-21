# TFLint configuration for every module and environment under tofu/ (docs/toolchain.md has the
# TFLint version). scripts/check_tofu.sh runs "tflint --chdir=<dir> --config=<this file>" for
# each directory. Only the Terraform ruleset bundled with TFLint is used, so "tflint --init"
# downloads nothing.

config {
  # Lint the module calls of an environment together with the local modules they call.
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

# Rules on top of the "recommended" preset.
rule "terraform_documented_variables" {
  enabled = true
}

rule "terraform_documented_outputs" {
  enabled = true
}

rule "terraform_naming_convention" {
  enabled = true
}

rule "terraform_standard_module_structure" {
  enabled = true
}

rule "terraform_comment_syntax" {
  enabled = true
}

rule "terraform_unused_required_providers" {
  enabled = true
}
