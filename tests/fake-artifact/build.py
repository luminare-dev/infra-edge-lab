#!/usr/bin/env python3
"""Build a fake server artifact (fx.tar.xz) for the Molecule scenarios and the unit tests.

The archive has the layout of a real Linux server build, with a test double inside:

    run.sh                                    starts the fake server (fake_fxserver.py)
    alpine/opt/cfx-server/fake_fxserver.py    the fake server (copied from this folder)
    alpine/opt/cfx-server/build               the build number, e.g. 35245
    alpine/opt/cfx-server/FAKE-ARTIFACT.txt   says what this is

With --broken, run.sh exits with status 1 instead (a build that never starts), which the
"upgrade" scenario uses to prove the automatic rollback. No real server file is ever downloaded,
copied or re-hosted. Python 3 standard library only.

Usage:
    python3 -I tests/fake-artifact/build.py --build 35245 --out /tmp/fake/35245/fx.tar.xz [--broken]
"""

from __future__ import annotations

import argparse
import io
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MTIME = 1792540800  # fixed (2026-10-21), so that two builds of the same input have equal members

RUN_SH = """#!/bin/bash
# Fake server launcher from tests/fake-artifact/build.py (a test double, not the real server).
SCRIPTPATH="$(dirname "$(readlink -f "$0")")"
exec python3 -I -u "$SCRIPTPATH/alpine/opt/cfx-server/fake_fxserver.py" "$@"
"""

RUN_SH_BROKEN = """#!/bin/bash
# Fake server launcher from tests/fake-artifact/build.py: a build that never starts, on purpose.
echo "fake FXServer {build}: this build is broken on purpose (test double)" >&2
exit 1
"""

NOTE = """This archive is a test double built by tests/fake-artifact/build.py of
luminare-dev/ansible-collection-gameserver. It is not FXServer and contains no part of it.
Build number: {build}{broken}
"""


def members(build: int, broken: bool) -> list[tuple[str, bytes, int]]:
    """(path, content, mode) of every file in the archive."""
    launcher = RUN_SH_BROKEN.format(build=build) if broken else RUN_SH
    return [
        ("run.sh", launcher.encode("utf-8"), 0o755),
        ("alpine/opt/cfx-server/fake_fxserver.py", (HERE / "fake_fxserver.py").read_bytes(), 0o644),
        ("alpine/opt/cfx-server/build", f"{build}\n".encode("utf-8"), 0o644),
        ("alpine/opt/cfx-server/FAKE-ARTIFACT.txt",
         NOTE.format(build=build, broken=" (broken on purpose)" if broken else "").encode("utf-8"), 0o644),
    ]


def build_archive(build: int, out: Path, broken: bool = False) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    files = members(build, broken)
    dirs = sorted({str(Path(p).parents[i]) for p, _, _ in files for i in range(len(Path(p).parents) - 1)})
    with tarfile.open(out, "w:xz") as tar:
        for d in dirs:
            info = tarfile.TarInfo(d)
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, MTIME
            tar.addfile(info)
        for path, content, mode in sorted(files):
            info = tarfile.TarInfo(path)
            info.size, info.mode, info.mtime = len(content), mode, MTIME
            tar.addfile(info, io.BytesIO(content))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("--build", type=int, required=True, help="build number written into the archive")
    p.add_argument("--out", type=Path, required=True, help="path of the fx.tar.xz to write")
    p.add_argument("--broken", action="store_true", help="run.sh exits 1 (a build that never starts)")
    args = p.parse_args(argv)
    if args.build <= 0:
        p.error("--build must be a positive number")
    print(build_archive(args.build, args.out, args.broken))
    return 0


if __name__ == "__main__":
    sys.exit(main())
