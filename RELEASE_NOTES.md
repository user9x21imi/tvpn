TVPN 1.2.0

- Interactive ASCII globe with real country geometry and shaded sphere.
- Smooth camera focus on the chosen VPN city; selected country shown as colored dots.
- Yellow means selected location, green means the VPN exit country passed verification.
- Arrow keys rotate, +/- and the mouse wheel zoom, Space toggles spinning, F returns to the selected location.
- Camera controls do not change the VPN server or interrupt the tunnel.
- Keeps Ctrl+S stop/reconnect, the large STOPED screen and Yes/No verified updates.
- Includes the tvpn terminal shortcut and compact status header.
- Fixes explicit UTF-8 reading on Windows.

Linux/macOS/Windows CI covers rendering, projection, camera controls, country checks,
update verification and cleanup orchestration. CI does not establish real VPN tunnels.
Native VPN availability still depends on the provider's current gateway inventory.
