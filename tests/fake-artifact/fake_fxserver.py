#!/usr/bin/env python3
"""Fake game server for tests: a stand-in for FXServer and txAdmin, not the real software.

The Molecule scenarios install a fake artifact (fx.tar.xz, built by build.py next to this file)
instead of a real server build, so that the fxserver role's systemd unit really starts and the
tests can query the same HTTP endpoints as on a real server. Python 3 standard library only; every
answer is synthetic.

Command line, as the role's unit passes it through run.sh (working directory = server-data):

    fake_fxserver.py +exec <file> [+set <name> <value>] ...   game server only ("plain" mode)
    fake_fxserver.py                                           txAdmin mode (no +exec)

Like the real launcher, the fake starts txAdmin when the command line has no "+exec" argument.

Config files are read like the real server reads them: one command per line, "#" and "//" start
comments, values may be quoted. The fake understands:

    endpoint_add_tcp "<address>:<port>"      where to listen (default 0.0.0.0:30120)
    exec <file>                              run another file (for example secrets.cfg)
    sv_licenseKey "<value>"                  required, as on the real server; never printed
    set|sets|setr <name> <value>             convars, e.g. sv_projectName, onesync,
                                             sv_prometheusBasicAuthUser/Password (protect /perf/)
    sv_hostname, sv_maxclients, ...          any other "sv_<name> <value>" line is a convar too
    ensure|start <resource>                  listed in /info.json

Game server HTTP endpoints:

    /info.json      server string with the build number, convars, resources
    /dynamic.json   player count ("clients") and sv_maxclients
    /players.json   synthetic players (player-1, license:000...1, ...)
    /perf/          Prometheus text (tickTime histograms). When sv_prometheusBasicAuthUser or
                    sv_prometheusBasicAuthPassword is set, only with exactly these HTTP basic
                    auth credentials (401 otherwise); when both are empty, to anyone, as build
                    35245 does (PerfHttpHandler.cpp; the fake has no rate limit)

txAdmin mode reads the TXHOST_* environment variables with the rules of txAdmin 8.1.1
(core/boot/getHostVars.ts and core/globalData.ts): a value in quotes or an invalid value stops
it with exit status 1 (the fake names the variable but, unlike txAdmin, never prints the value).
It then behaves like a txAdmin whose one-time web setup is done, with server-data = the working
directory and server.cfg as the config file:

    TXHOST_DATA_PATH        txData folder (absolute; default: txData next to run.sh); the fake
                            creates it and, with TXHOST_DEFAULT_ACCOUNT, writes admins.json (0600)
    TXHOST_TXA_PORT         web port (default 40120; 30120 is refused)
    TXHOST_INTERFACE        IPv4 address for the web port (default 0.0.0.0); when set, every
                            endpoint_add_tcp in server.cfg must use it or the game server is not
                            started (as txAdmin does)
    TXHOST_FXS_PORT         when set, the game port in server.cfg must equal it
    TXHOST_MAX_SLOTS        when set, sv_maxclients must not exceed it
    TXHOST_QUIET_MODE       "true": the game server's output is not printed
    TXHOST_API_TOKEN        token for /host/status ("disabled" = no token needed)
    TXHOST_DEFAULT_ACCOUNT  username:fivemId[:bcrypt hash], at least an id or a hash
    TXHOST_GAME_NAME, TXHOST_TXA_URL, TXHOST_PROVIDER_NAME, TXHOST_DEFAULT_DB*,
    TXHOST_DEFAULT_CFXKEY, TXHOST_IGNORE_DEPRECATED_CONFIGS: checked or accepted, not used

txAdmin web endpoints (on TXHOST_INTERFACE:TXHOST_TXA_PORT):

    /, /login       a fake page (status 200), like txAdmin before and after its setup
    /host/status    with the token in the header x-txadmin-envtoken or the query ?envtoken=:
                    isConfigured, status ONLINE/OFFLINE, playerCount, playerSlots, ...; like
                    txAdmin it answers status 200 with {"error": ...} for a missing, wrong or
                    unconfigured token

The game server keeps running inside the same process; a game server that cannot start (no
license key, a refused endpoint or slot count) leaves txAdmin running with status OFFLINE, as the
real txAdmin does.

Environment: FAKE_CLIENTS (number of synthetic players, default 3). The build number is read
from the file "build" next to this script (build.py writes it).
"""

from __future__ import annotations

