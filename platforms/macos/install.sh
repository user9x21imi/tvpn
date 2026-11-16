#!/bin/bash
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
if (( EUID != 0 )); then exec sudo /bin/bash "$source_dir/platforms/macos/install.sh" "$(id -un)"; fi
username=${1:?Укажите пользователя macOS}
id "$username" >/dev/null
[[ "$username" =~ ^[A-Za-z_][A-Za-z0-9_-]*$ ]] || exit 1
/usr/bin/python3 -I -c 'import ssl,json' || { echo 'Установите Apple Command Line Tools: xcode-select --install' >&2; exit 1; }
[[ -d /Applications/Tunnelblick.app ]] || { echo 'Сначала установите Tunnelblick из https://tunnelblick.net/'; exit 1; }
dest=/Library/PrivilegedHelperTools/riseup-vpn-panel
mkdir -p "$dest"
# Bundle dependencies stay inside a protected root-owned app copy, not Homebrew paths.
ditto /Applications/Tunnelblick.app "$dest/Tunnelblick.app"
install -m 755 "$source_dir/platforms/macos/backend.sh" "$dest/backend.sh"
install -m 755 "$source_dir/platforms/macos/dns-hook" "$dest/dns-hook"
install -m 644 "$source_dir/assets/riseup-ca.crt" "$dest/riseup-ca.crt"
install -m 644 "$source_dir/riseup_regions.py" "$dest/riseup_regions.py"
chown -R root:wheel "$dest"
chmod -R go-w "$dest"
policy=$(mktemp /private/tmp/riseup-policy.XXXXXXXX)
trap 'rm -f "$policy"' EXIT
for region in amsterdam paris montreal newyork miami seattle; do
    printf '%s ALL=(root) NOPASSWD: /Library/PrivilegedHelperTools/riseup-vpn-panel/backend.sh --text --region %s --events\n' "$username" "$region"
done > "$policy"
printf '%s ALL=(root) NOPASSWD: /Library/PrivilegedHelperTools/riseup-vpn-panel/backend.sh --text --check\n' "$username" >> "$policy"
visudo -cf "$policy"
install -o root -g wheel -m 440 "$policy" /etc/sudoers.d/zz-riseup-vpn-panel
visudo -c
sudo -u "$username" sudo -n -k "$dest/backend.sh" --text --check
echo 'Установлено. Откройте start-macos.command от обычного пользователя.'
