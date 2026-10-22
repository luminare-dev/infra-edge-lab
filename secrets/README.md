# Secrets

Credentials for an environment are kept in a dotenv file encrypted with
[SOPS](https://github.com/getsops/sops) and [age](https://github.com/FiloSottile/age)
([ADR 0006](../docs/adr/0006-sops-and-age-for-secrets.md)):

| File | Holds | Who can decrypt it |
|---|---|---|
| `<env>.enc.env` | write credentials for applying changes | the operator's age key and an offline break-glass key; for `demo` and `showcase` also the key of that GitHub environment (the `apply` workflow) |
| `<env>-ci.enc.env` | read-only credentials for plans in CI | the same keys plus the key of the GitHub environment `lab-plan` (the `plan` and `drift` workflows) |
| `demo-e2e.enc.env` | the Cloudflare token, account, zone and team values of the tunnel test, no cloud server token | the same keys plus the key of the GitHub environment `demo-e2e` (the `e2e-tunnel` workflow) |

Each GitHub environment holds its age private key as the secret `SOPS_AGE_KEY` and nothing else,
so a workflow can decrypt only the files whose creation rules list that environment's public key
([runbook](../docs/runbook.md#procedure-turn-on-the-cloud-workflows)). `lab` write credentials
never reach CI: the lab is applied from the operator's workstation only.

The recipients are set by the creation rules in `.sops.yaml` at the repository root, a committed
file that holds public age keys only; private keys never enter the repository. At this version
the repository ships **no** encrypted file and no `.sops.yaml` yet; [env.example](env.example)
lists the keys a file can hold, and [configuration.md](../docs/configuration.md#secrets) shows how
to create the age keys and an example `.sops.yaml` for every file of this table. Values are read into the environment of one command
(`sops exec-env secrets/<env>.enc.env '<command>'`) and never written to disk in clear text;
`task init ENV=<env>` and `task plan ENV=<env>` do this themselves when the file exists
([tofu/envs/README.md](../tofu/envs/README.md)).

Only this README, `*.example` files and `*.enc.env` files can be committed here: `.gitignore`
ignores everything else in this folder, and the unit tests fail if a committed `*.enc.env` file
holds a value that is not encrypted.
