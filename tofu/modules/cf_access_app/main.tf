# Cloudflare Access in front of the tunnel hostnames: one reusable "allow" policy for people
# (a one-time PIN sent to a listed e-mail address) and, for each machine-facing application, a
# Service Auth policy bound to a service token of its own.

locals {
  email_apps   = { for name, app in var.apps : name => app if app.auth == "email_otp" }
  service_apps = { for name, app in var.apps : name => app if app.auth == "service_auth" }
}

resource "cloudflare_zero_trust_access_policy" "allow_emails" {
  count = length(local.email_apps) > 0 ? 1 : 0

  account_id       = var.account_id
  name             = "${var.env} allow listed e-mail addresses"
  decision         = "allow"
  include          = [for email in var.allowed_emails : { email = { email = email } }]
  session_duration = var.session_duration
}

resource "cloudflare_zero_trust_access_service_token" "this" {
  for_each = local.service_apps

  account_id = var.account_id
  name       = "${each.key} service token"
  duration   = var.service_token_duration
}

resource "cloudflare_zero_trust_access_policy" "service_auth" {
  for_each = local.service_apps

  account_id = var.account_id
  name       = "${each.key} service auth"
  # "non_identity" is the Service Auth action: a request must carry the token headers
  # CF-Access-Client-Id and CF-Access-Client-Secret; there is no login page.
  decision = "non_identity"
  include  = [{ service_token = { token_id = cloudflare_zero_trust_access_service_token.this[each.key].id } }]
}

resource "cloudflare_zero_trust_access_application" "this" {
  for_each = var.apps

  account_id           = var.account_id
  name                 = each.key
  type                 = each.value.type
  domain               = "${each.key}.${var.zone}"
  destinations         = [{ type = "public", uri = "${each.key}.${var.zone}" }]
  session_duration     = var.session_duration
  app_launcher_visible = false
  allowed_idps         = each.value.auth == "email_otp" && length(var.allowed_idps) > 0 ? var.allowed_idps : null
  # Machines get a plain 401 instead of a redirect to a login page they cannot use.
  service_auth_401_redirect = each.value.auth == "service_auth" ? true : null

  policies = [{
    id = (
      each.value.auth == "service_auth"
      ? cloudflare_zero_trust_access_policy.service_auth[each.key].id
      : cloudflare_zero_trust_access_policy.allow_emails[0].id
    )
    precedence = 1
  }]
}
