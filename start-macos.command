#!/bin/bash
# Double-click: install/update everything needed, then start the normal-user UI.
set -euo pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 PYTHONIOENCODING=utf-8
export RISEUP_ART_STYLE=${RISEUP_ART_STYLE:-ascii}
cd -- "$(dirname -- "$0")"
source_dir=$PWD
[[ "$(uname -s)" == Darwin ]] || { echo 'Этот файл предназначен для macOS.'; exit 1; }
app_dir="$HOME/Library/Application Support/RiseupVPNPanel"
if [[ "$source_dir" != "$app_dir" ]]; then
    mkdir -p "$app_dir"
    ditto "$source_dir" "$app_dir"
    exec /bin/bash "$app_dir/start-macos.command" "$@"
fi
# Keep errors visible when launched by double-click rather than an existing terminal.
failed() { echo; echo 'Не удалось завершить установку. Скопируйте сообщение выше в журнал поддержки.'; read -r -p 'Enter — закрыть…' _; }
trap failed ERR
dest=/Library/PrivilegedHelperTools/riseup-vpn-panel
wanted=$(shasum -a 256 platforms/macos/backend.sh platforms/macos/dns-hook platforms/macos/install.sh riseup_regions.py verify_exit.py assets/riseup-ca.crt | shasum -a 256 | awk '{print $1}')
installed=$(cat "$dest/source-version" 2>/dev/null || true)
if [[ "$wanted" != "$installed" ]] || ! sudo -n "$dest/backend.sh" --text --check >/dev/null 2>&1; then
    echo 'Первая установка / обновление. macOS запросит права администратора один раз.'
    echo 'Скачивание и проверка зависимостей могут занять несколько минут. Дождитесь завершения.'
    osascript - "$source_dir/platforms/macos/install.sh" "$(id -un)" <<'APPLESCRIPT'
on run argv
    set scriptPath to item 1 of argv
    set accountName to item 2 of argv
    do shell script "/bin/bash " & quoted form of scriptPath & " " & quoted form of accountName with administrator privileges
end run
APPLESCRIPT
fi
python_runtime=$(cat "$dest/python-path")
if [[ ! -x .venv/bin/python3 ]] || ! .venv/bin/python3 -c 'import curses,psutil' >/dev/null 2>&1; then
    "$python_runtime" -m venv .venv
    .venv/bin/python3 -m pip install --disable-pip-version-check -r requirements-macos.txt
fi
# A launcher in ~/Applications is created automatically; no commands need typing.
mkdir -p "$HOME/Applications"
printf '#!/bin/bash\nexec /bin/bash %q "$@"\n' "$source_dir/start-macos.command" > "$HOME/Applications/TVPN.command"
chmod 755 "$HOME/Applications/TVPN.command"
echo 'Готово. [R] регион, [Ctrl+S] остановить/подключить, [U] ASCII/Unicode.'
exec .venv/bin/python3 launch.py "$@"
