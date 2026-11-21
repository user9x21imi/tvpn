# TVPN handoff for ttools

Application ID: `tvpn`. This handoff targets **Linux x86_64 / SteamOS** only.

## Install and run

The distribution bundle is the versioned update archive. Extract it in a temporary
bundle directory and pass actual argument elements, never a shell command string:

```text
install_argv = ["python3", "${BUNDLE}/install.py", "--prefix", "${PREFIX}", "--no-launch"]
launch_argv  = ["python3", "${PREFIX}/launch.py", "--region", "${REGION}"]
version_argv = ["python3", "${PREFIX}/manage.py", "version"]
```

`${PREFIX}` defaults to `${HOME}/.local/share/riseup-vpn`; `${BUNDLE}` is the
extracted archive directory. Paths with spaces and Cyrillic characters are
supported. `--no-launch` prints a JSON result and never opens the UI or connects
VPN. `--defer-system` can be appended for isolated, nonfunctional test installs;
it does not copy files to `/var`, change sudoers, or start networking.

The ordinary user owns the panel. Only the one-time system setup installs a
root-owned backend and exact sudo rules. The Linux installer requests admin
approval when that setup is needed. It never runs the whole launcher as root.
Repeat installation replaces application files atomically and keeps the reserved
`settings`, `.venv`, and state paths. No authentication, password, or account is
needed for Riseup.

Prerequisites: Linux x86_64, Python 3 with `curses`, Bash, curl, iproute2,
`flock`, sudo, and visudo. SteamOS already supplies the basic utilities. The
OpenVPN x86_64 binary and musl runtime are embedded in
`Riseup-Amsterdam-SteamDeck.sh`; they are not downloaded as a separate package.

## Machine control and update owner

TVPN `updater.py` is the sole owner of updates. ttools must call its JSON CLI;
it must not independently download, unpack, or replace TVPN files.

```text
check update = ["python3", "${PREFIX}/manage.py", "check-update"]
apply update = ["python3", "${PREFIX}/manage.py", "update"]
stop         = ["python3", "${PREFIX}/manage.py", "stop", "--timeout", "30"]
status       = ["python3", "${PREFIX}/manage.py", "status"]
```

Manifest: https://raw.githubusercontent.com/user9x21imi/tvpn/main/update.json
Linux archive: https://raw.githubusercontent.com/user9x21imi/tvpn/main/assets/updates/1.4.0.zip
Release asset: https://github.com/user9x21imi/tvpn/releases/download/v1.4.0/TVPN-1.4.0.zip
Platform: `linux-x86_64`; SHA-256 is in the sibling `update.json` and `app.json`.
The archive is checked by both version and SHA-256 before application.

The lifecycle OS lock excludes a second TVPN UI, installer, or updater. The UI
writes a cleanup state and selected region. `stop` sends SIGTERM to the verified
UI process and waits up to 30 seconds for it to finish backend cleanup; timeout
returns failure without killing it. A pending or failed cleanup blocks updates.
Before replacing files, the updater obtains a privileged shared backend guard.
The exact guard sudo rule prevents a direct VPN backend from starting during the
replacement. On an older system installation the protected system installer is
upgraded first; it itself refuses to change a running backend. A guard error
blocks the update. Updates do not reconnect from the machine CLI; ttools can
start again with `selected_region`/`resume_region` returned in JSON. TVPN's own
interactive updater retains its selected region and restarts the UI.

Application file replacement is atomic per file, keeps a rollback copy until
the transaction finishes, and restores changed files on error. System helper
installation has a separate root-owned backup and rollback. User preferences
and tokens are excluded from archives. TVPN does not persist Riseup passwords
or auth sessions. Temporary certificates and private key live in a root-created
`/run` directory and cleanup removes that directory after disconnect.

## Verification boundary

Verified locally without starting a VPN or changing system rules:

- 80 tests pass on Linux, including isolated repeat installation with spaces and
  Cyrillic, settings preservation, update checksum/version checks, rollback,
  lifecycle exclusion, cleanup ACK, stop timeout, guard lock behavior, and UI PTY.
- `install.py --prefix <temporary Unicode path> --no-launch --defer-system`
  installed version 1.4.0; `manage.py version` and `doctor` returned JSON.
- `manage.py doctor` reports platform/prerequisites only; it does not test network.
- `bash -n` and Python compilation pass. The archive contains the embedded
  OpenVPN runtime and contains no `.pem`, `.key`, `.ovpn`, log, or PID files.
- The protected helper and sudoers were not changed during these tests.

Not verified: a real Riseup tunnel, certificate request, DNS or route restoration
on this run. No physical Steam Deck connection was attempted. macOS and Windows
remain development ports; this handoff does not advertise them as supported.
CI tests do not establish VPN tunnels. The app is an independent client, not an
official Riseup product.
