#!/usr/bin/env python3
"""Normalize Riseup's TLS-authenticated public gateway inventory. No shell eval."""
import ipaddress
import json
import re
import sys
import unicodedata
from pathlib import Path

# Coordinates describe configured cities, not measured IP geolocation.
REGIONS = {
    'amsterdam': {'city': 'Амстердам', 'country': 'NL', 'lat': 52.37, 'lon': 4.90},
    'paris': {'city': 'Париж', 'country': 'FR', 'lat': 48.86, 'lon': 2.35},
    'montreal': {'city': 'Монреаль', 'country': 'CA', 'lat': 45.50, 'lon': -73.57},
    'newyork': {'city': 'Нью-Йорк', 'country': 'US', 'lat': 40.71, 'lon': -74.01},
    'miami': {'city': 'Майами', 'country': 'US', 'lat': 25.76, 'lon': -80.19},
    'seattle': {'city': 'Сиэтл', 'country': 'US', 'lat': 47.61, 'lon': -122.33},
}


def key(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    value = re.sub('[^a-z]', '', text)
    return 'newyork' if value == 'newyorkcity' else value


def normalize(document, selected):
    if not isinstance(document, dict):
        raise ValueError('Некорректный формат каталога')
    if selected not in REGIONS:
        raise ValueError('Неизвестный регион')
    locations = document.get('locations', {})
    seen = set()
    result = []
    for gateway in document.get('gateways', []):
        location = str(gateway.get('location', ''))
        info = locations.get(location, {})
        if selected not in (key(location), key(str(info.get('name', '')))):
            continue
        country = str(info.get('country_code', '')).upper()
        if country != REGIONS[selected]['country']:
            continue
        host = str(gateway.get('host', ''))
        if not re.fullmatch(r'vpn[0-9]+-[a-z0-9]+(?:\.riseup\.net)?', host):
            continue
        host = host.removesuffix('.riseup.net')
        try:
            address = str(ipaddress.IPv4Address(gateway['ip_address']))
        except (KeyError, ipaddress.AddressValueError):
            continue
        caps = gateway.get('capabilities', {})
        if caps.get('limited') or gateway.get('bucket'):
            continue
        options = set()
        for transport in caps.get('transport', []):
            if transport.get('type') != 'openvpn':
                continue
            for protocol in transport.get('protocols', []):
                if protocol not in ('udp', 'tcp'):
                    continue
                for port in transport.get('ports', []):
                    if str(port).isdigit() and 1 <= int(port) <= 65535:
                        options.add((protocol, int(port)))
        if not options or host in seen:
            continue
        protocol, port = min(options, key=lambda o: (o != ('udp', 1194), o != ('tcp', 80), o))
        seen.add(host)
        result.append((host, address, protocol, str(port), REGIONS[selected]['city'], country))
    return result


if __name__ == '__main__':
    try:
        data = json.loads(Path(sys.argv[1]).read_text())
        for row in normalize(data, sys.argv[2]):
            print('\t'.join(row))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        print('Не удалось прочитать список шлюзов Riseup: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
