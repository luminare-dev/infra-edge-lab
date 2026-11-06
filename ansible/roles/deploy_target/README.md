# deploy_target role

A deploy target for a release pipeline: a CI job may drop a release archive into one folder of
the game server host and nothing else, and the host deploys it once the upload is complete. The
upload account's SSH keys can only run `rrsync`, write-only, into the spool directory; a systemd
path unit starts the deploy script as the game server user when an upload is marked complete. The deploy
script itself belongs to the release pipeline and is not part of this role.

## Requirements

- Managed host: Debian 13 or Ubuntu 24.04, reached as root or with `become: true`.
- The game server user and group (default `fxserver`, created by `luminare.gameserver.fxserver`);
  the role stops when they do not exist.
- `deploy_target_script_src`: the deploy script on the control node.
- With the base role of `luminare.infra_edge` (`AllowGroups sshusers`): the upload account must
  be in `sshusers`, which `deploy_target_ssh_groups` does by default.

## Example playbook

```yaml
- name: Staging game server
  hosts: fxserver
  become: true
  roles:
    - role: deploy_target
      vars:
        deploy_target_script_src: files/luminare-deploy
        deploy_target_authorized_keys:
          - key: ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExampleExample
            comment: ci-staging
            # Uploads arrive through a tunnel connector on the host itself.
            from:
              - 127.0.0.1
              - "::1"
```

The `authorized_keys` line for that key is:

```text
restrict,from="127.0.0.1,::1",command="/usr/bin/rrsync -wo -no-del /srv/luminare/incoming" ssh-ed25519 AAAA... ci-staging
```

## Upload protocol

1. The uploader sends `<resource>-<version>.zip` and `<resource>-<version>.sha256` in one rsync
   call, with group-readable permissions (`rsync --perms --chmod=F640 ...`), to
   `deploy@<host>:` (the forced command maps the path into the spool directory).
2. In a second rsync call it sends the empty marker `<resource>-<version>.ready`.
3. `luminare-deploy.path` (`PathExistsGlob=<spool>/*.ready`) starts `luminare-deploy.service`,
   which runs the deploy script as `deploy_target_run_user`. A half-written upload never has a
   marker, so it never starts a deploy.

## What the deploy script gets and must do

| Environment variable | Value |
|---|---|
| `DEPLOY_SPOOL_DIR` | `deploy_target_spool_dir` |
| `DEPLOY_RELEASE_ROOT` | `deploy_target_release_root` |
| `DEPLOY_KEEP_VERSIONS` | `deploy_target_keep_versions` |
| `DEPLOY_RELOAD_HOOK` | `1` or `0` (`deploy_target_reload_hook`) |

- For every `*.ready` marker: check the archive against its checksum, deploy or reject it, and
  log the result to standard output (the journal of `luminare-deploy.service`).
- Delete the marker and its files in every case: the path unit starts the service again as long
  as a marker exists, and systemd stops the unit after too many quick restarts.
- Read regular files only: the spool directory is writable by the upload keys.
- The service has no privileges (`NoNewPrivileges`, no capabilities, `ProtectSystem=strict`); it
  may write to the spool directory, the release root and `deploy_target_read_write_paths` only,
  with `UMask=0027`.

## Controls

| Control | How | Checked in Molecule (SSH and rsync inside the test container) |
|---|---|---|
| Upload keys can only write | `restrict` and `command="/usr/bin/rrsync -wo -no-del <spool>"` for every key; `authorized_keys` holds exactly the configured keys and belongs to root | a shell command is refused; reading with rsync is refused; `--delete` is refused; remote port forwarding is refused |
| Keys bound to a source address | optional `from=` per key | the key is refused when the connection comes from the container's own private address instead of 127.0.0.1 |
| No privileges for the upload account | shell `/bin/sh` (sshd runs the forced command through it), password field `*` (keys only), supplementary groups exactly `deploy_target_ssh_groups` (admin groups refused) | shell, groups `deploy sshusers`, `sudo -l` shows no rights |
| Spool directory | owner `deploy`, group `fxserver`, mode `2770`: the upload account writes, the game server user reads and deletes, new files inherit the group | owner, group and mode; an uploaded file is group `fxserver`, mode `0640` |
| Only complete uploads deploy | path unit with `PathExistsGlob=<spool>/*.ready`, not `PathChanged=` | the archive alone starts nothing within 3 seconds; the marker starts the script within 10 seconds |
| Deploy runs as the game server user | `User=fxserver`, environment above, sandboxed | the test script reports user `fxserver` and the role's environment, verified the checksum and emptied the spool directory; its line is in the journal |
| Settings checked first | the role stops without a deploy script, without `-wo`, with an invalid key or path, or without the run user | a missing script and options without `-wo` are refused |

