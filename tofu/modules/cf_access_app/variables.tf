# Inputs of the cf_access_app module. Application hostnames follow the same rules as the DNS
# names of the cf_tunnel module (guard.tf).

variable "account_id" {
  description = "Cloudflare account ID of the Zero Trust organization (32 hexadecimal characters)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.account_id))
    error_message = "The account_id must be a Cloudflare account ID: 32 lower-case hexadecimal characters."
  }
}

variable "zone" {
  description = "DNS zone of the protected hostnames, for example example.com. It is always passed in and never written in this repository."
  type        = string

  validation {
    condition     = can(regex("^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]{2,63}$", var.zone))
    error_message = "The zone must be a lower-case domain name without a trailing dot, for example example.com."
  }
}

variable "env" {
  description = "Environment that owns the applications: lab, demo or showcase. It selects the allowed hostname prefix."
  type        = string

  validation {
    condition     = contains(["lab", "demo", "showcase"], var.env)
    error_message = "The env must be one of lab, demo or showcase."
  }
}

variable "apps" {
  description = "Access applications keyed by first-level hostname label (lab-pve becomes lab-pve.<zone>). type is self_hosted or ssh; auth is email_otp (people: a one-time PIN sent to a listed address) or service_auth (machines: a service token of the application's own)."
  type = map(object({
    type = optional(string, "self_hosted")
    auth = optional(string, "email_otp")
  }))

  validation {
    condition     = length(var.apps) > 0
    error_message = "The apps map must hold at least one application."
  }

  validation {
    condition = alltrue([
      for n in keys(var.apps) :
      !contains(local.reserved_names, n) && !strcontains(n, "_domainkey") && !strcontains(n, ".")
    ])
    error_message = "The apps must not use the zone apex (@), a reserved name (www, mx, scripts, triage, _dmarc, mta-sts, _mta-sts, *._domainkey) or a dotted name."
  }

  validation {
    condition     = alltrue([for n in keys(var.apps) : can(regex(local.name_pattern, n))])
    error_message = "Every apps key must be a first-level label with the prefix of env: lab-* in lab, demo-* in demo, show-* or play in showcase."
  }

  validation {
    condition     = alltrue([for a in values(var.apps) : contains(["self_hosted", "ssh"], a.type)])
    error_message = "Each app type must be self_hosted or ssh."
  }

  validation {
    condition     = alltrue([for a in values(var.apps) : contains(["email_otp", "service_auth"], a.auth)])
    error_message = "Each app auth must be email_otp or service_auth."
  }
}

variable "allowed_emails" {
  description = "E-mail addresses that may log in to the email_otp applications. Required while at least one app uses email_otp."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for e in var.allowed_emails : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", e))])
    error_message = "Each allowed_emails entry must be an e-mail address."
  }

  validation {
    condition     = length(var.allowed_emails) > 0 || alltrue([for a in values(var.apps) : a.auth != "email_otp"])
    error_message = "The allowed_emails must not be empty while an app uses email_otp."
  }
}

variable "allowed_idps" {
  description = "IDs of the identity providers that the email_otp applications offer, for example the one-time PIN provider. Empty means every provider of the organization."
  type        = list(string)
  default     = []
}

variable "session_duration" {
  description = "How long a login to an application lasts, from 12h to 24h."
  type        = string
  default     = "24h"

  validation {
    condition     = can(regex("^(1[2-9]|2[0-4])h$", var.session_duration))
    error_message = "The session_duration must be a whole number of hours from 12h to 24h."
  }
}

variable "service_token_duration" {
  description = "Lifetime of each service token, at most one year (8760h), so that every token is rotated at least once a year."
  type        = string
  default     = "8760h"

  validation {
    condition     = can(regex("^[1-9][0-9]*h$", var.service_token_duration)) && try(tonumber(trimsuffix(var.service_token_duration, "h")) <= 8760, false)
    error_message = "The service_token_duration must be a whole number of hours, at most 8760h."
  }
}
