TVPN 1.3.0

- Rename the GitHub project to user9x21imi/tvpn; retain compatibility with legacy updater archive URLs.
- Redesign the README around TVPN, the interactive ASCII globe, controls and live traffic.
- Add clearly separated Linux, macOS and Windows download buttons.
- Add Linux installer and desktop launcher; configure the invoking Linux account instead of hard-coding deck.
- Add Windows bootstrap with WinGet dependency installation, administrator service setup, Start menu shortcut and tvpn command.
- Add TVPN-named macOS installer; preserve legacy download compatibility.
- Validate Windows PowerShell installer syntax in CI.

Initial network setup requires administrator approval. Windows requires signing out and back in once.
Linux prerequisites: curl, unzip, Python 3, sudo and visudo. Native macOS/Windows VPN connections still need physical-device validation; CI does not establish tunnels.