import base64
import hmac
import ipaddress
import json
import os
import re
import shlex
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
# The folder that holds run.sh (HERE is alpine/opt/cfx-server inside the artifact).
ARTIFACT_ROOT = HERE.parent.parent.parent
BUCKETS = ("0.005", "0.01", "0.025", "0.05", "0.075", "0.1", "0.25", "0.5", "0.75", "1", "2.5", "5",
           "7.5", "10", "+Inf")
# Fake tick rates (ticks per second) and the share of ticks per bucket; every tick takes 2-8 ms.
THREADS = {"svMain": 20, "svNetwork": 100, "svSync": 40}
SHARES = (0.9, 1.0)  # <= 5 ms: 90 %, <= 10 ms: 100 %
MAX_EXEC_DEPTH = 8

# txAdmin 8.1.1 (bundled with build 35245): the rules the fake applies to TXHOST_* values.
TXADMIN_VERSION = "8.1.1"
TXA_DEFAULT_PORT = 40120
TXA_RESERVED_PORTS = range(40120, 40151)  # never a game port (fxsConfigHelper.ts)
API_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,48}$")
USERNAME_RE = re.compile(r"^\w[\w.-]{1,18}\w$", re.ASCII)
FIVEM_ID_RE = re.compile(r"^\d{1,8}$")
BCRYPT_RE = re.compile(r"^\$2[aby]\$[0-9]{2}\$[A-Za-z0-9./]{53}$")
PROVIDER_NAME_RE = re.compile(r"^[a-zA-Z0-9_.\- ]{2,16}$")
STATUS_DOCS = "https://aka.cfx.re/txadmin-env-config"


class ConfigError(Exception):
    """A config file could not be read."""


class HostConfigError(Exception):
    """A TXHOST_* environment variable is invalid (txAdmin stops at boot)."""


class Config:
    def __init__(self) -> None:
        self.endpoint = ("0.0.0.0", 30120)
        self.convars: dict[str, str] = {}
        self.license_key = ""
        self.resources: list[str] = []

    def command(self, words: list[str], depth: int) -> None:
        if not words:
            return
        name, args = words[0], words[1:]
        lname = name.lower()
        if lname in ("+exec", "exec") and args:
            self.exec_file(args[0], depth + 1)
        elif lname == "endpoint_add_tcp" and args:
            host, _, port = args[0].rpartition(":")
            self.endpoint = (host.strip("[]") or "0.0.0.0", int(port))
        elif lname == "sv_licensekey" and args:
            self.license_key = args[0]
        elif lname in ("+set", "set", "sets", "setr") and len(args) >= 2:
            if args[0].lower() == "sv_licensekey":
                self.license_key = args[1]
            else:
                self.convars[args[0]] = args[1]
        elif lname in ("ensure", "start") and args:
            if args[0] not in self.resources:
                self.resources.append(args[0])
        elif lname.startswith("sv_") and args:
            self.convars[name] = args[0]

    def exec_file(self, filename: str, depth: int) -> None:
        if depth > MAX_EXEC_DEPTH:
            raise ConfigError(f"exec nested deeper than {MAX_EXEC_DEPTH} levels at {filename}")
        try:
            text = Path(filename).read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"cannot read {filename}: {exc.strerror}") from exc
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", "//")):
                continue
            try:
                words = shlex.split(line, comments=False, posix=True)
            except ValueError as exc:
                raise ConfigError(f"{filename}: cannot parse a line ({exc})") from exc
            self.command(words, depth)

    def convar(self, name: str, default: str = "") -> str:
        for key, value in self.convars.items():
            if key.lower() == name.lower():
                return value
        return default

    @classmethod
    def from_argv(cls, argv: list[str]) -> Config:
        cfg = cls()
        i = 0
        while i < len(argv):
            word = argv[i]
            if word.lower() == "+exec" and i + 1 < len(argv):
                cfg.command(["+exec", argv[i + 1]], 0)
                i += 2
            elif word.lower() == "+set" and i + 2 < len(argv):
                cfg.command(["+set", argv[i + 1], argv[i + 2]], 0)
                i += 3
            else:
                i += 1
        return cfg


