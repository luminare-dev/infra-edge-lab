#!/usr/bin/env python3
"""Summarise a saved OpenTofu plan by resource, without a single attribute value.

The logs and job summaries of a public repository can be read by anyone with a GitHub account,
and a full plan shows every attribute: addresses, hostnames, IDs, sometimes secrets that the
provider does not mark as sensitive. The CI workflows therefore never print a plan; they print
this summary of it instead (docs/adr/0023):

    tofu -chdir=tofu/envs/demo show -json tfplan | python3 scripts/plan_summary.py --env demo

It lists each resource address with its action (create, update, replace, delete, forget), the
resources that changed outside OpenTofu since the last apply (drift found by the refresh), and
the counts in OpenTofu's own words ("Plan: 2 to add, 0 to change, 1 to destroy."). Addresses
contain module and resource names and for_each keys only (for example the label demo-web, never
the zone), so the summary holds nothing that the code does not show already.

Standard library only. Exit status 0, or 1 when the input is not the JSON of a plan.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# The order of the table; replace = delete and create in either order.
ACTIONS = ("create", "replace", "update", "delete", "forget")


def action_of(actions: list[str]) -> str | None:
    """One word for the actions of a resource change, None for no-op and read."""
    kinds = set(actions)
    if kinds <= {"no-op", "read"}:
        return None
    if {"create", "delete"} <= kinds:
        return "replace"
    for name in ("create", "update", "delete", "forget"):
        if name in kinds:
            return name
    return "+".join(actions)


def summarise(plan: dict[str, Any], title: str) -> tuple[str, dict[str, int]]:
    if not isinstance(plan, dict) or "resource_changes" not in plan and "format_version" not in plan:
        raise ValueError("the input is not the JSON of a saved plan (tofu show -json <planfile>)")
    rows = []
    for change in plan.get("resource_changes") or []:
        action = action_of(list((change.get("change") or {}).get("actions") or []))
        if action:
            rows.append((ACTIONS.index(action) if action in ACTIONS else len(ACTIONS), action, change.get("address")))
    drift = []
    for change in plan.get("resource_drift") or []:
        action = action_of(list((change.get("change") or {}).get("actions") or []))
        if action:
            drift.append((action, change.get("address")))
    counts = {
        "add": sum(1 for _, a, _ in rows if a in ("create", "replace")),
        "change": sum(1 for _, a, _ in rows if a == "update"),
        "destroy": sum(1 for _, a, _ in rows if a in ("delete", "replace")),
        "forget": sum(1 for _, a, _ in rows if a == "forget"),
    }
    lines = [f"### {title}", ""]
    if plan.get("errored"):
        lines += ["The plan stopped with an error; the list below is incomplete.", ""]
    if rows:
        lines += ["| Action | Resource |", "|---|---|"]
        lines += [f"| {action} | `{address}` |" for _, action, address in sorted(rows)]
        lines.append("")
    if drift:
        lines += ["Changed outside OpenTofu since the last apply:", "", "| Change | Resource |", "|---|---|"]
        lines += [f"| {action} | `{address}` |" for action, address in sorted(drift, key=lambda d: str(d[1]))]
        lines.append("")
    if rows:
        forget = f", {counts['forget']} to forget" if counts["forget"] else ""
        lines.append(f"Plan: {counts['add']} to add, {counts['change']} to change, {counts['destroy']} to destroy"
                     f"{forget}.")
    else:
        lines.append("No changes. The infrastructure matches the configuration.")
    return "\n".join(lines) + "\n", counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env", help="environment name for the heading")
    parser.add_argument("--title", help="heading (default: 'Plan of <env>')")
    parser.add_argument("input", nargs="?", default="-", help="JSON of tofu show -json (default: standard input)")
    args = parser.parse_args(argv)
    title = args.title or (f"Plan of {args.env}" if args.env else "Plan")
    try:
        if args.input == "-":
            plan = json.load(sys.stdin)
        else:
            with open(args.input, encoding="utf-8") as handle:
                plan = json.load(handle)
        text, _ = summarise(plan, title)
    except (OSError, ValueError) as exc:
        print(f"plan_summary.py: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
