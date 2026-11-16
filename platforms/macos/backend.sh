#!/bin/bash
# RiseupVPN: selectable free public gateways. Launch with bash on SteamOS/Linux x86_64.
# Ctrl+C disconnects and restores DNS. Bundled OpenVPN: see --licenses.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
script="$script_dir/backend.sh"
events=0
requested_region=amsterdam
while (( $# )); do
    case "$1" in
        --text) ;;
        --check) (( EUID == 0 )) || exit 1; echo 'RiseupVPN: беспарольный backend готов'; exit 0 ;;
        --events) events=1 ;;
        --region) shift; requested_region=${1:?Укажите регион после --region} ;;
        --licenses) break ;;
        *) echo "Неизвестный аргумент: $1" >&2; exit 2 ;;
    esac
    shift
done
case "$requested_region" in
    amsterdam|paris|montreal|newyork|miami|seattle) ;;
    *) echo 'Неизвестный регион Riseup.' >&2; exit 2 ;;
esac
event() {
    if (( events )); then printf '@RISEUP\t%s\t%s\t%s\t%s\n' "$1" "${2:-}" "${3:-}" "${4:-}"; fi
}
extract_runtime() {
    cp "$script_dir/riseup-ca.crt" "$1/riseup-ca.crt"
    cp "$script_dir/dns-hook" "$1/dns-hook"
    chmod 700 "$1/dns-hook"
}
if [[ "$(uname -s)" != Darwin ]]; then
    echo 'Этот backend работает только в macOS.' >&2
    exit 1
fi
if (( EUID != 0 )); then
    echo 'Backend macOS должен запускаться через установленное правило sudo.' >&2
    exit 1
fi
for program in curl /usr/bin/python3 /usr/sbin/networksetup; do
    command -v "$program" >/dev/null || { echo "Не найден $program" >&2; exit 1; }
done
lockdir=/var/run/riseup-vpn-panel.lock
mkdir "$lockdir" 2>/dev/null || { echo 'Другой туннель Riseup уже запущен (или остался lock после сбоя).' >&2; exit 1; }
trap 'rmdir "$lockdir" 2>/dev/null || true' EXIT
event state connecting "Подготовка туннеля"
directory=$(mktemp -d /var/run/riseup-amsterdam.XXXXXXXX)
vpn_pid=
stop_vpn() {
    if [[ -n "$vpn_pid" ]]; then
        kill -TERM "$vpn_pid" 2>/dev/null || true
        wait "$vpn_pid" 2>/dev/null || true
        vpn_pid=
    fi
}
cleanup() {
    local result=$?
    if (( result != 0 && result != 130 && result != 143 )); then event state error "Ошибка подключения; откройте журнал [L]"; fi
    stop_vpn
    if [[ -x "$directory/dns-hook" ]] && ! script_type=down "$directory/dns-hook"; then
        echo "Не удалось восстановить DNS. Резервная копия: $directory/dns-original" >&2
        event state error "Не удалось восстановить DNS; см. журнал"
        return 1
    fi
    event cleanup ok
    rm -rf -- "$directory"
    rmdir "$lockdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

# Keep the original Amsterdam endpoints as an offline fallback.
extract_runtime "$directory"
cd "$directory"
case "$requested_region" in
    amsterdam) city=Амстердам; expected_country=NL ;;
    paris) city=Париж; expected_country=FR ;;
    montreal) city=Монреаль; expected_country=CA ;;
    newyork) city=Нью-Йорк; expected_country=US ;;
    miami) city=Майами; expected_country=US ;;
    seattle) city=Сиэтл; expected_country=US ;;
esac
event location "$requested_region" "$city" "$expected_country"
event state catalog 'Получение актуального списка бесплатных шлюзов Riseup'
: > gateways.tsv
catalog_ok=0
for api_port in 4430 443; do
    ca_args=()
    [[ "$api_port" == 4430 ]] && ca_args=(--cacert "$directory/riseup-ca.crt")
    for api_address in 198.252.153.67 198.252.153.106; do
        event detail catalog "Список шлюзов: $api_address:$api_port, до 12 с"
        if curl -q4fsS --noproxy '*' --resolve "api.black.riseup.net:$api_port:$api_address" \
            --connect-timeout 6 --max-time 12 "${ca_args[@]}" \
            "https://api.black.riseup.net:$api_port/3/config/eip-service.json" -o gateways.json &&
            /usr/bin/python3 -I "$script_dir/riseup_regions.py" gateways.json "$requested_region" > gateways.tsv &&
            [[ -s gateways.tsv ]]; then
            catalog_ok=1
            break 2
        fi
    done
done
if (( ! catalog_ok )); then
    if [[ "$requested_region" == amsterdam ]]; then
        echo 'Список недоступен. Использую сохранённые шлюзы Амстердама.'
        printf 'vpn04-ams\t51.15.9.205\tudp\t1194\tАмстердам\tNL\n' > gateways.tsv
        printf 'vpn13-ams\t51.158.144.31\tudp\t1194\tАмстердам\tNL\n' >> gateways.tsv
    else
        echo "Riseup не вернул доступных публичных шлюзов для $city. Попробуйте другой регион или повторите позже." >&2
        exit 1
    fi