class HostConfig:
    """The TXHOST_* settings, checked like txAdmin 8.1.1 checks them at boot."""

    def __init__(self, data_path: Path) -> None:
        self.data_path = data_path
        self.txa_port = TXA_DEFAULT_PORT
        self.interface: str | None = None
        self.fxs_port: int | None = None
        self.max_slots: int | None = None
        self.quiet = False
        self.api_token: str | None = None
        self.game_name: str | None = None
        self.txa_url: str | None = None
        self.account: tuple[str, str | None, str | None] | None = None

    @staticmethod
    def _int(key: str, value: str) -> int:
        if not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
            raise HostConfigError(f"{key} must be a positive whole number")
        return int(value)

    @classmethod
    def from_env(cls, env: dict[str, str], default_data_path: Path) -> HostConfig:
        values: dict[str, str] = {}
        for key, value in env.items():
            if not key.startswith("TXHOST_") or value == "":
                continue
            if value[:1] in "\"'" or value[-1:] in "\"'":
                raise HostConfigError(f"{key}: the value is surrounded by quotes; remove them")
            values[key.removeprefix("TXHOST_")] = value
        host = cls(default_data_path)
        if "DATA_PATH" in values:
            if not os.path.isabs(values["DATA_PATH"]):
                raise HostConfigError("TXHOST_DATA_PATH must be an absolute path")
            host.data_path = Path(values["DATA_PATH"])
        if "TXA_PORT" in values:
            host.txa_port = cls._int("TXHOST_TXA_PORT", values["TXA_PORT"])
            if host.txa_port == 30120:
                raise HostConfigError("TXHOST_TXA_PORT cannot be 30120")
        if "FXS_PORT" in values:
            host.fxs_port = cls._int("TXHOST_FXS_PORT", values["FXS_PORT"])
            if host.fxs_port in TXA_RESERVED_PORTS:
                raise HostConfigError("TXHOST_FXS_PORT cannot be between 40120 and 40150")
        if "INTERFACE" in values:
            try:
                ipaddress.IPv4Address(values["INTERFACE"])
            except ValueError:
                raise HostConfigError("TXHOST_INTERFACE must be an IPv4 address") from None
            host.interface = values["INTERFACE"]
        if "MAX_SLOTS" in values:
            host.max_slots = cls._int("TXHOST_MAX_SLOTS", values["MAX_SLOTS"])
        host.quiet = values.get("QUIET_MODE") == "true"
        if "API_TOKEN" in values:
            if values["API_TOKEN"] != "disabled" and not API_TOKEN_RE.match(values["API_TOKEN"]):
                raise HostConfigError("TXHOST_API_TOKEN must be 'disabled' or 16-48 letters, digits, '_' or '-'")
            host.api_token = values["API_TOKEN"]
        if "GAME_NAME" in values:
            if values["GAME_NAME"] not in ("fivem", "redm"):
                raise HostConfigError("TXHOST_GAME_NAME must be fivem or redm")
            host.game_name = values["GAME_NAME"]
        if "TXA_URL" in values:
            if not re.match(r"^https?://[^\s/]+", values["TXA_URL"]):
                raise HostConfigError("TXHOST_TXA_URL must be a URL")
            host.txa_url = values["TXA_URL"]
        if "PROVIDER_NAME" in values and (
                not PROVIDER_NAME_RE.match(values["PROVIDER_NAME"])
                or re.search(r"[_.\- ]{2,}", values["PROVIDER_NAME"])
                or not re.match(r"^[a-zA-Z0-9].*[a-zA-Z0-9]$", values["PROVIDER_NAME"])):
            raise HostConfigError("TXHOST_PROVIDER_NAME is not a valid provider name")
        if "DEFAULT_ACCOUNT" in values:
            host.account = cls._account(values["DEFAULT_ACCOUNT"])
        return host

    @staticmethod
    def _account(value: str) -> tuple[str, str | None, str | None]:
        parts = value.split(":")
        if len(parts) not in (2, 3):
            raise HostConfigError("TXHOST_DEFAULT_ACCOUNT must be username:fivemId or username:fivemId:bcrypt")
        name, fivem_id, password = (parts + [""])[:3]
        if not USERNAME_RE.match(name):
            raise HostConfigError("TXHOST_DEFAULT_ACCOUNT: invalid username")
        if fivem_id and not FIVEM_ID_RE.match(fivem_id):
            raise HostConfigError("TXHOST_DEFAULT_ACCOUNT: the FiveM ID must be 1-8 digits")
        if password and not BCRYPT_RE.match(password):
            raise HostConfigError("TXHOST_DEFAULT_ACCOUNT: the password must be a bcrypt hash")
        if not fivem_id and not password:
            raise HostConfigError("TXHOST_DEFAULT_ACCOUNT needs a FiveM ID or a password hash")
        return name, fivem_id or None, password or None


