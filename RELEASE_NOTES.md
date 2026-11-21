TVPN 1.4.1 — install without starting the VPN

- Make the Linux one-click installer always pass `--no-launch`.
- Add an isolated installer-entrypoint check so installation cannot start a tunnel.
- Keep VPN startup an explicit action after installation.

TVPN 1.4.0 — integration with the future ttools launcher

- Add install-only Linux entrypoint. `--no-launch` never opens the panel or starts VPN; `--defer-system` is for isolated tests.
- Add JSON CLI for version, update check/apply, status, doctor and graceful stop.
- Make TVPN the single updater and add lifecycle exclusion for UI/install/update.
- Add protected shared backend guard. Updates wait for network cleanup; direct VPN start is refused while files are replaced.
- Require cleanup acknowledgement, preserve selected region, fail closed on stop timeout, and keep atomic rollback of user files.
- Make one-time protected system setup rollback its files on failure and serialize against backend start.
- Publish Linux x86_64 installation contract for ttools. macOS/Windows are not claimed as supported in this handoff.

The install-only command is tested in isolated paths with spaces and Cyrillic characters. CI and local tests do not establish VPN tunnels or alter system sudoers.
