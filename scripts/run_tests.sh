#!/usr/bin/env bash
# The repository's test command. CI runs it in "ci / lint-test" and on the release tag (the
# test-command input of ci.yml and release.yml); "task test" runs it locally.
#
# It installs the hash-pinned Python tools from requirements-test.txt into a virtual environment
# (TEST_VENV; default .venv, in CI $RUNNER_TEMP/venv-test) and runs the unit tests with that
# environment first on the PATH, so the tests also check the installed tool versions. Then it
# runs ansible-lint (production profile, offline; .ansible-lint) over the roles in ansible/roles,
# their Molecule playbooks, the playbooks in ansible/playbooks and the inventories' group_vars,
# with the collections of the hash-pinned "ansible" package (the roles of other collections are
# mocked, see .ansible-lint).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -n "${TEST_VENV:-}" ]; then
  venv="$TEST_VENV"
elif [ -n "${RUNNER_TEMP:-}" ]; then
  venv="$RUNNER_TEMP/venv-test"
else
  venv=".venv"
fi

if [ ! -x "$venv/bin/python" ]; then
  python3 -m venv "$venv"
fi
"$venv/bin/python" -m pip install --quiet --disable-pip-version-check \
  --require-hashes --only-binary=:all: -r requirements-test.txt

PATH="$(cd "$venv/bin" && pwd):$PATH"
REQUIREMENTS_TEST_INSTALLED=1
export PATH REQUIREMENTS_TEST_INSTALLED
python3 -m unittest discover -s tests -v
# The playbooks in ansible/playbooks use the roles of ansible/roles by name, as ansible.cfg's
# roles_path does for a real run from the ansible/ folder.
ANSIBLE_ROLES_PATH="$PWD/ansible/roles" ansible-lint
