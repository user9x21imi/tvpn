#!/bin/bash
set -euo pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
[[ "$(uname -s)" == Darwin ]] || { echo 'Установщик предназначен для macOS.'; exit 1; }
work=$(mktemp -d /private/tmp/riseup-download.XXXXXXXX)
trap 'rm -rf -- "$work"' EXIT
trap 'echo "Не удалось скачать установщик. Нажмите Enter."; read -r _' ERR
echo 'Скачиваю TVPN…'
curl -fL --proto '=https' --proto-redir '=https' --connect-timeout 10 --max-time 180 \
    https://codeload.github.com/user9x21imi/riseup-vpn-panel/zip/refs/heads/main -o "$work/source.zip"
ditto -x -k "$work/source.zip" "$work/unpacked"
source_dir="$work/unpacked/riseup-vpn-panel-main"
[[ -f "$source_dir/start-macos.command" ]] || exit 1
dest="$HOME/Library/Application Support/RiseupVPNPanel"
mkdir -p "$dest"
ditto "$source_dir" "$dest"
chmod 755 "$dest/start-macos.command"
# Retain the process (not exec) so the temporary download is removed on exit.
/bin/bash "$dest/start-macos.command"
