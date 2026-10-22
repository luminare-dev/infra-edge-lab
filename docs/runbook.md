# Runbook

At this version the repository runs no service; the failures below are those of the repository's
own checks.

## Failure: the secret scan finds a secret

| | |
|---|---|
| **Meaning** | `secrets / gitleaks` (or `task lint`) found something that looks like a credential in a commit or the working tree. |
| **Impact** | If the commit was pushed, the value must be treated as public, whatever the visibility of the repository. |
| **Diagnosis** | `gitleaks git --redact --config .gitleaks.toml .` names the rule, file and commit; `git show <commit> -- <file>` shows the line. A value inside a SOPS file is fine only if it starts with `ENC[`. |
| **Mitigation** | Revoke or rotate the credential at its provider first, before anything else. |
| **Fix** | Remove the value from the branch (rewrite the commits before merging, or open an issue to purge merged history), move it into an encrypted file in `secrets/`, and add a test or allowlist entry only for a proven false positive. |

## Failure: the hash-pinned install fails

| | |
|---|---|
| **Meaning** | `scripts/run_tests.sh` or `task venv` stopped in `pip install --require-hashes`, for example with `THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE`. |
| **Impact** | `ci / lint-test` and the release build fail; no tests run. |
| **Diagnosis** | Read which package and file pip names. Check the Python version (3.12 or 3.13) and the platform (Linux x86_64): another interpreter may need a distribution file the requirements do not list. |
| **Mitigation** | Run with Python 3.12, the version the files are compiled for. |
| **Fix** | Never copy a new hash from the error message. Recompile `requirements-test.txt` as in [toolchain.md](toolchain.md) and review the diff: a changed hash for an unchanged version means the file on PyPI changed and needs an explanation before it is accepted. |

## Failure: a Dependabot pull request fails CI

| | |
|---|---|
| **Meaning** | A dependency update breaks a check or a test. |
| **Impact** | The update waits; the current pins stay in use. |
| **Diagnosis** | Open the failed job; compare the release notes of the updated dependency. A version copied into the docs is not the cause: `tests/test_toolchain.py` keeps the Python versions in the requirements files only. |
| **Mitigation** | Leave the pull request open or close it; Dependabot proposes the next version later. |
| **Fix** | Adapt the code in the same pull request, or pin around the broken version with a comment that names the issue. |
