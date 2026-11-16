# Third-party components

Independent client for the public VPNBook OpenVPN service and VPN Gate relay network.
The bundled trust anchor and dummy client certificate originate in the
public VPN Gate OpenVPN catalogue. This client rebuilds its OpenVPN profiles
with strict server certificate identity checks.
https://www.vpngate.net/en/
VPNBook client certificates and CA are taken from its public OpenVPN profiles.
https://www.vpnbook.com/freevpn/openvpn

Dependencies are downloaded unchanged from their distributors:

- CPython 3.12.16, standalone build 20261110:
  Python license.
  https://github.com/python/cpython/tree/v3.12.16
  https://github.com/astral-sh/python-build-standalone

- PySide6 / Shiboken6 / Qt 6.8.3:
  LGPL/GPL license alternatives.
  https://github.com/qtproject/pyside-pyside-setup/tree/v6.8.3
  https://download.qt.io/archive/qt/6.8/6.8.3/submodules/

- OpenVPN 2.6.20:
  GPL-2.0 with OpenSSL exception.
  https://build.openvpn.net/downloads/releases/openvpn-2.6.20.tar.gz

- musl 1.2.5:
  MIT.
  https://musl.libc.org/

- OpenSSL 3.5.9:
  Apache-2.0.
  https://github.com/openssl/openssl/tree/openssl-3.5.9

- LZO 2.10:
  GPL-2.0-or-later.
  https://www.oberhumer.com/opensource/lzo/

- LZ4 1.10.0:
  BSD library license.
  https://github.com/lz4/lz4/tree/v1.10.0

- libcap-ng 0.8.5:
  LGPL library / GPL utility components.
  https://people.redhat.com/sgrubb/libcap-ng/

Exact binary URLs and SHA256 digests are included in
the runtime JSON manifests.

This text source bundle prepares a private local build.
Library sources and complete upstream license notices
remain available from the listed distributors.

The AppImage edition uses the official statically linked Type 2 runtime.
Upstream source and license notices are available in the runtime repository.
https://github.com/AppImage/type2-runtime
See packaging/appimage/runtime.sha256 for its pinned digest.
