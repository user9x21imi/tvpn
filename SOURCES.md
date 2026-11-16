```text
+-- Sources --+
```

```text
+-----------+
|  [ Map ]  |
+-----------+
```

Made with Natural Earth. World country polygons, scale 1:110m, obtained 2026-11-15:
https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson

`world-land.json` preserves only ADM0_A3, NAME and geometry from this dataset.
The renderer uses country codes only for highlighting, with Antarctica omitted
from the viewport. The data remains independent of the VPN gateway inventory.

Natural Earth data is public domain:
https://www.naturalearthdata.com/about/terms-of-use/

```text
+-----------+
|  [ VPN ]  |
+-----------+
```

Riseup service and account-free client:
https://riseup.net/en/vpn

Public gateway inventory endpoint used by the connection backend:
https://api.black.riseup.net/3/config/eip-service.json

The endpoint could not be fetched from the restricted development environment.
No new IP addresses are hard-coded from third-party lists. Newly selected regions
must yield public OpenVPN gateways in the TLS-authenticated provider inventory
at connection time. An empty or unavailable list fails explicitly. Only the
original two Amsterdam gateway addresses from the user's existing script are
retained for offline inventory fallback. Country validation uses HTTPS traces
through riseupvpn0 and must match the configured gateway country.

## macOS setup and exit validation (2026-11-17)

- Python 3.13.17 universal installer: https://www.python.org/ftp/python/3.13.17/
- Python macOS installer signing identity (PSF, BMM5U3QVKW): https://www.python.org/downloads/
- Tunnelblick stable 10.0.3 / build 6610, published SHA256:
  https://tunnelblick.net/downloads.html
- Download: https://tunnelblick.net/iprelease/Tunnelblick_10.0.3_build_6610.dmg
- Independent HTTPS geolocation API and rate limits: https://ipwhois.io/documentation

A TLS-verified live Riseup inventory fetched on 2026-11-17 contained 16
public gateways: Amsterdam 3, Paris 9, Montreal 2, Miami 2. Location metadata
still named New York and Seattle, but neither had gateways. The public
inventory is preserved as a regression fixture under tests/fixtures.
GeoIP cities are database estimates, not proof of a server's physical city.
