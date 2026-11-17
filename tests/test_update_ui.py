"""PTY confirmation and cleanup orchestration; no network or real installer."""
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
try:
    import pty,fcntl,termios,struct
except ImportError:
    pty=None

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipIf(pty is None,'PTY integration requires Unix')
class UpdateUITests(unittest.TestCase):
    def exercise(self,answer,ack=True):
        with tempfile.TemporaryDirectory() as tmp:
            app=Path(tmp)
            for name in ['riseup-panel.py','riseup_regions.py','world_map.py','globe.py','world-land.json','stoped_title.py','stoped-mask.json','VERSION','updater.py']:
                shutil.copy2(ROOT/name,app/name)
            # Only the network checker and install side effects are test doubles.
            with (app/'updater.py').open('a') as out:
                out.write('''
class Watcher:
    def __init__(self,root):self.sent=False
    def poll(self):
        if self.sent:return None
        self.sent=True
        return Update('9.0.0','https://raw.githubusercontent.com/user9x21imi/tvpn/main/assets/update-bundle.zip','0'*64,1)
def apply(update,root):
    assert not (Path(root)/'active').exists(), 'Installer ran before backend stopped'
    with (Path(root)/'actions').open('a') as f:f.write('apply\\n')
def restart(root,region):
    with (Path(root)/'actions').open('a') as f:f.write('restart\\n')
    raise SystemExit(0)
''')
            backend=app/'fake-backend.sh'
            backend.write_text('''#!/bin/bash
finish() {
 echo stop >> "$APP/actions"
 rm -f "$APP/active"
 if [[ "$ACK" == yes ]]; then echo cleanup >> "$APP/actions"; printf '@RISEUP\\tcleanup\\tok\\n'; fi
 exit 130
}
trap finish INT TERM
: > "$APP/active"
echo start >> "$APP/actions"
printf '@RISEUP\\tconnected\\t192.0.2.1\\tNL\\n'
while :; do sleep .05; done
''', encoding='utf-8')
            master,slave=pty.openpty()
            fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',40,120,0,0))
            process=subprocess.Popen([sys.executable,str(app/'riseup-panel.py'),str(backend)],
                                     stdin=slave,stdout=slave,stderr=slave,start_new_session=True,
                                     env=dict(os.environ,TERM='xterm-256color',RISEUP_NO_UPDATE_CHECK='0',APP=str(app),ACK='yes' if ack else 'no'))
            os.close(slave);output=bytearray()
            def collect(seconds=.05):
                until=time.monotonic()+seconds
                while time.monotonic()<until:
                    if select.select([master],[],[],.02)[0]:
                        try:output.extend(os.read(master,65536))
                        except OSError:return
            def wait_for(predicate):
                until=time.monotonic()+6
                while not predicate() and time.monotonic()<until:collect()
                self.assertTrue(predicate(),output.decode(errors='replace')[-3000:])
            try:
                wait_for(lambda:'ДОСТУПНО ОБНОВЛЕНИЕ'.encode() in output)
                os.write(master,answer.encode())
                if answer=='n':
                    collect(.2)
                    self.assertTrue((app/'active').exists())
                    self.assertNotIn('apply',(app/'actions').read_text(encoding='utf-8'))
                    os.write(master,b'\x13')
                    wait_for(lambda:not (app/'active').exists())
                    collect(.2);os.write(master,b'q')
                elif not ack:
                    wait_for(lambda:not (app/'active').exists())
                    collect(.2);os.write(master,b'q')
                wait_for(lambda:process.poll() is not None)
                actions=(app/'actions').read_text(encoding='utf-8').splitlines()
                if answer=='y' and ack:self.assertEqual(actions,['start','stop','cleanup','apply','restart'])
                else:self.assertNotIn('apply',actions)
                self.assertNotIn('Traceback',output.decode(errors='replace'))
            finally:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGTERM);collect(.3)
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
                os.close(master)

    def test_yes_stops_and_cleans_before_update_then_restarts(self):self.exercise('y')
    def test_no_keeps_existing_tunnel_running(self):self.exercise('n')
    def test_no_update_when_network_cleanup_was_not_acknowledged(self):self.exercise('y',False)


if __name__=='__main__':unittest.main(verbosity=2)
