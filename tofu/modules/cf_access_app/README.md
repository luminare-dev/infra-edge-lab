# cf_access_app

Cloudflare Access applications in front of the tunnel hostnames: people log in with a one-time
PIN sent to a listed e-mail address, machines send a service token. Hostnames follow the same
rules as in [cf_tunnel](../cf_tunnel/README.md#name-rules)
([ADR 0009](../../../docs/adr/0009-guard-rails-for-a-shared-dns-zone.md)).

- One reusable "allow" policy for every `email_otp` application, holding the listed addresses.
- For every `service_auth` application its own service token (one year by default) and a
  Service Auth policy (`decision = "non_identity"`) bound to it; the application answers `401`
  instead of redirecting a machine to a login page.
- Applications are hidden from the App Launcher. Sessions last 12 to 24 hours.

The one-time PIN identity provider is turned on once by hand in the Zero Trust dashboard; its
ID can be passed in `allowed_idps`.

## Usage

```hcl
module "access" {
  source = "../../modules/cf_access_app"

  account_id     = var.account_id
  zone           = var.zone # for example example.com; never written in the code
  env            = "lab"
  allowed_emails = var.allowed_emails
  apps = {
    lab-pve    = {}
    lab-tx     = {}
    lab-pveapi = { auth = "service_auth" }
  }
}
```

The provider reads its API token from `CLOUDFLARE_API_TOKEN`. It needs Access: Apps and Policies
Edit and, for service tokens, Access: Service Tokens Edit on the account.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `account_id` | string | | Cloudflare account ID of the Zero Trust organization. |
| `zone` | string | | DNS zone of the hostnames, for example `example.com`. |
| `env` | string | | `lab`, `demo` or `showcase`; selects the name rules. |
| `apps` | map(object) | | Applications keyed by label: `type` (`self_hosted` or `ssh`, default `self_hosted`), `auth` (`email_otp` or `service_auth`, default `email_otp`). |
| `allowed_emails` | list(string) | `[]` | Addresses that may log in; required while an app uses `email_otp`. |
| `allowed_idps` | list(string) | `[]` | Identity provider IDs offered to people; empty means all. |
| `session_duration` | string | `"24h"` | Login lifetime, `12h` to `24h`. |
| `service_token_duration` | string | `"8760h"` | Service token lifetime, at most `8760h`. |

## Outputs

| Name | Description |
|---|---|
| `aud_tags` | Audience tag per label, for `origin_request.access.aud_tag` of the tunnel. |
| `app_ids` | Application ID per label. |
| `hostnames` | Protected hostname per label. |
| `service_token_client_ids` | `CF-Access-Client-Id` per `service_auth` label. |
| `service_token_client_secrets` | `CF-Access-Client-Secret` per `service_auth` label (sensitive; Cloudflare shows it once, so it lives in the encrypted state only). |

## Tests

`tests/access.tftest.hcl` runs against a mocked provider: the shared allow policy, one
application per hostname, the service token and Service Auth policy of each machine-facing
application, an SSH application in `demo`, and the rejected names, types, sessions and token
lifetimes.
