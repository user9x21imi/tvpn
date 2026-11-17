#!/bin/bash
# One administrator authorization installs all missing native dependencies.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
if (( EUID != 0 )); then exec sudo /bin/bash "$source_dir/platforms/macos/install.sh" "$(id -un)"; fi
username=${1:?Укажите пользователя macOS}
id "$username" >/dev/null
[[ "$username" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || exit 1
[[ "$(uname -s)" == Darwin ]] || { echo 'Установщик предназначен для macOS.' >&2; exit 1; }
work=$(mktemp -d /private/tmp/riseup-install.XXXXXXXX)
mounted=0
cleanup() {
    if (( mounted )); then hdiutil detach "$work/mount" -quiet || true; fi
    rm -rf -- "$work"
}
trap cleanup EXIT
fetch() { curl -fL --proto '=https' --proto-redir '=https' --connect-timeout 10 --max-time 240 --retry 2 "$1" -o "$2"; }
python_runtime=
for candidate in /Library/Frameworks/Python.framework/Versions/{3.15,3.14,3.13,3.12,3.11}/bin/python3; do
    if [[ -x "$candidate" ]] && "$candidate" -I -c 'import ssl,json,venv,curses' >/dev/null 2>&1; then python_runtime=$candidate; break; fi
done
if [[ -z "$python_runtime" ]]; then
    echo 'Устанавливаю подписанный Python с python.org…'
    fetch https://www.python.org/ftp/python/3.13.17/python-3.13.17-macos11.pkg "$work/python.pkg"
    pkgutil --check-signature "$work/python.pkg" | tee "$work/python-signature"
    grep -Fq 'Python Software Foundation (BMM5U3QVKW)' "$work/python-signature"
    spctl --assess --type install "$work/python.pkg"
    installer -pkg "$work/python.pkg" -target /
    python_runtime=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
fi
has_openvpn=0
for candidate in /Applications/Tunnelblick.app/Contents/Resources/openvpn/openvpn-2.6*/openvpn; do
    [[ -x "$candidate" ]] && has_openvpn=1
done
if (( ! has_openvpn )); then
    major=$(sw_vers -productVersion | cut -d . -f 1)
    (( major >= 13 )) || { echo 'Для автоматической установки Tunnelblick нужен macOS 13+. Установите совместимый Tunnelblick с OpenVPN 2.6.' >&2; exit 1; }
    echo 'Устанавливаю Tunnelblick с проверкой SHA256 и подписи…'
    fetch https://tunnelblick.net/iprelease/Tunnelblick_10.0.3_build_6610.dmg "$work/tunnelblick.dmg"
    echo "8bb0f38b44c69a6c0ab4a3959d6091e5d3682af4019e99c4b79233fdc4ea7cdc  $work/tunnelblick.dmg" | shasum -a 256 -c -
    mkdir "$work/mount"
    hdiutil attach "$work/tunnelblick.dmg" -nobrowse -readonly -mountpoint "$work/mount" -quiet
    mounted=1
    codesign --verify --deep --strict "$work/mount/Tunnelblick.app"
    spctl --assess --type execute "$work/mount/Tunnelblick.app"
    ditto "$work/mount/Tunnelblick.app" /Applications/Tunnelblick.app
fi
dest=/Library/PrivilegedHelperTools/riseup-vpn-panel
mkdir -p "$dest"
# An update closes only this app's old backend, letting its traps restore DNS
# before replacing the native executable. Other VPN clients are not touched.
for pid in $(pgrep -f "$dest/backend.sh --text" || true); do
    owner=$(ps -p "$pid" -o uid= | tr -d ' ')
    [[ "$owner" == 0 ]] || continue
    kill -TERM "$pid"
    for ((step=0; step<30; step++)); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo 'Предыдущий туннель ещё восстанавливает сеть; установка остановлена.' >&2
        exit 1
    fi
done
# Dependencies and all executable code used with sudo stay root-owned.
ditto /Applications/Tunnelblick.app "$dest/Tunnelblick.app"
install -m 755 "$source_dir/platforms/macos/backend.sh" "$dest/backend.sh"
install -m 755 "$source_dir/platforms/macos/dns-hook" "$dest/dns-hook"
install -m 644 "$source_dir/assets/riseup-ca.crt" "$dest/riseup-ca.crt"
install -m 644 "$source_dir/riseup_regions.py" "$dest/riseup_regions.py"
install -m 644 "$source_dir/verify_exit.py" "$dest/verify_exit.py"
printf '%s\n' "$python_runtime" > "$dest/python-path"
chown -R root:wheel "$dest"
chmod -R go-w "$dest"
policy="$work/policy"
for region in amsterdam paris montreal newyork miami seattle; do
    printf '%s ALL=(root) NOPASSWD: /Library/PrivilegedHelperTools/riseup-vpn-panel/backend.sh --text --region %s --events\n' "$username" "$region"
done > "$policy"
printf '%s ALL=(root) NOPASSWD: /Library/PrivilegedHelperTools/riseup-vpn-panel/backend.sh --text --check\n' "$username" >> "$policy"
visudo -cf "$policy"
install -o root -g wheel -m 440 "$policy" /etc/sudoers.d/zz-riseup-vpn-panel
visudo -c
sudo -u "$username" sudo -n -k "$dest/backend.sh" --text --check
# Version stamp lets the next ordinary launch detect stale protected helpers.
(cd "$source_dir" && shasum -a 256 platforms/macos/backend.sh platforms/macos/dns-hook platforms/macos/install.sh riseup_regions.py verify_exit.py assets/riseup-ca.crt) | shasum -a 256 | awk '{print $1}' > "$dest/source-version"
echo 'Готово. Запуск панели продолжится автоматически, без повторного пароля.'
