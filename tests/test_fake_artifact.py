"""The fake server build of tests/fake-artifact/ that the local environment installs instead of a
real game server build (playbooks/local_prepare.yml, ansible/inventories/local/group_vars/).

The files are copies of another repository's test double (tests/fake-artifact/README.md); these
tests pin that they are unchanged and that they do what the local environment relies on: the
archive layout, /info.json with the build number and /perf/ behind basic auth when started with
server.cfg ("plain"), the game server started by the fake txAdmin from server.cfg ("txadmin",
the mode of the local environment), and no license key in the output. Standard library only;
the fake runs as a subprocess on free loopback ports.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKE_DIR = ROOT / "tests" / "fake-artifact"
BUILD = 35245
# Test values only: the fake accepts any key, and none of these is a secret.
KEY = "unittestlicensekey0123456789"
PERF_PASSWORD = "unittestperfpassword0123456789"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str, auth: tuple[str, str] | None = None) -> tuple[int, str]:
    request = urllib.request.Request(url)
    if auth:
        request.add_header("Authorization", "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode())
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:  # noqa: S310 (loopback test server)
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, exc.read().decode("utf-8")


class FakeBuild:
    """The archive built by build.py, unpacked, and a server-data folder as the roles write it."""

    def __init__(self, tmp: Path, port: int):
        archive = tmp / "fx.tar.xz"
        subprocess.run([sys.executable, "-I", str(FAKE_DIR / "build.py"), "--build", str(BUILD),
                        "--out", str(archive)], check=True, capture_output=True, timeout=60)
        self.archive = archive
        self.unpacked = tmp / "artifact"
        with tarfile.open(archive) as tar:
            tar.extractall(self.unpacked, filter="data")
        self.server_data = tmp / "server-data"
        self.server_data.mkdir()
        (self.server_data / "server.cfg").write_text(
            f'endpoint_add_tcp "127.0.0.1:{port}"\n'
            f'endpoint_add_udp "127.0.0.1:{port}"\n'
            'sv_hostname "Unit test server"\n'
            "sv_maxclients 32\n"
            "exec secrets.cfg\n", encoding="utf-8")
        (self.server_data / "secrets.cfg").write_text(
            f'sv_licenseKey "{KEY}"\n'
            'set sv_prometheusBasicAuthUser "prometheus"\n'
            f'set sv_prometheusBasicAuthPassword "{PERF_PASSWORD}"\n', encoding="utf-8")

    def start(self, *args: str, env: dict[str, str] | None = None) -> subprocess.Popen:
        return subprocess.Popen(["bash", str(self.unpacked / "run.sh"), *args], cwd=self.server_data,
                                env={**os.environ, **(env or {})}, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)


def wait_for(url: str, proc: subprocess.Popen, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"the fake exited with {proc.returncode}: {proc.stdout.read()}")
        try:
            get(url)
            return
        except OSError:
            time.sleep(0.2)
    raise AssertionError(f"{url} did not answer within {timeout} s")


def stop(proc: subprocess.Popen) -> str:
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return out or ""


class CopyTest(unittest.TestCase):
    def test_files_match_their_recorded_sha256(self):
        lines = (FAKE_DIR / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sorted(line.split()[1] for line in lines), ["build.py", "fake_fxserver.py"])
        for line in lines:
            digest, name = line.split()
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((FAKE_DIR / name).read_bytes()).hexdigest(), digest,
                                 "the copy changed; see tests/fake-artifact/README.md")

    def test_the_local_inventory_installs_this_build(self):
        group_vars = (ROOT / "ansible" / "inventories" / "local" / "group_vars" / "fxserver.yml").read_text(
            encoding="utf-8")
        self.assertIn(f"fxserver_build: {BUILD}\n", group_vars)
        self.assertIn('fxserver_artifact_url: "file:///', group_vars)
        self.assertNotIn("runtime.fivem.net", group_vars)
        prepare = (ROOT / "ansible" / "playbooks" / "local_prepare.yml").read_text(encoding="utf-8")
        self.assertIn("tests/fake-artifact/build.py", prepare)


class FakeServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.port = free_port()
        self.build = FakeBuild(Path(tmp.name), self.port)

    def test_archive_layout(self):
        with tarfile.open(self.build.archive) as tar:
            names = tar.getnames()
            run_sh = tar.getmember("run.sh")
        self.assertIn("alpine/opt/cfx-server/fake_fxserver.py", names)
        self.assertEqual(run_sh.mode & 0o777, 0o755)
        self.assertIn("test double", (self.build.unpacked / "alpine/opt/cfx-server/FAKE-ARTIFACT.txt").read_text(
            encoding="utf-8"))

    def test_plain_mode_answers_info_json_and_protects_perf(self):
        proc = self.build.start("+exec", "server.cfg")
        base = f"http://127.0.0.1:{self.port}"
        try:
            wait_for(f"{base}/info.json", proc)
            status, body = get(f"{base}/info.json")
            self.assertEqual(status, 200)
            self.assertRegex(json.loads(body)["server"], rf"\b{BUILD}\b")
            self.assertEqual(get(f"{base}/perf/")[0], 401)
            status, perf = get(f"{base}/perf/", auth=("prometheus", PERF_PASSWORD))
            self.assertEqual(status, 200)
            self.assertIn("tickTime", perf)
        finally:
            out = stop(proc)
        self.assertNotIn(KEY, out)
        self.assertNotIn(PERF_PASSWORD, out)

    def test_txadmin_mode_starts_the_game_server_from_server_cfg(self):
        tx_port = free_port()
        proc = self.build.start(env={"TXHOST_TXA_PORT": str(tx_port),
                                     "TXHOST_DATA_PATH": str(self.build.server_data.parent / "txData"),
                                     "TXHOST_QUIET_MODE": "true"})
        try:
            wait_for(f"http://127.0.0.1:{tx_port}/", proc)
            self.assertEqual(get(f"http://127.0.0.1:{tx_port}/")[0], 200)
            wait_for(f"http://127.0.0.1:{self.port}/info.json", proc)
            status, body = get(f"http://127.0.0.1:{self.port}/info.json")
            self.assertEqual(status, 200)
            self.assertRegex(json.loads(body)["server"], rf"\b{BUILD}\b")
        finally:
            out = stop(proc)
        self.assertNotIn(KEY, out)

    def test_refuses_to_start_without_a_license_key(self):
        (self.build.server_data / "secrets.cfg").write_text("", encoding="utf-8")
        proc = self.build.start("+exec", "server.cfg")
        try:
            out, _ = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            stop(proc)
            self.fail("the fake kept running without a license key")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("sv_licenseKey", out)


if __name__ == "__main__":
    unittest.main()