def read_build() -> str:
    try:
        return (HERE / "build").read_text(encoding="utf-8").strip() or "0"
    except OSError:
        return "0"


class FakeServer:
    def __init__(self, cfg: Config, build: str, clients: int) -> None:
        self.cfg = cfg
        self.build = build
        self.started = time.monotonic()
        self.max_clients = int(cfg.convar("sv_maxclients", "32") or "32")
        self.clients = max(0, min(clients, self.max_clients))

    def info(self) -> dict:
        onesync = self.cfg.convar("onesync", "off").lower()
        variables = {
            "sv_maxClients": str(self.max_clients),
            "sv_projectName": self.cfg.convar("sv_projectName"),
            "sv_projectDesc": self.cfg.convar("sv_projectDesc"),
            "locale": self.cfg.convar("locale", "en-US"),
            "onesync_enabled": "true" if onesync in ("on", "legacy", "true") else "false",
            "gamename": "gta5",
        }
        if self.cfg.convar("sv_enforceGameBuild"):
            variables["sv_enforceGameBuild"] = self.cfg.convar("sv_enforceGameBuild")
        return {
            "enhancedHostSupport": True,
            "icon": "",
            "requestSteamTicket": "off",
            "resources": list(self.cfg.resources),
            "server": f"FXServer-master SERVER v1.0.0.{self.build} linux",
            "vars": variables,
            "version": 1,
        }

    def dynamic(self) -> dict:
        return {
            "clients": self.clients,
            "gametype": "",
            "hostname": self.cfg.convar("sv_hostname", "Fake game server"),
            "iv": "0",
            "mapname": "",
            "sv_maxclients": str(self.max_clients),
        }

    def players(self) -> list:
        return [
            {"endpoint": "127.0.0.1", "id": i, "identifiers": [f"license:{i:040d}"],
             "name": f"player-{i}", "ping": 42}
            for i in range(1, self.clients + 1)
        ]

    def perf(self) -> str:
        uptime = time.monotonic() - self.started
        lines = ["# HELP tickTime Time spent in one server tick (synthetic data from the fake server).",
                 "# TYPE tickTime histogram"]
        for thread, rate in THREADS.items():
            count = int(uptime * rate) + 1
            for le in BUCKETS:
                share = SHARES[0] if le == "0.005" else SHARES[1]
                lines.append(f'tickTime_bucket{{name="{thread}",le="{le}"}} {int(count * share)}')
            lines.append(f'tickTime_sum{{name="{thread}"}} {count * 0.004:.6f}')
            lines.append(f'tickTime_count{{name="{thread}"}} {count}')
        return "\n".join(lines) + "\n"

    def perf_authorised(self, header: str | None) -> bool:
        user = self.cfg.convar("sv_prometheusBasicAuthUser")
        password = self.cfg.convar("sv_prometheusBasicAuthPassword")
        if not user and not password:
            return True  # open to anyone, like the real server without credentials
        if not header or not header.startswith("Basic "):
            return False
        try:
            given = base64.b64decode(header[6:].strip(), validate=True)
        except ValueError:
            return False
        return hmac.compare_digest(given, f"{user}:{password}".encode("utf-8"))


class BaseHandler(BaseHTTPRequestHandler):
    sys_version = ""
    log_prefix = "fake"
    log_requests = True

    def send_body(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, data: object) -> None:
        self.send_body(200, json.dumps(data).encode("utf-8"), "application/json")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 (base class name)
        # Path and status only: no client addresses and no query strings (tokens) in the log.
        if self.log_requests:
            sys.stdout.write(f"{self.log_prefix}: {self.command} {self.path.split('?', 1)[0]} -> {args[1]}\n")
            sys.stdout.flush()


def make_handler(server: FakeServer, log_requests: bool = True) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHandler):
        server_version = "FakeFXServer"
        log_prefix = "fake FXServer"

        def do_GET(self) -> None:  # noqa: N802 (http.server naming)
            path = self.path.split("?", 1)[0]
            if path == "/info.json":
                self.send_json(server.info())
            elif path == "/dynamic.json":
                self.send_json(server.dynamic())
            elif path == "/players.json":
                self.send_json(server.players())
            elif path in ("/perf", "/perf/"):
                if server.perf_authorised(self.headers.get("Authorization")):
                    self.send_body(200, server.perf().encode("utf-8"), "text/plain; version=0.0.4")
                else:
                    self.send_body(401, b"Unauthorized\n", "text/plain",
                                   {"WWW-Authenticate": 'Basic realm="perf"'})
            else:
                self.send_body(404, b"Not found\n", "text/plain")

        do_HEAD = do_GET

    Handler.log_requests = log_requests
    return Handler


