# Fake server build (test double)

The local environment never downloads a real game server build. `playbooks/local_prepare.yml`
builds a small `fx.tar.xz` with `build.py`, copies it to the game server hosts, and the
inventory points `fxserver_artifact_url` at it with a `file://` URL
(`ansible/inventories/local/group_vars/fxserver.yml`). The archive has the layout of a Linux
server build (`run.sh` at the top), but `run.sh` starts `fake_fxserver.py`, a Python 3
standard-library HTTP server. It is neither FXServer nor txAdmin and contains no part of them.

| File | Purpose |
|---|---|
| `build.py` | Writes the archive: `python3 -I build.py --build 35245 --out <dir>/fx.tar.xz`. |
| `fake_fxserver.py` | The fake server: the game server's `/info.json`, `/dynamic.json`, `/players.json` (synthetic players only) and `/perf/` (with HTTP basic auth when `sv_prometheusBasicAuthUser` or `sv_prometheusBasicAuthPassword` is set), and, started without `+exec` as the `txadmin` mode does, a fake txAdmin page that starts the game server from `server.cfg`. It refuses to start without `sv_licenseKey` and never prints it. Its docstring lists every endpoint and setting. |
| `SHA256SUMS` | The sha256 of both files; `tests/test_fake_artifact.py` fails when a file no longer matches. |

Both files are copies, unchanged, of `tests/fake-artifact/` of
[luminare-dev/ansible-collection-gameserver](https://github.com/luminare-dev/ansible-collection-gameserver),
taken on 2026-10-22 before its first release (the collection's own tests describe their
behaviour in full). That collection builds the release tarball without them, so this repository
keeps its own copy. Their texts still name that collection's Molecule scenarios as their user.
To take a newer version, copy both files from the collection's release tag, run
`sha256sum build.py fake_fxserver.py > SHA256SUMS` in this folder and the unit tests.

`tests/test_fake_artifact.py` checks what the local environment relies on: the archive layout,
`/info.json` with the build number and `/perf/` behind basic auth when the server is started
with `server.cfg`, the game server started by the fake txAdmin from `server.cfg`, and that the
license key never appears in the output.
