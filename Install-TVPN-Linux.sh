#!/bin/bash
set -euo pipefail
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'TVPN requires Linux x86_64.'; exit 1; }
for tool in curl unzip python3 sudo; do command -v "$tool" >/dev/null || { echo "Install required package: $tool"; exit 1; }; done
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
curl -fL --proto '=https' --proto-redir '=https' --connect-timeout 15 --max-time 240 https://codeload.github.com/user9x21imi/tvpn/zip/refs/heads/main -o "$work/source.zip"
unzip -q "$work/source.zip" -d "$work"
dest="$HOME/.local/share/riseup-vpn"
mkdir -p "$dest" "$HOME/.local/bin" "$HOME/.local/share/applications"
cp -R "$work/tvpn-main/." "$dest/"
install -m 755 "$dest/bin/tvpn" "$HOME/.local/bin/tvpn"
bash "$dest/install-passwordless.sh"
python3 - "$dest" <<'PY'
from pathlib import Path
import sys
root=Path(sys.argv[1]);home=Path.home()
launcher=home/'.local/share/applications/tvpn.desktop'
launcher.write_text('[Desktop Entry]\nType=Application\nName=TVPN\nComment=Terminal VPN with interactive ASCII globe\nExec=bash "'+str(root/'Riseup-Amsterdam-SteamDeck.sh')+'"\nTerminal=true\nIcon=network-vpn\nCategories=Network;\n',encoding='utf-8')
for rc in (home/'.bashrc',home/'.zshrc'):
 text=rc.read_text(encoding='utf-8') if rc.exists() else ''
 if '# TVPN shortcut' not in text:
  with rc.open('a',encoding='utf-8') as f:f.write('\n# TVPN shortcut\nalias tvpn=\'bash "$HOME/.local/bin/tvpn"\'\n')

PY
exec bash "$HOME/.local/bin/tvpn"