## Variables

The table is generated from [`meta/argument_specs.yml`](meta/argument_specs.yml), which Ansible
also uses to check the variables when the role starts.

<!-- argument-specs:deploy_target:begin -->
| Variable | Type | Default | Description |
|---|---|---|---|
| `deploy_target_user` | str | `deploy` | Upload account. Its login shell is /bin/sh (sshd runs the forced command through the shell, so nologin would block it); it gets no sudo rights and no password. |
| `deploy_target_ssh_groups` | list of str | `["sshusers"]` | Groups for the upload account, created as system groups when missing. sshusers is the AllowGroups group of the luminare.infra_edge base role, without which SSH refuses the account. |
| `deploy_target_authorized_keys` | list of dict | `[]` | Public keys of the uploaders (for example a CI job). Each item has key (type and base64, ssh-ed25519, ecdsa-sha2-nistp256/384/521 or ssh-rsa), comment and optionally from (list of source address patterns for the from= option, for example 127.0.0.1 and ::1 when uploads come through a tunnel on the host). Every key gets restrict and the forced rrsync command; the file holds exactly these keys. |
| `deploy_target_rrsync_path` | str | `/usr/bin/rrsync` | rrsync from the rsync package (the role checks that it exists). |
| `deploy_target_rrsync_options` | list of str | `["-wo", "-no-del"]` | rrsync options of the forced command; -wo (write only) is required. Allowed: -wo, -no-del (no deletions), -no-lock, -no-overwrite, -munge (rsync --munge-links). |
| `deploy_target_spool_dir` | str | `/srv/luminare/incoming` | Spool directory, the only place the upload keys can write to. Owner deploy_target_user, group deploy_target_run_group, mode 2770 (new files inherit the group). |
| `deploy_target_run_user` | str | `fxserver` | User of the deploy service (the game server user). It must exist; the role does not create it. |
| `deploy_target_run_group` | str | `fxserver` | Group of the deploy service and of the spool directory. |
| `deploy_target_release_root` | str | `/opt/fxserver/releases` | Directory for unpacked releases, owned by deploy_target_run_user (mode 0750); passed to the script as DEPLOY_RELEASE_ROOT. |
| `deploy_target_script_src` | str | `""` | Deploy script on the control node, installed to deploy_target_script_dest (required; the script itself is not part of this role). See the role README for the environment it gets and what it must do with the files in the spool directory. |
| `deploy_target_script_dest` | str | `/usr/local/sbin/luminare-deploy` | Path of the installed deploy script (root-owned, mode 0755). |
| `deploy_target_unit_name` | str | `luminare-deploy` | Name of the systemd path and service units (the name plus .path and .service). |
| `deploy_target_keep_versions` | int | `3` | Releases to keep per resource; passed to the script as DEPLOY_KEEP_VERSIONS. |
| `deploy_target_reload_hook` | bool | `false` | Whether the script may call a reload hook after a deploy (staging only); passed as DEPLOY_RELOAD_HOOK (1 or 0). |
| `deploy_target_read_write_paths` | list of str | `[]` | More paths the sandboxed service may write to (absolute), for example the resources folder where the script links a release. The spool directory and the release root are always writable. |
| `deploy_target_packages` | list of str | `["rsync", "unzip"]` | Packages for uploads (rsync with rrsync) and for the deploy script (unzip). |
<!-- argument-specs:deploy_target:end -->

## Limitations

- Molecule uses a test script that only checks the checksum and deletes the files; a real deploy
  (unpacking, linking a release, rejecting an archive with a wrong checksum, the reload hook) is
  the deploy script's job and is not tested here.
- Uploads through a tunnel with access control from a CI runner, and the role on a host hardened
  by the base role, are not tested; Molecule emulates the base role's `AllowGroups sshusers`.
