#!/usr/bin/env python3
"""Validate independent country evidence without treating GeoIP city as gateway city."""
import ipaddress
import json
from pathlib import Path
import re
import sys


def verify(document, address, expected):
    if not isinstance(document,dict):
        raise ValueError('GeoIP вернул некорректный ответ')
    if document.get('success') is not True:
        raise ValueError('GeoIP временно недоступен: '+str(document.get('message','нет ответа'))[:100])
    if str(ipaddress.IPv4Address(document.get('ip',''))) != str(ipaddress.IPv4Address(address)):
        raise ValueError('GeoIP вернул другой внешний IP')
    country=document.get('country_code','')
    if country != expected:
        raise ValueError(f'Страна выхода {country or "неизвестна"}, выбрана {expected}; шлюз отклонён')
    city=''.join(c for c in str(document.get('city','—')) if c.isprintable() and c not in '\t\r\n')[:70]
    return city,country


if __name__=='__main__':
    try:
        city,country=verify(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')),sys.argv[2],sys.argv[3])
        print(f'@RISEUP\tgeo\t{city}\t{country}\tipwho.is')
    except (OSError,ValueError,TypeError,KeyError,AttributeError) as error:
        print(str(error),file=sys.stderr)
        raise SystemExit(1)
