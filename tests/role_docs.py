#!/usr/bin/env python3
"""Generate the variable tables of the roles in ansible/roles from their meta/argument_specs.yml.

Each role documents its variables once, in ansible/roles/<role>/meta/argument_specs.yml (type,
default, description, choices). This script renders them as a Markdown table into every block

    <!-- argument-specs:<role>:begin -->
    ...
    <!-- argument-specs:<role>:end -->

of ansible/roles/<role>/README.md and docs/configuration.md. tests/test_ansible.py fails when a
block differs from the generated table, or when defaults/main.yml and argument_specs.yml disagree.

Usage (from the repository root, needs PyYAML from requirements-test.txt):
    python3 tests/role_docs.py           # report blocks that are out of date (exit 1)
    python3 tests/role_docs.py --write   # rewrite them
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ROLES = ROOT / "ansible" / "roles"
DOC_FILES = ("docs/configuration.md",)
BLOCK_RE = re.compile(
    r"(<!-- argument-specs:(?P<role>[a-z0-9_]+):begin -->\n)(?P<body>.*?)(<!-- argument-specs:(?P=role):end -->)",
    re.DOTALL,
)


def role_names() -> list[str]:
    return sorted(p.parent.parent.name for p in ROLES.glob("*/meta/argument_specs.yml"))


def load_options(role: str) -> dict:
    data = yaml.safe_load((ROLES / role / "meta" / "argument_specs.yml").read_text(encoding="utf-8"))
    return data["argument_specs"]["main"]["options"]


def _code(text: str) -> str:
    return f"`{text}`"


def render_type(spec: dict) -> str:
    kind = spec.get("type", "str")
    if kind == "list" and "elements" in spec:
        kind = f"list of {spec['elements']}"
    if "choices" in spec:
        kind += ": " + ", ".join(_code(str(c)) for c in spec["choices"])
    return kind


def render_default(spec: dict) -> str:
    if "default" not in spec:
        return "(required)"
    value = spec["default"]
    if isinstance(value, bool):
        return _code(str(value).lower())
    if isinstance(value, str):
        return _code(value) if value else _code('""')
    return _code(json.dumps(value))


def render_description(spec: dict) -> str:
    text = spec.get("description", "")
    if isinstance(text, list):
        text = " ".join(text)
    return " ".join(str(text).split()).replace("|", "\\|")


def render_table(role: str) -> str:
    rows = ["| Variable | Type | Default | Description |", "|---|---|---|---|"]
    for name, spec in load_options(role).items():
        rows.append(f"| {_code(name)} | {render_type(spec)} | {render_default(spec)} | {render_description(spec)} |")
    return "\n".join(rows) + "\n"


def doc_files() -> list[Path]:
    files = [ROLES / role / "README.md" for role in role_names()]
    files += [ROOT / rel for rel in DOC_FILES]
    return [f for f in files if f.is_file()]


def render_file(text: str) -> str:
    """Return text with every argument-specs block replaced by the generated table."""
    return BLOCK_RE.sub(lambda m: m.group(1) + render_table(m.group("role")) + m.group(4), text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="rewrite out-of-date blocks")
    args = parser.parse_args(argv)
    stale = []
    for path in doc_files():
        text = path.read_text(encoding="utf-8")
        new = render_file(text)
        if new != text:
            stale.append(path.relative_to(ROOT))
            if args.write:
                path.write_text(new, encoding="utf-8")
    for rel in stale:
        print(f"{'updated' if args.write else 'out of date'}: {rel}")
    return 1 if stale and not args.write else 0


if __name__ == "__main__":
    sys.exit(main())
