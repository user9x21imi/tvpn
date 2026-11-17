import base64
import importlib.util
import io
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import tarfile
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('panel', ROOT / 'riseup-panel.py')
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
SOURCE = (ROOT / 'Riseup-Amsterdam-SteamDeck.sh').read_text()
HEADER, PAYLOAD = SOURCE.split('__RISEUP_RUNTIME_BELOW__\n', 1)


class PanelTests(unittest.TestCase):
    def test_counters_actual_elapsed_reset_and_missing_interface(self):
        m = P.Model()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            def values(rx, tx):
                (root/'rx_bytes').write_text(str(rx))
                (root/'tx_bytes').write_text(str(tx))
            values(100, 200); m.sample(10, root)
            values(100+2**21, 200+2**20); m.sample(12, root)
            self.assertEqual((m.down, m.up), (1, .5))
            self.assertEqual((m.rx, m.tx), (2**21, 2**20))
            values(1, 2); m.sample(13, root)
            self.assertEqual((m.rx, m.tx, m.down), (0, 0, 0))
            (root/'rx_bytes').unlink(); m.sample(14, root)
            self.assertIsNone(m.last)

    def test_events_and_secret_filter(self):
        m = P.Model()
        m.line('@RISEUP\tgateway\tvpn13-ams\tАмстердам\t51.158.144.31\n')
        self.assertEqual(m.city, 'Амстердам')
        self.assertEqual(m.region, '—')
        m.line('@RISEUP\tconnected\t1.2.3.4\tUS\n')
        self.assertIsNone(m.since)
        m.line('@RISEUP\tconnected\t1.2.3.4\tNL\n')
        self.assertEqual(m.state, 'connected')
        for line in ['-----BEGIN PRIVATE KEY-----', 'secret', '-----END PRIVATE KEY-----', '\x1b[31mnormal']:
            m.line(line)
        self.assertNotIn('secret', ' '.join(m.logs))
        self.assertNotIn('\x1b', ' '.join(m.logs))

    def backend(self, scenario, selected='amsterdam', exit_country=None):
        """Execute original control flow with network/runtime isolated in a tempdir."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            import shutil
            shutil.copy2(ROOT/'verify_exit.py',d/'verify_exit.py')
            import json
            gateways, locations = [], {}
            for index, (region, meta) in enumerate(P.REGIONS.items()):
                locations[region] = {'name': region, 'country_code': meta['country']}
                for number in (4, 13):
                    host = f'vpn{number:02}-ams' if region == 'amsterdam' else f'vpn{number:02}-{region}'
                    gateways.append({'host': host+'.riseup.net', 'ip_address': f'192.0.2.{index*2+(number==13)+1}',
                                     'location': region, 'capabilities': {'limited': False, 'transport': [
                                         {'type': 'openvpn', 'ports': ['1194', '80'], 'protocols': ['udp', 'tcp']}]}})
            (d/'inventory.json').write_text(json.dumps({'locations': locations, 'gateways': gateways}))
            fake = d/'openvpn-fake'
            fake.write_text('''#!/bin/bash
trap 'echo route-restored >> "$TEST_DIR/actions"; exit 0' TERM INT
printf 'Initialization Sequence Completed\\n' > "$TEST_DIR/openvpn.log"
echo route-added >> "$TEST_DIR/actions"
while :; do /bin/sleep .05; done
''')
            fake.chmod(0o700)
            hook = d/'dns-hook'
            hook.write_text('#!/bin/bash\necho dns-restored >> "$TEST_DIR/actions"\n')
            hook.chmod(0o700)
            # Keep production connection and cleanup functions; substitute boundaries.
            h = HEADER
            a = h.index('if [[ "$(uname -sm)"')
            b = h.index('directory=$(mktemp', a)
            h = h[:a] + h[b:]
            h = h.replace('directory=$(mktemp -d /run/riseup-amsterdam.XXXXXXXX)', 'directory="$TEST_DIR"')
            h = h.replace('extract_runtime "$directory"', ':')
            h = h.replace('python3 -I "$(dirname "$script")/riseup_regions.py"',
                          f'python3 "{ROOT}/riseup_regions.py"')
            h = h.replace('find "$directory" -depth -delete', ':')
            a = h.index('runtime="$directory/openvpn"')
            b = h.index('\nconnect() {', a)
            h = h[:a] + 'openvpn=("$TEST_DIR/openvpn-fake")\n' + h[b:]
            h = h.replace('sleep 1', 'sleep .02')
            h = h.replace('echo \'VPN работает, пока открыт Konsole. Ctrl+C — отключить.\'', "kill -INT $$")
            prelude = '''
curl() {
  if [[ "$*" == *'/3/cert'* ]]; then
    echo "cert-attempt" >> "$TEST_DIR/actions"
    if [[ "$SCENARIO" == timeout ]]; then echo 'curl: (28) Operation timed out' >&2; return 28; fi
    printf '%s\\n' '-----BEGIN CERTIFICATE-----' '-----BEGIN PRIVATE KEY-----' > client.pem
  elif [[ "$*" == *'eip-service.json'* ]]; then
    if [[ "$SCENARIO" == no_catalog ]]; then return 28; fi
    cp "$TEST_DIR/inventory.json" gateways.json
  elif [[ "$*" == *'ipwho.is/'* ]]; then
    geo_country=$EXIT_COUNTRY
    [[ "$SCENARIO" == geo_conflict ]] && geo_country=FR
    printf '{"success":true,"ip":"1.2.3.4","country_code":"%s","city":"Observed city"}' "$geo_country" > exit-geo.json
  else
    if [[ "$SCENARIO" == fallback && "$(cat "$TEST_DIR/host")" == vpn04-ams ]]; then return 28; fi
    if [[ "$SCENARIO" == udp_blocked ]] && grep -q '^proto udp$' client.ovpn; then return 28; fi
    printf 'ip=1.2.3.4\\nloc=%s\\n' "$EXIT_COUNTRY"
  fi
}
'''
            h = h.replace('extract_runtime() {', prelude+'\nextract_runtime() {')
            h = h.replace('    event gateway "$host"', '    echo "$host" > "$TEST_DIR/host"\n    event gateway "$host"')
            script = d/'backend.sh'; script.write_text(h)
            env = dict(os.environ, TEST_DIR=tmp, SCENARIO=scenario,
                       EXIT_COUNTRY=exit_country or P.REGIONS[selected]['country'])
            result = subprocess.run(['bash', str(script), '--text', '--events', '--region', selected], env=env,
                                    capture_output=True, text=True, timeout=10)
            return result, (d/'actions').read_text()

    def test_certificate_timeout_and_cleanup(self):
        result, actions = self.backend('timeout')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(actions.count('cert-attempt'), 4)
        self.assertIn('@RISEUP\tstate\tcertificate', result.stdout)
        self.assertIn('@RISEUP\tstate\terror', result.stdout)
        self.assertIn('dns-restored', actions)
        self.assertNotIn('route-added', actions)

    def test_fallback_verified_connection_and_ctrl_c_cleanup(self):
        result, actions = self.backend('fallback')
        self.assertEqual(result.returncode, 130, result.stderr)
        for event in ['fallback', 'verifying', 'connected\t1.2.3.4\tNL']:
            self.assertIn(event, result.stdout)
        self.assertIn('vpn13-ams\tАмстердам', result.stdout)
        self.assertEqual(actions.count('route-added'), 2)
        self.assertEqual(actions.count('route-restored'), 2)
        self.assertGreaterEqual(actions.count('dns-restored'),2)
        self.assertIn('@RISEUP\tcleanup\tok',result.stdout)

    def test_tcp_fallback_when_udp_is_blocked(self):
        result, actions = self.backend('udp_blocked')
        self.assertEqual(result.returncode,130,result.stderr)
        self.assertIn('@RISEUP\tconnected',result.stdout)
        self.assertEqual(actions.count('route-added'),3)

    def test_independent_geo_country_conflict_rejects_exit(self):
        result, actions = self.backend('geo_conflict')
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertNotIn('@RISEUP\tconnected',result.stdout)
        self.assertIn('Страна выхода FR, выбрана NL',result.stderr)
        self.assertGreaterEqual(actions.count('dns-restored'), 2)
        self.assertIn('@RISEUP\tcleanup\tok', result.stdout)

    def test_every_region_uses_matching_country_and_real_inventory_flow(self):
        for region in P.REGIONS:
            with self.subTest(region=region):
                result, actions = self.backend('normal', region)
                self.assertEqual(result.returncode, 130, result.stderr)
                self.assertIn('connected\t1.2.3.4\t'+P.REGIONS[region]['country'], result.stdout)
                self.assertEqual(actions.count('route-added'), 1)
                self.assertEqual(actions.count('route-restored'), 1)

    def test_wrong_egress_country_is_rejected(self):
        result, actions = self.backend('wrong_country', 'paris', 'NL')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('@RISEUP\tconnected', result.stdout)
        self.assertEqual(actions.count('route-restored'), 8)

    def test_missing_catalog_never_connects_another_region(self):
        result, actions = self.backend('no_catalog', 'paris')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertNotIn('route-added', actions)
        self.assertNotIn('cert-attempt', actions)
        self.assertIn('не вернул доступных публичных шлюзов', result.stderr)

    def test_amsterdam_offline_catalog_fallback(self):
        result, actions = self.backend('no_catalog')
        self.assertEqual(result.returncode, 130, result.stderr)
        self.assertIn('Использую сохранённые шлюзы', result.stdout)
        self.assertIn('@RISEUP\tconnected', result.stdout)

    def test_real_embedded_dns_hook_restores_temp_resolver(self):
        archive = tarfile.open(fileobj=io.BytesIO(base64.b64decode(PAYLOAD)), mode='r:gz')
        hook = archive.extractfile(next(m for m in archive.getmembers() if m.name.endswith('/dns-hook'))).read().decode()
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); resolver = d/'resolv.conf'
            resolver.write_text('nameserver 192.0.2.1\n')
            (d/'dns-original').write_text('nameserver 192.0.2.1\n')
            (d/'dns-active').write_text('nameserver 10.1.2.3\n')
            resolver.write_text('nameserver 10.1.2.3\n')
            (d/'dns-target').write_text(str(resolver))
            script = d/'dns-hook'; script.write_text(hook)
            subprocess.run(['bash', str(script)], env=dict(os.environ, script_type='down'), check=True)
            self.assertEqual(resolver.read_text(), 'nameserver 192.0.2.1\n')
            self.assertFalse((d/'dns-target').exists())

    def test_terminal_start_resize_log_and_disconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = Path(tmp)/'fake.sh'
            backend.write_text("trap \"printf '@RISEUP\\tcleanup\\tok\\n'; exit 130\" INT TERM\nprintf '@RISEUP\\tstate\\tcertificate\\tПолучение сертификата\\n'\nsleep .2\nprintf '@RISEUP\\tgateway\\tvpn04-ams\\tАмстердам\\n@RISEUP\\tconnected\\t1.2.3.4\\tNL\\n'\nwhile :; do sleep .1; done\n")
            master, slave = pty.openpty()
            import fcntl, struct, termios
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 42, 110, 0, 0))
            process = subprocess.Popen(['python3', str(ROOT/'riseup-panel.py'), str(backend)],
                                       stdin=slave, stdout=slave, stderr=slave,
                                       env=dict(os.environ, RISEUP_NO_UPDATE_CHECK='1', TERM='xterm-256color'), start_new_session=True)
            os.close(slave)
            output = b''
            def collect(seconds):
                nonlocal output
                until = time.monotonic()+seconds
                while time.monotonic() < until:
                    if select.select([master], [], [], .05)[0]:
                        try: output += os.read(master, 65536)
                        except OSError: break
            collect(.6)
            os.write(master, b'l'); collect(.2)
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 65, 0, 0))
            os.kill(process.pid, signal.SIGWINCH)
            os.write(master, b'l'); collect(.2)
            os.killpg(process.pid, signal.SIGINT); collect(.5)
            self.assertIsNone(process.poll())
            os.write(master, b'q'); collect(.2)
            process.wait(timeout=5)
            os.close(master)
            self.assertEqual(process.returncode, 0, output.decode(errors='replace'))
            self.assertIn('ПОДКЛЮЧЕНО', output.decode())
            self.assertIn('ОТКЛЮЧЕНО', output.decode())
            self.assertNotIn('Traceback', output.decode())


if __name__ == '__main__':
    unittest.main(verbosity=2)
