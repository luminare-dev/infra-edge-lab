#!/usr/bin/env python3
"""Zone and account checks against the Cloudflare API, for the tasks around an apply.

The guard rails in the OpenTofu modules stop a wrong name before any API call.
This script is the operational layer around them: it checks the zone and the
token before an apply, keeps a copy of the zone, compares the zone before and after a run, and
removes what an interrupted demo run left behind. Subcommands:

    permissions  print the token permissions an environment needs (no API call)
    preflight    check what a read can show of those permissions, that the zone ID belongs to the
                 zone, and that the environment touches no record it does not manage: without a
                 plan, every record under the environment's prefix must carry the environment's
                 comment; with --plan-json (tofu show -json of a saved plan), every DNS record the
                 plan creates, changes or deletes must have the environment's prefix, a record it
                 creates must not exist yet, and one it changes or deletes must carry the comment
    export       print the zone file of the zone (BIND format) on standard output, for an
                 encrypted copy (scripts/dns_backup.sh); the count goes to standard error
    snapshot     write every record outside an environment's prefix, without IDs and timestamps,
                 to a JSON file (mode 0600)
    compare      compare two snapshot files and name the records that differ
    sweep        list, or with --delete remove, the objects of the demo environment that are
                 left over: Access applications, their policies and service tokens, DNS records
                 with the demo comment and tunnels without a connection, all named demo-*
    tunnel-status  wait until a tunnel has a connection

Credentials come from the environment, as for OpenTofu: CLOUDFLARE_API_TOKEN, TF_VAR_account_id,
TF_VAR_zone_id and TF_VAR_zone (from the SOPS file of the environment). Nothing this script
prints contains the API token; record names contain the zone, which the CI workflows mask.

Standard library only. Exit status 0 on success, 1 when a check refuses or the API fails, 2 for a
missing or malformed input.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

API_BASE = "https://api.cloudflare.com/client/v4"
ACCOUNT_RE = re.compile(r"^[0-9a-f]{32}$")
ZONE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
ZONE_RE = re.compile(r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ENVS = ("lab", "demo", "showcase")

# The name rules of tofu/modules/cf_tunnel/guard.tf and tofu/modules/cf_access_app/guard.tf;
# tests/test_cloudflare_api.py keeps them equal.
NAME_PATTERNS = {
    "lab": "^lab-[a-z0-9-]+$",
    "demo": "^demo-[a-z0-9-]+$",
    "showcase": "^(show-[a-z0-9-]+|play)$",
}
TUNNEL_PREFIXES = {"lab": "lab-", "demo": "demo-", "showcase": "show-"}
# Record types the tunnel module may create (CNAME everywhere, A and AAAA in showcase only).
RECORD_TYPES = {"lab": {"CNAME"}, "demo": {"CNAME"}, "showcase": {"CNAME", "A", "AAAA"}}


def comment(env: str) -> str:
    """The comment of every record that the tunnel module creates (tofu/modules/cf_tunnel/main.tf)."""
    return f"managed-by-tofu env={env}"


# What each environment needs. An apply creates and deletes tunnels, Access applications,
# policies, service tokens and DNS records; a plan only reads them. The names are those of the
# token form in the dashboard, which Cloudflare renames from time to time.
WRITE_PERMISSIONS = (
    ("Account", "Cloudflare Tunnel", "Edit", "the tunnel, its ingress rules and its token"),
    ("Account", "Access: Apps and Policies", "Edit", "the Access applications and their policies"),
    ("Account", "Access: Service Tokens", "Edit", "the service tokens of the machine-facing applications"),
    ("Zone", "DNS", "Edit", "the CNAME records of the hostnames, for this one zone only"),
)
# The reads that preflight makes, one per permission, each with the permission it shows.
READ_CHECKS = (
    ("Zone · DNS · Read", "/zones/{zone_id}/dns_records"),
    ("Account · Cloudflare Tunnel · Read", "/accounts/{account_id}/cfd_tunnel"),
    ("Account · Access: Apps and Policies · Read", "/accounts/{account_id}/access/apps"),
    ("Account · Access: Service Tokens · Read", "/accounts/{account_id}/access/service_tokens"),
)

# Names that the cf_access_app module gives the objects of the demo environment.
DEMO_POLICY_RES = (re.compile(r"^demo-[a-z0-9-]+ service auth$"), re.compile(r"^demo allow listed e-mail addresses$"))
DEMO_TOKEN_RE = re.compile(r"^demo-[a-z0-9-]+ service token$")
# A tunnel with a connector is in use; the sweeper never deletes it.
ACTIVE_TUNNEL_STATES = {"healthy", "degraded"}
# Keys of a DNS record that change without a change of the record itself.
VOLATILE_KEYS = {"id", "created_on", "modified_on", "meta", "zone_id", "zone_name", "proxiable", "locked",
                 "comment_modified_on", "tags_modified_on"}


class ApiError(Exception):
    """The API refused a request or could not be reached; the message never holds a credential."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Api:
    def __init__(self, token: str, base: str = API_BASE, timeout: float = 30):
        self.token = token
        self.base = base.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, params: dict[str, Any] | None = None, raw: bool = False) -> Any:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 (fixed https base)
                body = response.read()
        except urllib.error.HTTPError as exc:
            with exc:
                raise ApiError(f"{method} {path}: HTTP {exc.code}{api_errors(exc.read())}", exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApiError(f"{method} {path}: the API could not be reached: {getattr(exc, 'reason', exc)}") from None
        if raw:
            return body
        try:
            data = json.loads(body)
        except ValueError:
            raise ApiError(f"{method} {path}: the answer is not JSON") from None
        if not isinstance(data, dict) or data.get("success") is not True:
            raise ApiError(f"{method} {path}: the API refused the request{api_errors(body)}")
        return data

    def get_all(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Every item of a paginated list."""
        items: list[dict[str, Any]] = []
        page = 1
        while True:
            data = self.request("GET", path, {**(params or {}), "page": page, "per_page": 100})
            result = data.get("result") or []
            if not isinstance(result, list):
                raise ApiError(f"GET {path}: the result is not a list")
            items += [item for item in result if isinstance(item, dict)]
            info = data.get("result_info") or {}
            total_pages = info.get("total_pages")
            if not result or not isinstance(total_pages, int) or page >= total_pages:
                return items
            page += 1


def api_errors(body: bytes) -> str:
    """The codes and messages of a Cloudflare error answer (never its result field)."""
    try:
        errors = json.loads(body).get("errors") or []
    except (ValueError, AttributeError):
        return ""
    parts = [f"{e.get('code')}: {e.get('message')}" for e in errors if isinstance(e, dict)]
    return f" ({'; '.join(parts)})" if parts else ""


class Settings:
    """Credentials and IDs from the environment, checked before any request."""

    def __init__(self, need: Iterable[str]):
        self.token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
        self.account_id = os.environ.get("TF_VAR_account_id", "")
        self.zone_id = os.environ.get("TF_VAR_zone_id", "")
        self.zone = os.environ.get("TF_VAR_zone", "")
        checks = {
            "token": (bool(self.token), "CLOUDFLARE_API_TOKEN is not set"),
            "account": (bool(ACCOUNT_RE.match(self.account_id)),
                        "TF_VAR_account_id is not a Cloudflare account ID (32 hexadecimal characters)"),
            "zone_id": (bool(ZONE_ID_RE.match(self.zone_id)),
                        "TF_VAR_zone_id is not a Cloudflare zone ID (32 hexadecimal characters)"),
            "zone": (bool(ZONE_RE.match(self.zone)), "TF_VAR_zone is not a lower-case domain name"),
        }
        self.problems = [message for key, (ok, message) in checks.items() if key in need and not ok]


def api_base() -> str:
    """The API base URL. CLOUDFLARE_API_BASE replaces it for the tests (a loopback address only)."""
    base = os.environ.get("CLOUDFLARE_API_BASE", "")
    if base and re.match(r"^http://127\.0\.0\.1:\d+(/.*)?$", base):
        return base
    return API_BASE


def label_of(name: str, zone: str) -> str | None:
    """The label of a record name in the zone ("@" for the apex), None when outside the zone."""
    if name == zone:
        return "@"
    if name.endswith("." + zone):
        return name[: -len(zone) - 1]
    return None


def managed_label(label: str | None, env: str) -> bool:
    return label is not None and re.match(NAME_PATTERNS[env], label) is not None


def parse_time(value: Any) -> datetime | None:
    """An API timestamp (2026-10-22T10:00:00.123456789Z and similar) as an aware datetime."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def records(api: Api, settings: Settings) -> list[dict[str, Any]]:
    return api.get_all(f"/zones/{settings.zone_id}/dns_records")


# --- permissions and preflight ------------------------------------------------------------------

def print_permissions(env: str, read_only: bool) -> None:
    level = "Read" if read_only else "Edit"
    what = "a read-only plan" if read_only else "an apply, a destroy and the sweeper"
    print(f"Cloudflare API token permissions for {what} of {env}:")
    for scope, name, _, purpose in WRITE_PERMISSIONS:
        print(f"  - {scope} · {name} · {level}: {purpose}")
    print("  A token for one zone only (Zone Resources: Include, Specific zone) and this one account is enough;")
    print("  the dashboard may show newer names for the same permissions.")


def preflight(api: Api, settings: Settings, env: str, plan: dict[str, Any] | None) -> list[str]:
    """Refusals (empty when every check passes); prints what it checked."""
    refusals: list[str] = []
    zone_records: list[dict[str, Any]] = []
    for permission, template in READ_CHECKS:
        path = template.format(zone_id=settings.zone_id, account_id=settings.account_id)
        try:
            if "dns_records" in path:
                zone_records = records(api, settings)
            else:
                api.request("GET", path, {"page": 1, "per_page": 1})
        except ApiError as exc:
            refusals.append(f"the token cannot read what {permission} grants: {exc}")
            print(f"  {permission}: refused")
            continue
        print(f"  {permission}: ok")
    if not read_ok(refusals, "Zone · DNS · Read"):
        return refusals
    print("  Edit permissions: not checked (only a write would show them)")

    outside = sorted({r.get("name", "?") for r in zone_records if label_of(str(r.get("name", "")), settings.zone) is None})
    if outside:
        refusals.append(f"TF_VAR_zone_id does not belong to TF_VAR_zone: {len(outside)} record(s) of the zone are "
                        "not names in it")
        return refusals
    by_name: dict[str, list[dict[str, Any]]] = {}
    for record in zone_records:
        by_name.setdefault(str(record.get("name")), []).append(record)
    mine = comment(env)
    print(f"  zone: {len(zone_records)} record(s), "
          f"{sum(1 for r in zone_records if r.get('comment') == mine)} with the comment \"{mine}\"")

    if plan is None:
        for record in zone_records:
            name = str(record.get("name"))
            if managed_label(label_of(name, settings.zone), env) and record.get("comment") != mine:
                refusals.append(f"{record.get('type')} {name} has the prefix of {env} but not the comment \"{mine}\": "
                                f"this repository did not create it, and an apply of {env} could collide with it")
        return refusals
    return refusals + check_plan(api, settings, env, plan, by_name)


def read_ok(refusals: list[str], permission: str) -> bool:
    return not any(permission in r for r in refusals)


def plan_changes(plan: dict[str, Any], resource_type: str) -> list[tuple[list[str], dict, dict]]:
    """(actions, before, after) of every change of one resource type that is not a no-op or a read."""
    changes = []
    for change in plan.get("resource_changes") or []:
        if change.get("type") != resource_type:
            continue
        detail = change.get("change") or {}
        actions = list(detail.get("actions") or [])
        if not actions or set(actions) <= {"no-op", "read"}:
            continue
        changes.append((actions, detail.get("before") or {}, detail.get("after") or {}))
    return changes


def check_plan(api: Api, settings: Settings, env: str, plan: dict[str, Any],
               by_name: dict[str, list[dict[str, Any]]]) -> list[str]:
    refusals: list[str] = []
    mine = comment(env)
    dns_changes = plan_changes(plan, "cloudflare_dns_record")
    for actions, before, after in dns_changes:
        for side in (before, after):
            if not side:
                continue
            name = str(side.get("name", ""))
            label = label_of(name, settings.zone)
            if not managed_label(label, env):
                refusals.append(f"the plan would touch {name or 'a record without a name'}, which is outside the "
                                f"prefix of {env}")
            record_type = side.get("type")
            if record_type is not None and record_type not in RECORD_TYPES[env]:
                refusals.append(f"the plan would write a {record_type} record ({name}); {env} manages only "
                                f"{', '.join(sorted(RECORD_TYPES[env]))}")
        if "create" in actions and "delete" not in actions:
            name = str(after.get("name", ""))
            for existing in by_name.get(name, []):
                origin = ("left from an earlier run or a running environment (destroy it, or task sweep:demo for "
                          "demo)" if existing.get("comment") == mine else "not created by this repository")
                refusals.append(f"the plan would create {name}, but the zone already has {existing.get('type')} "
                                f"{name}, {origin}")
        if "update" in actions or "delete" in actions:
            name = str(before.get("name", ""))
            existing = [r for r in by_name.get(name, [])
                        if not before.get("id") or r.get("id") == before.get("id")]
            for record in existing:
                if record.get("comment") != mine:
                    refusals.append(f"the plan would change or delete {record.get('type')} {name}, which does not "
                                    f"carry the comment \"{mine}\"")
    print(f"  plan: {len(dns_changes)} DNS record change(s) checked")

    new_tunnels = {str(a.get("name")) for actions, _, a in plan_changes(plan, "cloudflare_zero_trust_tunnel_cloudflared")
                   if "create" in actions and "delete" not in actions}
    new_apps = {str(a.get("domain")) for actions, _, a in plan_changes(plan, "cloudflare_zero_trust_access_application")
                if "create" in actions and "delete" not in actions}
    for name in new_tunnels:
        if not name.startswith(TUNNEL_PREFIXES[env]):
            refusals.append(f"the plan would create the tunnel {name}, which lacks the prefix {TUNNEL_PREFIXES[env]}")
    try:
        if new_tunnels:
            existing_tunnels = {t.get("name") for t in api.get_all(f"/accounts/{settings.account_id}/cfd_tunnel",
                                                                     {"is_deleted": "false"})}
            refusals += [f"the plan would create the tunnel {name}, which exists already (left from an earlier run? "
                         "task sweep:demo removes it for demo)" for name in sorted(new_tunnels & existing_tunnels)]
        if new_apps:
            existing_apps = {a.get("domain") for a in api.get_all(f"/accounts/{settings.account_id}/access/apps")}
            refusals += [f"the plan would create an Access application for {domain}, which has one already"
                         for domain in sorted(new_apps & existing_apps)]
    except ApiError as exc:
        refusals.append(str(exc))
    print(f"  plan: {len(new_tunnels)} new tunnel(s) and {len(new_apps)} new Access application(s) checked")
    return refusals


# --- snapshot and compare -----------------------------------------------------------------------

def snapshot(zone_records: list[dict[str, Any]], zone: str, exclude_env: str | None) -> list[dict[str, Any]]:
    """The records outside an environment's prefix, without IDs and timestamps, sorted."""
    kept = []
    for record in zone_records:
        if exclude_env and managed_label(label_of(str(record.get("name", "")), zone), exclude_env):
            continue
        kept.append({k: v for k, v in sorted(record.items()) if k not in VOLATILE_KEYS})
    return sorted(kept, key=lambda r: json.dumps(r, sort_keys=True))


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def compare(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    """One line per record that is only in one of the snapshots (type and name, never content)."""
    def keyed(items):
        return {json.dumps(r, sort_keys=True): r for r in items}
    old, new = keyed(before), keyed(after)
    lines = [f"gone or changed: {old[k].get('type')} {old[k].get('name')}" for k in sorted(set(old) - set(new))]
    lines += [f"new or changed: {new[k].get('type')} {new[k].get('name')}" for k in sorted(set(new) - set(old))]
    return lines


# --- sweep ----------------------------------------------------------------------------------------

def sweep_candidates(api: Api, settings: Settings, created_after: datetime | None) -> list[tuple[str, str, str, dict]]:
    """(kind, name, delete path, object) of every left-over demo object, in deletion order."""
    account = f"/accounts/{settings.account_id}"

    def recent(item: dict[str, Any], key: str) -> bool:
        if created_after is None:
            return True
        moment = parse_time(item.get(key))
        return moment is not None and moment >= created_after

    found: list[tuple[str, str, str, dict]] = []
    for app in api.get_all(f"{account}/access/apps"):
        name, domain = str(app.get("name", "")), str(app.get("domain", ""))
        if (managed_label(name, "demo") and domain == f"{name}.{settings.zone}" and recent(app, "created_at")
                and UUID_RE.match(str(app.get("id", "")))):
            found.append(("Access application", name, f"{account}/access/apps/{app['id']}", app))
    for policy in api.get_all(f"{account}/access/policies"):
        name = str(policy.get("name", ""))
        if (any(p.match(name) for p in DEMO_POLICY_RES) and recent(policy, "created_at")
                and UUID_RE.match(str(policy.get("id", "")))):
            found.append(("Access policy", name, f"{account}/access/policies/{policy['id']}", policy))
    for token in api.get_all(f"{account}/access/service_tokens"):
        name = str(token.get("name", ""))
        if DEMO_TOKEN_RE.match(name) and recent(token, "created_at") and UUID_RE.match(str(token.get("id", ""))):
            found.append(("service token", name, f"{account}/access/service_tokens/{token['id']}", token))
    for record in records(api, settings):
        name = str(record.get("name", ""))
        if (managed_label(label_of(name, settings.zone), "demo") and record.get("comment") == comment("demo")
                and recent(record, "created_on") and re.match(r"^[0-9a-f]{32}$", str(record.get("id", "")))):
            found.append(("DNS record", f"{record.get('type')} {name}",
                          f"/zones/{settings.zone_id}/dns_records/{record['id']}", record))
    for tunnel in api.get_all(f"{account}/cfd_tunnel", {"is_deleted": "false"}):
        name = str(tunnel.get("name", ""))
        if managed_label(name, "demo") and recent(tunnel, "created_at") and UUID_RE.match(str(tunnel.get("id", ""))):
            found.append(("tunnel", name, f"{account}/cfd_tunnel/{tunnel['id']}", tunnel))
    return found


def sweep(api: Api, settings: Settings, delete: bool, created_after: datetime | None) -> int:
    candidates = sweep_candidates(api, settings, created_after)
    window = f" created since {created_after.isoformat()}" if created_after else ""
    if not candidates:
        print(f"sweep: no left-over demo object{window}")
        return 0
    failed = 0
    for kind, name, path, item in candidates:
        if kind == "tunnel" and item.get("status") in ACTIVE_TUNNEL_STATES:
            print(f"sweep: {'kept' if delete else 'would keep'} the tunnel {name}: it has a connector "
                  f"({item.get('status')}); stop the connector, then sweep again")
            failed += 1 if delete else 0
            continue
        if not delete:
            print(f"sweep: would delete the {kind} {name}")
            continue
        try:
            if kind == "tunnel":
                # Stale connections of a connector that is gone; a tunnel without any is fine.
                try:
                    api.request("DELETE", f"{path}/connections")
                except ApiError:
                    pass
            api.request("DELETE", path)
        except ApiError as exc:
            print(f"sweep: could not delete the {kind} {name}: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(f"sweep: deleted the {kind} {name}")
    if not delete:
        print(f"sweep: {len(candidates)} left-over demo object(s){window}; run again with --delete to remove them")
    return 1 if failed else 0


# --- tunnel status --------------------------------------------------------------------------------

def wait_for_tunnel(api: Api, settings: Settings, tunnel_id: str, wait: float, interval: float = 5) -> bool:
    deadline = time.monotonic() + wait
    status = "unknown"
    while True:
        data = api.request("GET", f"/accounts/{settings.account_id}/cfd_tunnel/{tunnel_id}")
        result = data.get("result") or {}
        status = str(result.get("status", "unknown"))
        if status in ACTIVE_TUNNEL_STATES or result.get("connections"):
            print(f"tunnel {tunnel_id}: {status}, {len(result.get('connections') or [])} connection(s)")
            return True
        if time.monotonic() >= deadline:
            print(f"tunnel {tunnel_id}: still {status} after {wait:.0f} s", file=sys.stderr)
            return False
        time.sleep(interval)


# --- command line ---------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("permissions", help="print the token permissions an environment needs")
    p.add_argument("--env", required=True, choices=ENVS)
    p.add_argument("--read-only", action="store_true", help="the permissions of a read-only plan")
    p = sub.add_parser("preflight", help="check the token and the zone before an apply")
    p.add_argument("--env", required=True, choices=ENVS)
    p.add_argument("--plan-json", type=Path, help="tofu show -json of the saved plan to check")
    sub.add_parser("export", help="print the zone file (BIND format)")
    p = sub.add_parser("snapshot", help="write the records outside an environment's prefix to a JSON file")
    p.add_argument("--exclude-env", choices=ENVS, help="leave out the records with this environment's prefix")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("compare", help="compare two snapshot files")
    p.add_argument("before", type=Path)
    p.add_argument("after", type=Path)
    p = sub.add_parser("sweep", help="list or delete the left-over objects of the demo environment")
    p.add_argument("--delete", action="store_true", help="delete them (default: list only)")
    p.add_argument("--created-after", help="only objects created at or after this ISO 8601 time (UTC)")
    p = sub.add_parser("tunnel-status", help="wait until a tunnel has a connection")
    p.add_argument("--tunnel-id", required=True)
    p.add_argument("--wait", type=float, default=180, help="seconds to wait (default 180)")
    args = parser.parse_args(argv)

    if args.command == "permissions":
        print_permissions(args.env, args.read_only)
        return 0
    if args.command == "compare":
        try:
            before, after = (json.loads(path.read_text(encoding="utf-8")) for path in (args.before, args.after))
        except (OSError, ValueError) as exc:
            print(f"cloudflare_api.py: {exc}", file=sys.stderr)
            return 2
        differences = compare(before, after)
        for line in differences:
            print(f"zone: {line}")
        print(f"zone: {len(after)} record(s) outside the environment, "
              f"{'unchanged' if not differences else f'{len(differences)} difference(s)'}")
        return 1 if differences else 0

    need = {"token", "account", "zone_id", "zone"}
    if args.command in ("export", "snapshot"):
        need = {"token", "zone_id", "zone"}
    elif args.command == "tunnel-status":
        need = {"token", "account"}
    settings = Settings(need)
    created_after = None
    if args.command == "sweep" and args.created_after:
        created_after = parse_time(args.created_after)
        if created_after is None:
            settings.problems.append("--created-after is not an ISO 8601 time")
    if args.command == "tunnel-status" and not UUID_RE.match(args.tunnel_id):
        settings.problems.append("the tunnel ID is not a UUID")
    plan = None
    if args.command == "preflight" and args.plan_json:
        try:
            plan = json.loads(args.plan_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            settings.problems.append(f"cannot read the plan {args.plan_json}: {exc}")
    if settings.problems:
        for problem in settings.problems:
            print(f"cloudflare_api.py: {problem}", file=sys.stderr)
        return 2

    api = Api(settings.token, api_base())
    try:
        if args.command == "preflight":
            print(f"preflight of {args.env}:")
            refusals = preflight(api, settings, args.env, plan)
            for refusal in refusals:
                print(f"preflight: refused: {refusal}", file=sys.stderr)
            print(f"preflight of {args.env}: {'refused' if refusals else 'passed'}")
            return 1 if refusals else 0
        if args.command == "export":
            body = api.request("GET", f"/zones/{settings.zone_id}/dns_records/export", raw=True)
            text = body.decode("utf-8", errors="strict")
            if "SOA" not in text and "IN\t" not in text and " IN " not in text:
                print("cloudflare_api.py: the export does not look like a zone file", file=sys.stderr)
                return 1
            sys.stdout.write(text)
            count = sum(1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith(";"))
            print(f"export: {count} record line(s)", file=sys.stderr)
            return 0
        if args.command == "snapshot":
            kept = snapshot(records(api, settings), settings.zone, args.exclude_env)
            write_private(args.output, json.dumps(kept, indent=1, sort_keys=True) + "\n")
            outside = f" outside the prefix of {args.exclude_env}" if args.exclude_env else ""
            print(f"snapshot: {len(kept)} record(s){outside} written to {args.output}")
            return 0
        if args.command == "sweep":
            return sweep(api, settings, args.delete, created_after)
        if args.command == "tunnel-status":
            return 0 if wait_for_tunnel(api, settings, args.tunnel_id, args.wait) else 1
    except ApiError as exc:
        print(f"cloudflare_api.py: {exc}", file=sys.stderr)
        return 1
    except UnicodeDecodeError:
        print("cloudflare_api.py: the export is not UTF-8 text", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
