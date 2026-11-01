#!/usr/bin/env python3
"""Fetch the token of a remotely managed tunnel from the Cloudflare API and print it.

The tunnel token is never an OpenTofu output. "task configure ENV=<env>" for an
environment with a tunnel (lab, demo, showcase) runs this script inside "sops exec-env" and
captures the token into TUNNEL_TOKEN for the one ansible-playbook command that needs it, so the
token is never written to a file on the workstation and never appears on a command line:

    TUNNEL_TOKEN="$(python3 scripts/tunnel_token.py --tunnel-id "$(tofu output -raw tunnel_id)")"

The API token comes from CLOUDFLARE_API_TOKEN and the account from TF_VAR_account_id (both from
the environment's SOPS file); the request is
GET /accounts/<account_id>/cfd_tunnel/<tunnel_id>/token, which needs tunnel write permission.
Only the token is printed (on standard output); errors name the cause, never a token.

Standard library only. Exit status 0 on success, 1 when the API refuses or answers something
unexpected, 2 for a missing or malformed input.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

API_BASE = "https://api.cloudflare.com/client/v4"
ACCOUNT_RE = re.compile(r"^[0-9a-f]{32}$")
TUNNEL_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# A tunnel token is base64 of a small JSON document: letters, digits, "+", "/", "=", "-", "_".
TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=_-]{40,4096}$")


class TokenError(Exception):
    """The API did not hand out a token; the message never contains one."""


def fetch(api_base: str, account_id: str, tunnel_id: str, api_token: str, timeout: float = 30) -> str:
    url = f"{api_base}/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_token}",
                                                   "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https base)
            body = response.read()
    except urllib.error.HTTPError as exc:
        with exc:
            raise TokenError(f"the API answered HTTP {exc.code} for tunnel {tunnel_id}{api_errors(exc.read())}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise TokenError(f"the API could not be reached: {reason}") from None
    try:
        data = json.loads(body)
    except ValueError:
        raise TokenError("the API answered something that is not JSON") from None
    if not isinstance(data, dict) or data.get("success") is not True:
        raise TokenError(f"the API refused the request for tunnel {tunnel_id}{api_errors(body)}")
    token = data.get("result")
    if not isinstance(token, str) or not TOKEN_RE.match(token):
        raise TokenError("the API answer holds no tunnel token in the expected format")
    return token


def api_errors(body: bytes) -> str:
    """The codes and messages of a Cloudflare error answer (never its result field)."""
    try:
        errors = json.loads(body).get("errors") or []
    except (ValueError, AttributeError):
        return ""
    parts = [f"{e.get('code')}: {e.get('message')}" for e in errors if isinstance(e, dict)]
    return f" ({'; '.join(parts)})" if parts else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--tunnel-id", required=True, help="ID of the tunnel (tofu output -raw tunnel_id)")
    parser.add_argument("--account-id", default=os.environ.get("TF_VAR_account_id", ""),
                        help="Cloudflare account ID (default: TF_VAR_account_id)")
    parser.add_argument("--api-base", default=API_BASE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    problems = []
    if not api_token:
        problems.append("CLOUDFLARE_API_TOKEN is not set (it comes from the SOPS file of the environment)")
    if not ACCOUNT_RE.match(args.account_id):
        problems.append("the account ID (TF_VAR_account_id) is not 32 hexadecimal characters")
    if not TUNNEL_RE.match(args.tunnel_id):
        problems.append("the tunnel ID is not a UUID")
    if problems:
        for problem in problems:
            print(f"tunnel_token.py: {problem}", file=sys.stderr)
        return 2
    try:
        token = fetch(args.api_base, args.account_id, args.tunnel_id, api_token)
    except TokenError as exc:
        print(f"tunnel_token.py: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(token + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
