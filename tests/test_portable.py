"""No network, admin rights, shell tools or Unix-only modules required."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from riseup_regions import REGIONS
from world_map import render, land
from stoped_title import render as stoped
import launch

spec=importlib.util.spec_from_file_location('panel_portable',ROOT/'riseup-panel.py')
panel=importlib.util.module_from_spec(spec);spec.loader.exec_module(panel)
spec=importlib.util.spec_from_file_location('windows_backend',ROOT/'platforms/windows/backend.py')
windows=importlib.util.module_from_spec(spec);spec.loader.exec_module(windows)


class PortableTests(unittest.TestCase):
    def test_launch_chooses_native_backend(self):
        self.assertEqual(launch.backend('win32').suffix,'.py')
        self.assertEqual(launch.backend('darwin').name,'launcher.sh')
        self.assertEqual(launch.backend('linux').name,'Riseup-Amsterdam-SteamDeck.sh')

    def test_partial_cell_highlights_only_selected_country_dots(self):
        def polygon(code,west,east):
            return {'id':code,'type':'Polygon','coordinates':[[[west,-60],[east,-60],[east,84],[west,84],[west,-60]]]}
        render.cache_clear()
        try:
            with patch('world_map.land',return_value=[polygon('NLD',-180,0),polygon('FRA',0,180)]):
                char,highlight=render(1,1,'NL')[0][0]
                self.assertTrue(highlight)
                self.assertEqual(ord(char)-0x2800,0x47)  # left four dots only
        finally:
            render.cache_clear()

    def test_stoped_is_large_tightly_spaced_and_contains_dots_only(self):
        banner=stoped(124,15)
        self.assertGreater(len(banner),8)
        self.assertGreater(len(banner[0]),110)
        self.assertTrue(set(''.join(banner)) <= {'●',' '})
        occupied=[any(row[x]!=' ' for row in banner) for x in range(len(banner[0]))]
        gaps=[];current=0
        for value in occupied:
            if not value:current+=1
            elif current:gaps.append(current);current=0
        self.assertLessEqual(max(gaps,default=0),1)

    def test_macos_interface_event_and_country_confirmation(self):
        m=panel.Model('paris')
        m.line('@RISEUP\tinterface\tutun12\n')
        m.line('@RISEUP\tconnected\t192.0.2.1\tFR\n')
        self.assertEqual(m.interface,'utun12')
        self.assertEqual(m.state,'connected')
        self.assertIn('utun12',m.detail)

    def test_windows_profile_uses_service_managed_dns_and_certificate_checks(self):
        profile=windows.make_profile('vpn04-ams','192.0.2.1','udp','1194',Path('C:/Users/test/OpenVPN/config'))
        self.assertIn('windows-driver wintun',profile)
        self.assertIn('block-outside-dns',profile)
        self.assertIn('verify-x509-name vpn04-ams name',profile)
        self.assertIn('remote-cert-tls server',profile)
        self.assertNotIn('script-security',profile)
        self.assertNotIn('PRIVATE KEY',profile)

    def test_interface_counters_use_actual_elapsed_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'rx_bytes').write_text('10');(root/'tx_bytes').write_text('20')
            m=panel.Model();m.sample(1,root)
            (root/'rx_bytes').write_text(str(10+2**20));(root/'tx_bytes').write_text(str(20+2**19))
            m.sample(3,root)
            self.assertEqual((m.down,m.up),(.5,.25))

    def test_macos_native_backend_does_not_extract_linux_runtime(self):
        script=(ROOT/'platforms/macos/backend.sh').read_text()
        self.assertNotIn('ld-musl',script)
        self.assertNotIn('__RISEUP_RUNTIME_BELOW__',script)
        self.assertIn('event interface "$tunnel_iface"',script)
        self.assertIn('if!$tunnel_iface',script)


if __name__=='__main__':unittest.main(verbosity=2)
