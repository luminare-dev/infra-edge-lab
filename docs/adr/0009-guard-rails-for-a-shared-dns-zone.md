# 0009. Guard rails for a shared DNS zone

- **Status:** accepted
- **Date:** 2026-10-21

## Context

The tunnel hostnames live in a DNS zone that also holds records this repository must never
touch: the website, mail (MX, SPF, DKIM, DMARC, MTA-STS) and other sites. A Cloudflare API token
with DNS Edit is scoped to a whole zone; there is no narrower scope per name or record type. One
typo in a variable could therefore replace `www` or the MX record.

## Considered options

1. A separate zone for the lab.
2. Trust in review only.
3. Guard rails in the code: name and record-type rules in the modules, tested on every change.

## Decision

Chosen option: 3, because it works with the existing zone and turns a typo into a failed plan
before anything reaches the API. The zone itself is always a variable (`var.zone`), never a
literal in the code; examples use `example.com`.

- Every environment has its own first-level prefix: `lab-*`, `demo-*`, and `show-*` plus `play`
  in `showcase`. A name of another environment, a dotted name (outside the edge certificate,
  which covers one level only), upper case or an empty label fails the variable validation.
- A denylist rejects the apex (`@`), `www`, `mx`, `scripts`, `triage`, `_dmarc`, `mta-sts`,
  `_mta-sts` and every `_domainkey` label with its own message. It is a second layer: no prefix
  matches these names, so the prefix rule rejects them as well, and the denylist still rejects
  them if a prefix is ever widened.
- Record types: the tunnel module creates proxied CNAMEs only; DNS-only A and AAAA records are
  allowed in `showcase` only. A variable validation and a resource precondition both reject
  every other type, so MX and TXT can never be created.
- Every record carries the comment `managed-by-tofu env=<env>`, so a reviewer, a zone export and a
  clean-up job can tell these records apart from the rest of the zone.
- The Access module applies the same name rules to its applications.
- `tofu test` with mocked providers checks the accepted names per environment, that each
  reserved name, dotted name, name of another environment and the record types MX and TXT are
  rejected, the catch-all ingress rule, proxied CNAMEs and the comment. A reserved name fails the
  prefix rule and the denylist together, and a test can expect a failure of the variable only,
  not of one validation, so the tests cannot tell the two layers apart; one run checks the
  content of the denylist and that no prefix matches a listed name.

## Consequences

- Good: a wrong name or type fails in `tofu plan` and in CI, without credentials.
- Good: the tests run on fork pull requests, because the providers are mocked.
- Bad: the rules are written in two modules (`cf_tunnel`, `cf_access_app`) and must be changed
  together; the tests of both modules cover them.
- Bad: no test shows the denylist rejecting a name on its own, because the prefix rule rejects
  every listed name as well. The denylist matters only once a prefix lets a listed name through,
  and such a change fails the run that checks that no prefix matches a listed name.
- Bad: the guard does not protect against a token used outside this code; zone exports before
  each apply remain the operational safety net.