fi
event state certificate 'Получение сертификата'
echo 'Получаю временный сертификат RiseupVPN. Аккаунт не нужен.'
riseup_cert() {
  local port address
  local -a ca
  for port in 4430 443; do
    ca=()
    if [[ "$port" == 4430 ]]; then ca=(--cacert "$directory/riseup-ca.crt"); fi
    for address in 198.252.153.67 198.252.153.106; do
      event detail certificate "Сертификат: $address:$port, до 12 с на попытку"
      if curl -q4fsS --noproxy "*" --resolve "api.black.riseup.net:$port:$address" --connect-timeout 6 --max-time 12 "${ca[@]}" "https://api.black.riseup.net:$port/3/cert" -o client.pem; then return 0; fi
    done
  done
  echo "Steam Deck не смог связаться с сервером сертификатов Riseup на обоих портах." >&2
  return 1
}
riseup_cert
grep -q '^-----BEGIN CERTIFICATE-----' client.pem
grep -Eq '^-----BEGIN (RSA )?PRIVATE KEY-----' client.pem

openvpn_path=
for candidate in "$script_dir"/Tunnelblick.app/Contents/Resources/openvpn/openvpn-2.6*/openvpn; do
    if [[ -x "$candidate" ]]; then openvpn_path=$candidate; fi
done
[[ -n "$openvpn_path" ]] || { echo 'В защищённой копии Tunnelblick не найден OpenVPN 2.6.' >&2; exit 1; }
openvpn=("$openvpn_path")
tunnel_iface=

connect() {
    local host=$1 address=$2 protocol=$3 port=$4 city=$5
    event gateway "$host" "$city" "$address"
    event state connecting "Подключение…"
    cat > client.ovpn <<PROFILE
client
dev tun
dev-type tun
proto $protocol
remote $address $port
nobind
connect-retry-max 1
connect-timeout 8
hand-window 15
auth SHA512
data-ciphers AES-256-GCM
tls-cipher TLS-ECDHE-ECDSA-WITH-AES-256-GCM-SHA384
tls-version-min 1.2
remote-cert-tls server
verify-x509-name $host name
ca riseup-ca.crt
cert client.pem
key client.pem
pull-filter ignore redirect-gateway
pull-filter ignore ifconfig-ipv6
pull-filter ignore block-outside-dns
redirect-gateway def1 ipv6
ifconfig-ipv6 fd42:6760:5255::2/64 fd42:6760:5255::1
block-ipv6
script-security 2
up "$directory/dns-hook"
down "$directory/dns-hook"
verb 3
PROFILE

    : > openvpn.log
    "${openvpn[@]}" --config client.ovpn --log "$directory/openvpn.log" &
    vpn_pid=$!
    local step address_check trace
    for ((step=0; step<27; step++)); do
        kill -0 "$vpn_pid" 2>/dev/null || return 1
        if grep -q 'Initialization Sequence Completed' openvpn.log; then
            tunnel_iface=$(grep -Eo 'utun[0-9]+' openvpn.log | tail -n 1)
            [[ "$tunnel_iface" =~ ^utun[0-9]+$ ]] || return 1
            event interface "$tunnel_iface"
            event state verifying "Проверка выхода через $tunnel_iface"
            for address_check in 1.1.1.1 1.0.0.1; do
                if trace=$(curl -qfsS -4 --noproxy '*' --interface "if!$tunnel_iface" \
                    --connect-timeout 5 --max-time 8 "https://$address_check/cdn-cgi/trace") &&
                    grep -qx "loc=$expected_country" <<< "$trace"; then
                    event connected "$(sed -n 's/^ip=//p' <<< "$trace")" "$expected_country"
                    printf 'VPN подключён. Выход %s, внешний IP: %s\n' "$expected_country" "$(sed -n 's/^ip=//p' <<< "$trace")"
                    return 0
                fi
            done
            return 1
        fi
        sleep 1
    done
    return 1
}

connected=0
attempt=0
while IFS=$'\t' read -r host address protocol port gateway_city gateway_country; do
    if (( attempt > 0 )); then event state fallback "Пробую резервный шлюз: $host"; fi
    attempt=$((attempt + 1))
    echo "Подключаюсь: $gateway_city / $host ($attempt)…"
    if connect "$host" "$address" "$protocol" "$port" "$gateway_city"; then
        connected=1
        break
    fi
    tail -n 12 openvpn.log >&2
    stop_vpn
    script_type=down "$directory/dns-hook"
done < gateways.tsv
if (( ! connected )); then
    echo "Ни один шлюз региона $city не прошёл проверку HTTPS и страны $expected_country." >&2
    exit 1
fi
echo 'VPN работает. Панель управляет остановкой через Ctrl+S.'
if ! wait "$vpn_pid"; then
    echo 'Процесс VPN завершился с ошибкой.' >&2
    tail -n 20 openvpn.log >&2
    exit 1
fi
exit 0
