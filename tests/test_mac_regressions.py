"""Portable regressions for the reported Mac font/region/setup failures."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from riseup_regions import availability,normalize
from verify_exit import verify
spec=importlib.util.spec_from_file_location('mac_panel',ROOT/'riseup-panel.py')
P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)


class MacRegressionTests(unittest.TestCase):
    def test_real_provider_catalog_has_no_new_york_or_seattle_gateways(self):
        data=json.loads((ROOT/'tests/fixtures/riseup-catalog-2026-11-17.json').read_text(encoding='utf-8'))
        self.assertEqual(availability(data),dict(amsterdam=3,paris=9,montreal=2,newyork=0,miami=2,seattle=0))
        self.assertEqual(normalize(data,'newyork'),[])
        self.assertEqual(normalize(data,'seattle'),[])

    def test_gateway_identity_cannot_cross_city_boundaries(self):
        data={'locations':{'Amsterdam':{'name':'Amsterdam','country_code':'NL'}},'gateways':[
            {'host':'vpn02-par.riseup.net','ip_address':'192.0.2.1','location':'Amsterdam',
             'capabilities':{'transport':[{'type':'openvpn','ports':[1194],'protocols':['udp']}]}}]}
        self.assertEqual(normalize(data,'amsterdam'),[])

    def test_aliases_and_advertised_tcp_fallback(self):
        data={'locations':{'nyc':{'name':'New York City','country_code':'US'}},'gateways':[
            {'host':'vpn24-nyc.riseup.net','ip_address':'192.0.2.1','location':'nyc',
             'capabilities':{'transport':[{'type':'openvpn','ports':['1194','80'],'protocols':['udp','tcp']}]}}]}
        rows=normalize(data,'newyork')
        self.assertEqual(rows[0][2:4],('udp','1194'))
        self.assertEqual(rows[1][2:4],('tcp','80'))
        self.assertTrue(all(r[4:] == ('Нью-Йорк','US') for r in rows))

    def test_independent_geo_city_is_not_the_configured_city(self):
        document={'success':True,'ip':'192.0.2.1','country_code':'NL','city':'Haarlem'}
        self.assertEqual(verify(document,'192.0.2.1','NL'),('Haarlem','NL'))
        with self.assertRaisesRegex(ValueError,'Страна выхода NL, выбрана FR'):
            verify(document,'192.0.2.1','FR')
        with self.assertRaisesRegex(ValueError,'другой внешний IP'):
            verify(document,'192.0.2.2','NL')

    def test_geo_failure_and_missing_country_do_not_confirm_connection(self):
        for document in [{'success':False,'message':'rate limit'},{'success':True,'ip':'192.0.2.1'}]:
            with self.assertRaises(ValueError):verify(document,'192.0.2.1','NL')

    def test_macos_defaults_to_plain_ascii_art(self):
        with patch.object(P.sys,'platform','darwin'),patch.dict(os.environ,{},clear=True):
            m=P.Model()
            self.assertEqual(m.art,'ascii')
        converted=P.art_text('⣿⡇● ▁▂▃▄▅▆▇█ ↓ ↑ — …')
        self.assertTrue(converted.isascii())

    def test_catalog_events_disable_missing_regions_and_keep_geo_separate(self):
        m=P.Model('amsterdam')
        m.line('@RISEUP\tavailability\tnewyork\t0\tRiseup\n')
        m.line('@RISEUP\tgeo\tHaarlem\tNL\tipwho.is\n')
        self.assertEqual(m.counts['newyork'],0)
        self.assertEqual(m.city,'Амстердам')
        self.assertEqual(m.geo_city,'Haarlem')

    def test_single_entrypoint_runs_setup_before_launch_and_has_no_xcode_dependency(self):
        start=(ROOT/'start-macos.command').read_text(encoding='utf-8')
        install=(ROOT/'platforms/macos/install.sh').read_text(encoding='utf-8')
        self.assertIn('with administrator privileges',start)
        self.assertIn('source-version',start)
        self.assertIn('import curses,psutil',start)
        self.assertIn('exec .venv/bin/python3 launch.py',start)
        self.assertIn('pkgutil --check-signature',install)
        self.assertIn('spctl --assess',install)
        self.assertNotIn('xcode-select',install)
        self.assertIn('verify_exit.py',install)


if __name__=='__main__':unittest.main(verbosity=2)
