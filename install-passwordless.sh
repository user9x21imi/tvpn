#!/bin/bash
# One-time administrator installation. Afterwards only the VPN backend is NOPASSWD.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if (( EUID != 0 )); then
    echo 'Однократная установка режима VPN без пароля. Нужен пароль администратора Linux.'
    exec sudo -- /bin/bash "$source_dir/install-passwordless.sh"
fi
command -v visudo >/dev/null || { echo 'Не найден visudo.' >&2; exit 1; }
target_user=${SUDO_USER:-$(id -un "${PKEXEC_UID:-1000}")}
[[ $target_user =~ ^[a-zA-Z_][a-zA-Z0-9_-]*\$?$ ]] || { echo 'Invalid account name'; exit 1; }
id "$target_user" >/dev/null
[[ ! -L /run/tvpn-install.lock ]] || exit 1
exec 7>>/run/tvpn-install.lock
flock -n 7 || { echo 'Another system installation is active' >&2; exit 1; }
# Shared lock excludes the OpenVPN backend's exclusive lock, including certificate fetch.
[[ ! -L /run/riseup-amsterdam.lock ]] || exit 1
exec 8>>/run/riseup-amsterdam.lock
flock -sn 8 || { echo 'VPN is active; stop it before system installation.' >&2; exit 1; }
chown root:root /run/riseup-amsterdam.lock
chmod 644 /run/riseup-amsterdam.lock
backend_dir=/var/lib/riseup-vpn
policy=/etc/sudoers.d/zz-riseup-vpn
[[ ! -L "$backend_dir" && ! -L "$policy" ]] || { echo 'Неожиданная символическая ссылка; установка остановлена.' >&2; exit 1; }
[[ -f "$source_dir/Riseup-Amsterdam-SteamDeck.sh" && -f "$source_dir/riseup_regions.py" ]]
bash -n "$source_dir/Riseup-Amsterdam-SteamDeck.sh"
python3 -I -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' "$source_dir/riseup_regions.py"
# Root-owned parent and backend: deck cannot edit code allowed by sudoers.
install -d -o root -g root -m 755 "$backend_dir"
work=$(mktemp -d "$backend_dir/.install.XXXXXXXX")
committed=0
mkdir "$work/rollback"
if [[ -f /etc/sudoers.d/70-riseup-vpn ]]; then cp -p /etc/sudoers.d/70-riseup-vpn "$work/rollback/legacy"; fi
for path in "$backend_dir/backend.sh" "$backend_dir/riseup_regions.py" "$backend_dir/verify_exit.py" "$policy" /etc/sudoers.d/70-riseup-vpn; do
    if [[ -f "$path" ]]; then cp -p -- "$path" "$work/rollback/$(basename "$path")"; fi
done
rollback() {
    result=$?
    if (( ! committed )); then
        for path in "$backend_dir/backend.sh" "$backend_dir/riseup_regions.py" "$backend_dir/verify_exit.py" "$policy" /etc/sudoers.d/70-riseup-vpn; do
            saved="$work/rollback/$(basename "$path")"
            if [[ -f "$saved" ]]; then cp -p -- "$saved" "$path"; else rm -f -- "$path"; fi
        done
    fi
    if (( committed == 0 )) && [[ -f "$work/rollback/legacy" ]]; then cp -p "$work/rollback/legacy" /etc/sudoers.d/70-riseup-vpn; fi
    rm -rf -- "$work"
    exit "$result"
}
trap rollback EXIT
install -o root -g root -m 755 "$source_dir/Riseup-Amsterdam-SteamDeck.sh" "$work/backend.sh"
install -o root -g root -m 644 "$source_dir/riseup_regions.py" "$work/riseup_regions.py"
install -o root -g root -m 644 "$source_dir/verify_exit.py" "$work/verify_exit.py"
{
    echo '# RiseupVPN: exact commands only; never a user-writable script or arbitrary shell.'
    printf '%s ALL=(root) NOPASSWD: /var/lib/riseup-vpn/backend.sh --text --check\n' "$target_user"
    printf '%s ALL=(root) NOPASSWD: /var/lib/riseup-vpn/backend.sh --text --guard\n' "$target_user"
    for region in amsterdam paris montreal newyork miami seattle; do
        printf '%s ALL=(root) NOPASSWD: /var/lib/riseup-vpn/backend.sh --text --region %s\n' "$target_user" "$region"
        printf '%s ALL=(root) NOPASSWD: /var/lib/riseup-vpn/backend.sh --text --region %s --events\n' "$target_user" "$region"
    done
} > "$work/policy"
chmod 440 "$work/policy"
visudo -cf "$work/policy"
# Keep a copy so an administrator can roll back a previous installation.
for name in backend.sh riseup_regions.py verify_exit.py; do
    if [[ -f "$backend_dir/$name" ]]; then cp -p -- "$backend_dir/$name" "$backend_dir/$name.previous"; fi
    mv -fT -- "$work/$name" "$backend_dir/$name"
done
install -d -o root -g root -m 755 /etc/sudoers.d
if [[ -f "$policy" ]]; then cp -p -- "$policy" "$backend_dir/sudoers.previous"; fi
install -o root -g root -m 440 "$work/policy" "$policy"
# The previous 70-* file sorted before SteamOS's wheel rule and could be overridden.
if [[ -f /etc/sudoers.d/70-riseup-vpn ]]; then
    mv -fT /etc/sudoers.d/70-riseup-vpn "$backend_dir/sudoers.legacy"
fi
visudo -c
# Verify from deck with the timestamp ignored; a syntax check alone is insufficient.
if ! runuser -u "$target_user" -- sudo -n -k -- "$backend_dir/backend.sh" --text --check; then
    echo 'Правило записано, но беспарольный запуск не прошёл проверку. Не закрывайте административный терминал.' >&2
    exit 1
fi
committed=1
echo 'Готово. vpn и VPN запускаются без пароля. Переключение регионов: R.'
echo 'После обновления VPN-файлов повторите эту установку, чтобы обновить защищённый backend.'
