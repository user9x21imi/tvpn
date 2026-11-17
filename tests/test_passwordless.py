import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from test_panel import ROOT, HEADER


class PasswordlessTests(unittest.TestCase):
    def test_policy_is_valid_and_contains_only_thirteen_exact_commands(self):
        installer = (ROOT/'install-passwordless.sh').read_text(encoding='utf-8')
        start = installer.index("{\n    echo '# RiseupVPN:")
        end = installer.index('\nchmod 440', start)
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['bash', '-c', 'work=$1\n'+installer[start:end], 'policy-test', tmp], check=True)
            policy = Path(tmp)/'policy'
            checked = subprocess.run(['visudo', '-cf', str(policy)], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stdout+checked.stderr)
            commands = [line.split('NOPASSWD: ', 1)[1] for line in policy.read_text(encoding='utf-8').splitlines()
                        if 'NOPASSWD:' in line]
            self.assertEqual(len(commands), 13)
            self.assertIn('/var/lib/riseup-vpn/backend.sh --text --check', commands)
            for command in commands:
                if command.endswith(' --text --check'):
                    continue
                words = shlex.split(command)
                self.assertEqual(words[:3], ['/var/lib/riseup-vpn/backend.sh', '--text', '--region'])
                self.assertIn(words[3], ['amsterdam', 'paris', 'montreal', 'newyork', 'miami', 'seattle'])
                self.assertIn(words[4:], [[], ['--events']])
                self.assertNotIn('*', command)
                self.assertNotIn('/home/deck', command)

    def test_launcher_uses_noninteractive_sudo_and_fixed_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            sudo = d/'sudo'
            sudo.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding='utf-8')
            sudo.chmod(0o700)
            source = HEADER.replace('export PATH=/usr/bin:/bin:/usr/sbin:/sbin', ':')
            source = source.replace('[[ -f /var/lib/riseup-vpn/backend.sh ]]', 'true')
            script = d/'launcher.sh'; script.write_text(source, encoding='utf-8')
            result = subprocess.run(['bash', str(script), '--text', '--region', 'paris', '--events'],
                                    env=dict(os.environ, PATH=tmp+':'+os.environ['PATH']),
                                    capture_output=True, text=True, timeout=2)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['-n', '--', '/var/lib/riseup-vpn/backend.sh',
                                                        '--text', '--region', 'paris', '--events'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
