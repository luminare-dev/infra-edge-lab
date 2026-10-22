# Unit tests of the cf_access_app module with a mocked Cloudflare provider (no credentials, no
# network). The zone and the e-mail address are documentation values.

mock_provider "cloudflare" {}

variables {
  account_id     = "0123456789abcdef0123456789abcdef"
  zone           = "example.com"
  env            = "lab"
  allowed_emails = ["operator@example.com"]
  apps = {
    lab-pve    = {}
    lab-status = {}
    lab-tx     = {}
    lab-pveapi = { auth = "service_auth" }
  }
}

run "email_apps_share_one_allow_policy" {
  command = plan

  assert {
    condition     = length(cloudflare_zero_trust_access_policy.allow_emails) == 1
    error_message = "People should share one reusable allow policy."
  }

  assert {
    condition = (
      cloudflare_zero_trust_access_policy.allow_emails[0].decision == "allow" &&
      length(cloudflare_zero_trust_access_policy.allow_emails[0].include) == 1 &&
      one(cloudflare_zero_trust_access_policy.allow_emails[0].include).email.email == "operator@example.com"
    )
    error_message = "The allow policy should admit exactly the listed e-mail addresses."
  }

  assert {
    condition     = cloudflare_zero_trust_access_policy.allow_emails[0].session_duration == "24h"
    error_message = "The login should last 24h by default."
  }
}

run "applications_cover_every_hostname" {
  command = plan

  assert {
    condition     = length(cloudflare_zero_trust_access_application.this) == 4
    error_message = "Every app should get one Access application."
  }

  assert {
    condition = alltrue([
      for name, app in cloudflare_zero_trust_access_application.this :
      app.domain == "${name}.example.com" && app.destinations[0].uri == "${name}.example.com" && app.destinations[0].type == "public"
    ])
    error_message = "Each application should protect exactly <label>.<zone>."
  }

  assert {
    condition = alltrue([
      for app in cloudflare_zero_trust_access_application.this : app.type == "self_hosted" && app.app_launcher_visible == false
    ])
    error_message = "Applications should be self-hosted and hidden from the App Launcher by default."
  }
}

run "service_auth_app_has_its_own_token" {
  command = apply

  assert {
    condition     = keys(cloudflare_zero_trust_access_service_token.this) == ["lab-pveapi"]
    error_message = "Only the service_auth app should get a service token."
  }

  assert {
    condition     = cloudflare_zero_trust_access_service_token.this["lab-pveapi"].duration == "8760h"
    error_message = "A service token should last one year by default."
  }

  assert {
    condition = (
      cloudflare_zero_trust_access_policy.service_auth["lab-pveapi"].decision == "non_identity" &&
      one(cloudflare_zero_trust_access_policy.service_auth["lab-pveapi"].include).service_token.token_id == cloudflare_zero_trust_access_service_token.this["lab-pveapi"].id
    )
    error_message = "The service_auth app should use a Service Auth policy bound to its own token."
  }

  assert {
    condition = (
      cloudflare_zero_trust_access_application.this["lab-pveapi"].policies[0].id == cloudflare_zero_trust_access_policy.service_auth["lab-pveapi"].id &&
      cloudflare_zero_trust_access_application.this["lab-pve"].policies[0].id == cloudflare_zero_trust_access_policy.allow_emails[0].id
    )
    error_message = "Each application should use the policy that matches its auth."
  }

  assert {
    condition     = cloudflare_zero_trust_access_application.this["lab-pveapi"].service_auth_401_redirect == true
    error_message = "A machine-facing application should answer 401 instead of redirecting to a login page."
  }

  assert {
    condition     = keys(output.aud_tags) == ["lab-pve", "lab-pveapi", "lab-status", "lab-tx"]
    error_message = "The aud_tags output should list every application."
  }
}

run "ssh_app_in_demo" {
  command = plan

  variables {
    env = "demo"
    apps = {
      demo-tx  = {}
      demo-ssh = { type = "ssh", auth = "service_auth" }
    }
  }

  assert {
    condition     = cloudflare_zero_trust_access_application.this["demo-ssh"].type == "ssh"
    error_message = "demo-ssh should be an SSH application."
  }

  assert {
    condition     = length(cloudflare_zero_trust_access_service_token.this) == 1
    error_message = "Only demo-ssh should get a service token."
  }
}

run "no_allow_policy_without_people" {
  command = plan

  variables {
    allowed_emails = []
    apps           = { lab-pveapi = { auth = "service_auth" } }
  }

  assert {
    condition     = length(cloudflare_zero_trust_access_policy.allow_emails) == 0
    error_message = "No allow policy should exist when no app uses email_otp."
  }
}

# A reserved name fails both the prefix rule and the denylist of var.apps; expect_failures cannot
# tell the two validations apart, so this run shows that the name is rejected, not by which rule.
run "rejects_reserved_hostname" {
  command = plan

  variables {
    apps = { www = {} }
  }

  expect_failures = [var.apps]
}

# The denylist is the second layer behind the prefix rule (as in the cf_tunnel module): this run
# checks what it holds and that no prefix matches a listed, _domainkey or dotted name.
run "denylist_is_a_second_layer" {
  command = plan

  assert {
    condition = alltrue([
      for n in ["", "@", "www", "mx", "scripts", "triage", "_dmarc", "mta-sts", "_mta-sts"] :
      contains(local.reserved_names, n)
    ])
    error_message = "The denylist should hold the apex, www, mx, scripts, triage, _dmarc, mta-sts and _mta-sts."
  }

  assert {
    condition = alltrue(flatten([
      for pattern in values(local.name_patterns) : [
        for n in concat(local.reserved_names, ["lab-s1_domainkey", "lab-pve.internal"]) : !can(regex(pattern, n))
      ]
    ]))
    error_message = "No environment prefix should match a reserved, _domainkey or dotted name; if one does, the denylist is the only guard for it and needs a run of its own."
  }
}

run "rejects_dotted_hostname" {
  command = plan

  variables {
    apps = { "lab-pve.internal" = {} }
  }

  expect_failures = [var.apps]
}

run "rejects_hostname_of_another_env" {
  command = plan

  variables {
    apps = { demo-tx = {} }
  }

  expect_failures = [var.apps]
}

run "rejects_unknown_type" {
  command = plan

  variables {
    apps = { lab-pve = { type = "saas" } }
  }

  expect_failures = [var.apps]
}

run "rejects_unknown_auth" {
  command = plan

  variables {
    apps = { lab-pve = { auth = "everyone" } }
  }

  expect_failures = [var.apps]
}

run "rejects_people_without_addresses" {
  command = plan

  variables {
    allowed_emails = []
  }

  expect_failures = [var.allowed_emails]
}

run "rejects_long_sessions" {
  command = plan

  variables {
    session_duration = "72h"
  }

  expect_failures = [var.session_duration]
}

run "rejects_tokens_longer_than_a_year" {
  command = plan

  variables {
    service_token_duration = "17520h"
  }

  expect_failures = [var.service_token_duration]
}
