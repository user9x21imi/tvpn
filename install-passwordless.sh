#!/bin/bash
# One-time administrator installation. Afterwards only the VPN backend is NOPASSWD.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
if (( EUID != 0 )); then
    echo 'Однократная установка режима VPN без пароля. Нужен пароль администратора SteamOS.'
    exec sudo -- /bin/bash "$source_dir/install-passwordless.sh"
fi
command -v visudo >/dev/null || { echo 'Не найден visudo.' >&2; exit 1; }
id deck >/dev/null
backend_dir=/var/lib/riseup-vpn
policy=/etc/sudoers.d/zz-riseup-vpn
[[ ! -L "$backend_dir" && ! -L "$policy" ]] || { echo 'Неожиданная символическая ссылка; установка остановлена.' >&2; exit 1; }
[[ -f "$source_dir/Riseup-Amsterdam-SteamDeck.sh" && -f "$source_dir/riseup_regions.py" ]]
bash -n "$source_dir/Riseup-Amsterdam-SteamDeck.sh"
python3 -I -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' "$source_dir/riseup_regions.py"
# Root-owned parent and backend: deck cannot edit code allowed by sudoers.
install -d -o root -g root -m 755 "$backend_dir"
work=$(mktemp -d "$backend_dir/.install.XXXXXXXX")
trap 'rm -rf -- "$work"' EXIT
install -o root -g root -m 755 "$source_dir/Riseup-Amsterdam-SteamDeck.sh" "$work/backend.sh"
install -o root -g root -m 644 "$source_dir/riseup_regions.py" "$work/riseup_regions.py"
{
    echo '# RiseupVPN: exact commands only; never a user-writable script or arbitrary shell.'
    echo 'deck ALL=(root) NOPASSWD: /var/lib/riseup-vpn/backend.sh --text --check'
    for region in amsterdam paris montreal newyork miami seattle; do
        printf 'deck ALL=(root) NOPASSWD: /var/lib/riseup-vpn/backend.sh --text --region %s\n' "$region"
        printf 'deck ALL=(root) NOPASSWD: /var/lib/riseup-vpn/backend.sh --text --region %s --events\n' "$region"
    done
} > "$work/policy"
chmod 440 "$work/policy"
visudo -cf "$work/policy"
# Keep a copy so an administrator can roll back a previous installation.
for name in backend.sh riseup_regions.py; do
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
if ! runuser -u deck -- sudo -n -k -- "$backend_dir/backend.sh" --text --check; then
    echo 'Правило записано, но беспарольный запуск не прошёл проверку. Не закрывайте административный терминал.' >&2
    exit 1
fi
echo 'Готово. vpn и VPN запускаются без пароля. Переключение регионов: R.'
echo 'После обновления VPN-файлов повторите эту установку, чтобы обновить защищённый backend.'
