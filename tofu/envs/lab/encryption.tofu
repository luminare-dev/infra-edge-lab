# State and plan encryption of this environment (OpenTofu only: Terraform and TFLint do not read
# .tofu files). The same file is in every environment.
#
# The passphrase comes from TF_VAR_state_passphrase: from the SOPS file of the environment
# (secrets/<env>.enc.env) for lab, demo and showcase, and a random one per run for local, whose
# state is thrown away with its containers. Keep it in the SOPS file and offline: without it the
# state cannot be read again.

variable "state_passphrase" {
  description = "Passphrase from which the state and plan encryption key is derived (PBKDF2), at least 16 characters."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.state_passphrase) >= 16
    error_message = "The state_passphrase must be at least 16 characters long."
  }
}

terraform {
  encryption {
    key_provider "pbkdf2" "main" {
      passphrase = var.state_passphrase
    }

    method "aes_gcm" "main" {
      keys = key_provider.pbkdf2.main
    }

    # enforced: OpenTofu refuses to write a state or plan file that is not encrypted with this
    # method, so a configuration mistake cannot fall back to clear text.
    state {
      method   = method.aes_gcm.main
      enforced = true
    }

    plan {
      method   = method.aes_gcm.main
      enforced = true
    }
  }
}
