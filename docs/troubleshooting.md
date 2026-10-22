# Troubleshooting

## `The virtual environment was not created successfully because ensurepip is not available`

**Cause:** Debian and Ubuntu ship the `venv` module of Python in a separate package.

**Fix:**

```bash
sudo apt install python3-venv
task venv
```

## `ERROR: Could not find a version that satisfies the requirement ansible-core==…`

**Cause:** ansible-core 2.21 needs Python 3.12 or later, and `--only-binary=:all:` allows wheels
only. An older `python3` finds no matching file.

**Fix:** install Python 3.12 or 3.13 and create the environment with it:

```bash
rm -rf .venv
python3.12 -m venv .venv
task venv
```

## `@name: repository name '…' contains the mark …` from `forbidden_words.py`

**Cause:** the clone has no `origin` remote, so the name check falls back to the folder name.

**Fix:** name the repository explicitly:

```bash
GITHUB_REPOSITORY=luminare-dev/infra-edge-lab python3 scripts/forbidden_words.py
```

## `task: Failed to run task "lint"` after `npx --yes markdownlint-cli2@0.23.2`

**Cause:** Node.js is missing or too old for markdownlint-cli2, or npm cannot reach the registry.

**Fix:** install Node.js 24.22.0 as described in [toolchain.md](toolchain.md) and run `task lint`
again.

## Still stuck?

Search the issues, then ask in the organization's
[Discussions](https://github.com/orgs/luminare-dev/discussions). Never post secrets, keys, IP
addresses, hostnames or player data; redact logs before you paste them.
