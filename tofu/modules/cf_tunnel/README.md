# cf_tunnel

A remotely managed Cloudflare tunnel with its ingress rules and the DNS records that point at
it, guarded so that it can only ever touch its own names in a zone that it shares with other
records.

- The tunnel is remotely managed (`config_src = "cloudflare"`), so it has no `tunnel_secret` and
  no credentials file on the host.
- The module appends the catch-all rule `http_status:404` to the ingress rules, so a request for
  a name or path without a rule never reaches an origin.
- Every name gets a proxied CNAME to `<tunnel_id>.cfargotunnel.com` with the comment
  `managed-by-tofu env=<env>`. In `showcase` only, `address_records` adds DNS-only A or AAAA
  records for traffic that a tunnel cannot carry (UDP game traffic on `play`). No other record
  type can be created.
- The tunnel token is never read and never an output.

## Usage

```hcl
module "tunnel" {
  source = "../../modules/cf_tunnel"

  account_id  = var.account_id
  zone_id     = var.zone_id
  zone        = var.zone # for example example.com; never written in the code
  env         = "lab"
  tunnel_name = "lab-edge"
  dns_names   = ["lab-demo", "lab-tx"]
  ingress = [
    { hostname = "lab-demo.${var.zone}", service = "http://127.0.0.1:8080" },
    {
      hostname = "lab-tx.${var.zone}"
      service  = "http://192.0.2.13:40120"
      origin_request = {
        access = { team_name = var.team_name, aud_tag = [module.access.aud_tags["lab-tx"]] }
      }
    },
  ]
}
```

The provider reads its API token from `CLOUDFLARE_API_TOKEN`. It needs Cloudflare Tunnel Edit on
the account and DNS Edit on the zone.

## Name rules

| Environment | Allowed first-level labels |
|---|---|
| `lab` | `lab-*` |
| `demo` | `demo-*` |
| `showcase` | `show-*` and `play` |

Labels are lower-case letters, digits and hyphens. The apex (`@`), `www`, `mx`, `scripts`,
`triage`, `_dmarc`, `mta-sts`, `_mta-sts`, every label with `_domainkey` and every dotted name are
rejected, and so is any name of another environment. A denylist names the reserved labels; it is
a second layer behind the prefix rule, which rejects each of them as well. Every ingress
hostname must be `<label>.<zone>` with its label in `dns_names`, and a rule with
`origin_request.access` must keep `required = true`.

## Inputs

| Name | Type | Default | Description |
|---|---|---|---|
| `account_id` | string | | Cloudflare account ID (32 hexadecimal characters). |
| `zone_id` | string | | Zone ID of `zone`. |
| `zone` | string | | DNS zone, for example `example.com`. |
| `env` | string | | `lab`, `demo` or `showcase`; selects the name rules. |
| `tunnel_name` | string | | Tunnel name with the prefix of `env` (`lab-`, `demo-`, `show-`). |
| `dns_names` | list(string) | | Labels that get a proxied CNAME to the tunnel. |
| `ingress` | list(object) | | Rules `{ hostname, service, path, origin_request }`, in order; the catch-all rule is added. |
| `address_records` | map(object) | `{}` | `showcase` only: DNS-only `{ type = "A" or "AAAA", content, ttl }` keyed by label. |

## Outputs

| Name | Description |
|---|---|
| `tunnel_id` | ID of the tunnel; the configure step fetches the token for it from the API. |
| `tunnel_name` | Name of the tunnel. |
| `tunnel_cname` | `<tunnel_id>.cfargotunnel.com`. |
| `hostnames` | Hostnames that point at the tunnel, sorted. |
| `address_hostnames` | Hostnames of the DNS-only records, sorted. |
| `records` | Every record of the module keyed by hostname, with `type`, `proxied` and `comment`; the guard tests of the environments read it. |

## Tests

`tests/zone_guard.tftest.hcl` runs against a mocked provider: accepted names in every
environment, each rejected name and record type, the catch-all rule, the Access settings, the
record type, proxy flag and comment of every record. A reserved name fails both the prefix rule
and the denylist, and a test can only expect a failure of the variable, so the runs show that
each reserved name is rejected but cannot tell the two rules apart; one run checks the content
of the denylist and that no prefix matches a listed name. Run the tests with
`tofu -chdir=tofu/modules/cf_tunnel test` (after `tofu init`) or `scripts/check_tofu.sh test`.
