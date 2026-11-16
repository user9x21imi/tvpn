import copy
import fcntl
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import tempfile
import termios
import time
import unittest
from unittest.mock import patch
from test_panel import P, ROOT
from riseup_regions import normalize
from world_map import render, position


class Screen:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.erase()

    def erase(self):
        self.cells = [[(' ', 0) for _ in range(self.width)] for _ in range(self.height)]

    def getmaxyx(self):
        return self.height, self.width

    def addnstr(self, y, x, text, n, attr):
        for i, c in enumerate(text[:n]):
            self.cells[y][x+i] = (c, attr)

    def refresh(self):
        pass

    def text(self):
        return '\n'.join(''.join(c for c, _ in row) for row in self.cells)


class RegionTests(unittest.TestCase):
    def fixture(self):
        return {'locations': {'Montréal': {'name': 'Montréal', 'country_code': 'CA'}},
                'gateways': [{'host': 'vpn17-mtl.riseup.net', 'ip_address': '192.0.2.4',
                              'location': 'Montréal', 'capabilities': {'transport': [
                                  {'type': 'obfs4', 'protocols': ['tcp'], 'ports': ['443']},
                                  {'type': 'openvpn', 'protocols': ['udp', 'tcp'], 'ports': ['80', '1194']} ]}}]}

    def test_catalog_selects_supported_transport_and_city(self):
        row, = normalize(self.fixture(), 'montreal')
        self.assertEqual(row, ('vpn17-mtl', '192.0.2.4', 'udp', '1194', 'Монреаль', 'CA'))
        self.assertEqual(normalize(self.fixture(), 'paris'), [])

    def test_catalog_rejects_private_invalid_or_wrong_country_gateways(self):
        for update in [{'host': 'bad\nscript-security 3'}, {'ip_address': 'not-an-ip'},
                       {'bucket': 'invitation-only'}, {'capabilities': {'limited': True}}]:
            data = self.fixture()
            data['gateways'][0].update(update)
            self.assertEqual(normalize(data, 'montreal'), [])
        data = self.fixture()
        data['locations']['Montréal']['country_code'] = 'US'
        self.assertEqual(normalize(data, 'montreal'), [])

    def test_each_country_model_confirms_only_matching_exit(self):
        for selected, region in P.REGIONS.items():
            m = P.Model(selected)
            wrong = 'NL' if region['country'] != 'NL' else 'FR'
            m.line(f'@RISEUP\tconnected\t192.0.2.1\t{wrong}\n')
            self.assertIsNone(m.since)
            m.line(f"@RISEUP\tconnected\t192.0.2.1\t{region['country']}\n")
            self.assertEqual(m.state, 'connected')
            self.assertEqual(m.region, region['country'])

    def test_map_country_highlight_and_geographic_positions(self):
        for country in ('NL', 'FR', 'CA', 'US'):
            rows = render(96, 20, country)
            self.assertEqual((len(rows), len(rows[0])), (20, 96))
            self.assertGreater(sum(highlight for row in rows for _, highlight in row), 0)
        ams = position(4.9, 52.37, 96, 20)
        sea = position(-122.33, 47.61, 96, 20)
        self.assertLess(sea[0], ams[0])
        self.assertEqual(render(96, 20, 'US')[18][48][0], ' ')  # South Atlantic

    def test_layouts_keep_both_graphs_and_region_button_visible(self):
        m = P.Model('paris')
        with patch.object(P.curses, 'color_pair', side_effect=lambda color: color):
            for width, height in [(128, 40), (100, 40), (65, 35), (80, 32)]:
                screen = Screen(width, height)
                P.draw(screen, m, False, False)
                self.assertIn('[R] Регион', screen.text())
                self.assertIn('↑', screen.text())
                self.assertIn('↓', screen.text())
                self.assertIn('@', screen.text())
                self.assertNotIn('Увеличьте окно', screen.text())

    def terminal_switch(self, cleanup_ok):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp)/'actions'
            backend = Path(tmp)/'backend.sh'
            backend.write_text('''region=${4:-amsterdam}
echo "start:$region" >> "$ACTIONS"
finish() {
 echo "stop:$region" >> "$ACTIONS"
 if [[ "$CLEANUP_OK" == yes ]]; then printf '@RISEUP\\tcleanup\\tok\\n'; fi
 exit 130
}
trap finish INT TERM
country=NL
[[ "$region" == paris ]] && country=FR
printf '@RISEUP\\tlocation\\t%s\\tCity\\t%s\\n' "$region" "$country"
printf '@RISEUP\\tconnected\\t192.0.2.1\\t%s\\n' "$country"
while :; do sleep .05; done
''')
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))
            process = subprocess.Popen(['python3', str(ROOT/'riseup-panel.py'), str(backend)],
                                       stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
                                       env=dict(os.environ, TERM='xterm-256color', ACTIONS=str(log),
                                                CLEANUP_OK='yes' if cleanup_ok else 'no'))
            os.close(slave)
            output = bytearray()
            def collect(seconds):
                until = time.monotonic()+seconds
                while time.monotonic() < until:
                    if select.select([master], [], [], .03)[0]:
                        try: output.extend(os.read(master, 65536))
                        except OSError: break
            try:
                collect(.3)
                # Ctrl+S must reach curses even if the terminal initially enables IXON.
                os.write(master, b'\x13'); collect(.25)
                self.assertIsNone(process.poll())
                if cleanup_ok:
                    self.assertIn('stop:amsterdam', log.read_text())
                    os.write(master, b'\x13'); collect(.25)
                    self.assertEqual(log.read_text().count('start:amsterdam'), 2)
                os.write(master, b'r'); collect(.15)
                os.write(master, b'j'); collect(.15)
                os.write(master, b'\r'); collect(.5)
                if cleanup_ok:
                    self.assertEqual(log.read_text().splitlines()[-3:],
                                     ['start:amsterdam', 'stop:amsterdam', 'start:paris'])
                    os.killpg(process.pid, signal.SIGINT)
                    collect(.2)
                    os.write(master, b'q')
                else:
                    self.assertNotIn('start:paris', log.read_text())
                    os.write(master, b'q')
                collect(.4)
                process.wait(timeout=5)
                self.assertNotIn('Traceback', output.decode())
                self.assertIn('ВЫБОР БЕСПЛАТНОГО РЕГИОНА', output.decode())
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    collect(.3)
                    process.wait(timeout=5)
                os.close(master)

    def test_terminal_switch_waits_for_cleanup_before_starting_next_region(self):
        self.terminal_switch(True)

    def test_terminal_refuses_switch_without_cleanup_acknowledgement(self):
        self.terminal_switch(False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