class FakeTxAdmin:
    """The txAdmin part: web port, /host/status and the game server it supervises."""

    def __init__(self, host: HostConfig) -> None:
        self.host = host
        self.game: FakeServer | None = None
        self.game_cfg: Config | None = None
        self.offline_reason = "not started"

    def start_game(self, build: str, clients: int) -> ThreadingHTTPServer | None:
        """Start the game server from server.cfg in the working directory, with txAdmin's checks."""
        try:
            cfg = Config.from_argv(["+exec", "server.cfg"])
        except ConfigError as exc:
            self.offline_reason = str(exc)
            return None
        iface, port = cfg.endpoint
        max_clients = int(cfg.convar("sv_maxclients", "32") or "32")
        if not cfg.license_key:
            self.offline_reason = "sv_licenseKey is not set; the server refuses to start without it"
        elif port in TXA_RESERVED_PORTS or port == self.host.txa_port:
            self.offline_reason = f"the endpoint_add_tcp port {port} is reserved for txAdmin"
        elif self.host.interface and iface != self.host.interface:
            self.offline_reason = f"the endpoint_add_tcp interface MUST be {self.host.interface} (TXHOST_INTERFACE)"
        elif self.host.fxs_port and port != self.host.fxs_port:
            self.offline_reason = f"the endpoint_add_tcp port MUST be {self.host.fxs_port} (TXHOST_FXS_PORT)"
        elif self.host.max_slots and max_clients > self.host.max_slots:
            self.offline_reason = f"sv_maxclients {max_clients} is above TXHOST_MAX_SLOTS {self.host.max_slots}"
        else:
            self.game_cfg = cfg
            self.game = FakeServer(cfg, build, clients)
            httpd = ThreadingHTTPServer(cfg.endpoint, make_handler(self.game, log_requests=not self.host.quiet))
            httpd.daemon_threads = True
            return httpd
        return None

    def status(self) -> dict:
        cwd = Path.cwd()
        cfg = self.game_cfg
        return {
            "isConfigured": True,
            "dataPath": str(cwd),
            "cfgPath": str(cwd / "server.cfg"),
            "playerCount": self.game.clients if self.game else 0,
            "status": "ONLINE" if self.game else "OFFLINE",
            "cfxId": None,
            "gameName": self.host.game_name,
            "joinDeepLink": None,
            "joinLink": None,
            "playerSlots": self.game.max_clients if self.game else None,
            "projectName": cfg.convar("sv_projectName") if cfg else None,
            "projectDesc": cfg.convar("sv_projectDesc") if cfg else None,
        }

    def token_error(self, header: str | None, query: str | None) -> dict | None:
        """The checks of txAdmin's hostAuthMw for /host/status (all answers have status 200)."""
        token = self.host.api_token
        if token == "disabled":
            return None
        if not token:
            return {"error": "token not configured",
                    "desc": "need to configure the TXHOST_API_TOKEN environment variable to be able "
                            "to use the status endpoint", "docs": STATUS_DOCS}
        if header and query:
            return {"error": "token conflict", "desc": "cannot use both header and query token", "docs": STATUS_DOCS}
        given = header or query
        if not given:
            return {"error": "token missing", "desc": "a token needs to be provided in the header or query string",
                    "docs": STATUS_DOCS}
        if not hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8")):
            return {"error": "invalid token",
                    "desc": "the token provided does not match the TXHOST_API_TOKEN environment variable",
                    "docs": STATUS_DOCS}
        return None

    def write_admins(self) -> bool:
        """admins.json from TXHOST_DEFAULT_ACCOUNT on the first boot (an existing file is kept)."""
        admins = self.host.data_path / "admins.json"
        if self.host.account is None or admins.exists():
            return False
        name, fivem_id, password = self.host.account
        account = {"name": name, "master": True, "password_hash": password,
                   "providers": {"citizenfx": {"id": f"fivem:{fivem_id}"}} if fivem_id else {},
                   "fake": "written by the fake txAdmin of tests/fake-artifact"}
        fd = os.open(admins, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump([account], fh, indent=2)
        return True


def make_txadmin_handler(txadmin: FakeTxAdmin) -> type[BaseHTTPRequestHandler]:
    page = (f"<!doctype html><html><head><title>fake txAdmin</title></head><body>fake txAdmin "
            f"{TXADMIN_VERSION} (test double)</body></html>\n").encode("utf-8")

    class Handler(BaseHandler):
        server_version = "FakeTxAdmin"
        log_prefix = "fake txAdmin"

        def do_GET(self) -> None:  # noqa: N802 (http.server naming)
            url = urlsplit(self.path)
            if url.path in ("/", "/login"):
                self.send_body(200, page, "text/html; charset=utf-8")
            elif url.path == "/host/status":
                query = parse_qs(url.query).get("envtoken", [None])[0]
                error = txadmin.token_error(self.headers.get("x-txadmin-envtoken"), query)
                self.send_json(error if error else txadmin.status())
            else:
                self.send_body(404, b"Not found\n", "text/plain")

        do_HEAD = do_GET

    return Handler


def serve(httpds: list[ThreadingHTTPServer], name: str) -> int:
    """Serve every server in its own thread until SIGTERM, then close them and return 0."""

    def stop(signum: int, _frame: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    for httpd in httpds:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        while True:
            time.sleep(3600)
    except SystemExit:
        return 0
    finally:
        for httpd in httpds:
            httpd.shutdown()
            httpd.server_close()
        print(f"{name}: stopped", flush=True)


def main_txadmin(build: str, clients: int) -> int:
    try:
        host = HostConfig.from_env(dict(os.environ), ARTIFACT_ROOT / "txData")
    except HostConfigError as exc:
        print(f"fake txAdmin {TXADMIN_VERSION}: invalid TXHOST setting: {exc}", file=sys.stderr, flush=True)
        return 1
    txadmin = FakeTxAdmin(host)
    try:
        (host.data_path / "default").mkdir(parents=True, exist_ok=True)
        created = txadmin.write_admins()
    except OSError as exc:
        print(f"fake txAdmin {TXADMIN_VERSION}: cannot write the data path {host.data_path}: {exc.strerror}",
              file=sys.stderr, flush=True)
        return 1
    iface = host.interface or "0.0.0.0"
    token_state = {None: "not set", "disabled": "disabled (no token needed)"}.get(
        host.api_token, "set (value not shown)")
    web = ThreadingHTTPServer((iface, host.txa_port), make_txadmin_handler(txadmin))
    web.daemon_threads = True
    print(f"fake txAdmin {TXADMIN_VERSION} (test double) on build {build}: listening on {iface}:{host.txa_port}; "
          f"data path {host.data_path}; API token {token_state}; "
          f"quiet mode {'on' if host.quiet else 'off'}", flush=True)
    if created:
        print(f"fake txAdmin: created the master account {host.account[0]} from TXHOST_DEFAULT_ACCOUNT", flush=True)
    game = txadmin.start_game(build, clients)
    if game is None:
        print(f"fake txAdmin: game server not started: {txadmin.offline_reason}", flush=True)
    else:
        print(f"fake txAdmin: game server started from server.cfg, listening on "
              f"{game.server_address[0]}:{game.server_address[1]}; sv_licenseKey is set (value not shown)",
              flush=True)
    return serve([web] + ([game] if game else []), f"fake txAdmin {TXADMIN_VERSION}")


def main(argv: list[str]) -> int:
    build = read_build()
    clients = int(os.environ.get("FAKE_CLIENTS", "3"))
    # The real launcher (code/server/launcher/src/Server.cpp) starts txAdmin unless "+exec" is given.
    if "+exec" not in argv:
        return main_txadmin(build, clients)
    try:
        cfg = Config.from_argv(argv)
    except ConfigError as exc:
        print(f"fake FXServer {build}: {exc}", file=sys.stderr, flush=True)
        return 1
    if not cfg.license_key:
        print(f"fake FXServer {build}: sv_licenseKey is not set; the real server refuses to start "
              "without it, so the fake does too", file=sys.stderr, flush=True)
        return 1
    fake = FakeServer(cfg, build, clients)
    httpd = ThreadingHTTPServer(cfg.endpoint, make_handler(fake))
    httpd.daemon_threads = True
    auth = ("on" if cfg.convar("sv_prometheusBasicAuthUser") or cfg.convar("sv_prometheusBasicAuthPassword")
            else "off (open to anyone)")
    print(f"fake FXServer {build}: listening on {cfg.endpoint[0]}:{cfg.endpoint[1]}; sv_licenseKey "
          f"is set (value not shown); /perf/ basic auth {auth}", flush=True)
    return serve([httpd], f"fake FXServer {build}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
