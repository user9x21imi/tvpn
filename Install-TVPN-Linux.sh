#!/bin/bash
set -euo pipefail
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'TVPN requires Linux x86_64.'; exit 1; }
for tool in curl unzip python3 sudo; do command -v "$tool" >/dev/null || { echo "Install required package: $tool"; exit 1; }; done
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
curl -fL --proto '=https' --proto-redir '=https' --connect-timeout 15 --max-time 240 https://codeload.github.com/user9x21imi/tvpn/zip/refs/heads/main -o "$work/source.zip"
unzip -q "$work/source.zip" -d "$work"
python3 "$work/tvpn-main/install.py" "$@"
