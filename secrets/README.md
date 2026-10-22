# Secrets

Credentials for an environment are kept in a dotenv file encrypted with
[SOPS](https://github.com/getsops/sops) and [age](https://github.com/FiloSottile/age)
([ADR 0006](../docs/adr/0006-sops-and-age-for-secrets.md)):

| File | Holds | Who can decrypt it |
|---|---|---|
| `<env>.enc.env` | write credentials for applying changes | the operator's age key and an offline break-glass key |
| `<env>-ci.enc.env` | read-only credentials for plans in CI | the same keys plus the CI key of that environment |

The recipients are set by the creation rules in `.sops.yaml` at the repository root, a committed
file that holds public age keys only; private keys never enter the repository. At this version
the repository ships **no** encrypted file and no `.sops.yaml` yet; [env.example](env.example)
lists the keys a file can hold. Values are read into the environment of one command
(`sops exec-env secrets/<env>.enc.env '<command>'`) and never written to disk in clear text;
`task init ENV=<env>` and `task plan ENV=<env>` do this themselves when the file exists
([tofu/envs/README.md](../tofu/envs/README.md)).

Only this README, `*.example` files and `*.enc.env` files can be committed here: `.gitignore`
ignores everything else in this folder, and the unit tests fail if a committed `*.enc.env` file
holds a value that is not encrypted.
