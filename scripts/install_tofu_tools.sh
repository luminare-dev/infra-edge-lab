#!/usr/bin/env bash
# Installs the pinned OpenTofu, TFLint, Terraform and Trivy binaries into a directory, each one
# only after the sha256 of its download matches the value below (the same values as
# docs/toolchain.md; tests/test_tofu.py keeps them equal). CI's "tofu" job installs tofu, tflint
# and trivy with it; "scripts/check_tofu.sh compat" installs terraform into a throwaway directory.
#
# Usage: scripts/install_tofu_tools.sh <dir> [tofu] [tflint] [terraform] [trivy]
#        (default: tofu tflint)
# Downloads are for Linux x86_64 (the GitHub ubuntu-24.04 runner and the workstation).
set -euo pipefail

TOFU_VERSION=1.13.1
TOFU_SHA256=378ada19d4bc70c43732004e8159be771b23b9a5afdf059e5f8a2b3fa2c70a69
TFLINT_VERSION=0.64.0
TFLINT_SHA256=cca9d13e2e1d7a2c627af60ff899a3c9b74212899416aeb96ec764d2ef954537
TERRAFORM_VERSION=1.16.6
TERRAFORM_SHA256=38034b38d03096399a7a1264a14561a8029b2b496fd1f169452656e53968f1b7
TRIVY_VERSION=0.76.0
TRIVY_SHA256=e24b1c51293c1b15e4ba8d45bbc7891ba053f90278ec2698f3562c993e145fe7

if [ $# -lt 1 ]; then
  echo "usage: $0 <dir> [tofu] [tflint] [terraform] [trivy]" >&2
  exit 2
fi
dest=$1
shift
if [ $# -eq 0 ]; then
  set -- tofu tflint
fi

if [ "$(uname -s)-$(uname -m)" != "Linux-x86_64" ]; then
  echo "$0: the pinned downloads are for Linux x86_64; install the tools by hand (docs/toolchain.md)" >&2
  exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$dest"

# fetch <url> <sha256>: download into the work directory and stop unless the sha256 matches.
fetch() {
  local file
  file="$work/$(basename "$1")"
  curl -fsSL --retry 3 -o "$file" "$1"
  echo "$2  $file" | sha256sum -c --quiet -
}

# unzip_one <zip> <member>: extract one file with Python's zipfile (unzip may be missing).
unzip_one() {
  python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extract(sys.argv[2], sys.argv[3])' "$1" "$2" "$work"
}

for tool in "$@"; do
  case "$tool" in
    tofu)
      file="tofu_${TOFU_VERSION}_linux_amd64.tar.gz"
      fetch "https://github.com/opentofu/opentofu/releases/download/v${TOFU_VERSION}/$file" "$TOFU_SHA256"
      tar -xzf "$work/$file" -C "$work" tofu
      ;;
    tflint)
      file=tflint_linux_amd64.zip
      fetch "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/$file" "$TFLINT_SHA256"
      unzip_one "$work/$file" tflint
      ;;
    terraform)
      file="terraform_${TERRAFORM_VERSION}_linux_amd64.zip"
      fetch "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/$file" "$TERRAFORM_SHA256"
      unzip_one "$work/$file" terraform
      ;;
    trivy)
      file="trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"
      fetch "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/$file" "$TRIVY_SHA256"
      tar -xzf "$work/$file" -C "$work" trivy
      ;;
    *)
      echo "$0: unknown tool '$tool' (tofu, tflint, terraform or trivy)" >&2
      exit 2
      ;;
  esac
  install -m 0755 "$work/$tool" "$dest/$tool"
  echo "installed $tool into $dest"
done
