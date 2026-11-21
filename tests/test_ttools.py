"""Isolated handoff contract tests; never authorizes root or starts a VPN."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import updater as U


class TtoolsTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux guard entrypoint')
    def test_guard_is_a_fixed_sudo_argv_and_fails_closed_without_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper=Path(tmp)/'backend.sh';helper.write_text('protected');calls=[]
            class Fake:
                def __init__(self,ready):
                    self.stdout=io.StringIO(ready);self.stderr=io.StringIO('permission denied')
                    self.stdin=io.StringIO();self.returncode=0
                def wait(self,timeout=None):return self.returncode
                def poll(self):return self.returncode
                def terminate(self):self.returncode=-15
                def kill(self):self.returncode=-9
            fake=Fake('TVPN_GUARD_READY\n')
            with patch.object(U,'Path',side_effect=lambda value:helper if str(value)=='/var/lib/riseup-vpn/backend.sh' else Path(value)), \
                 patch.object(U.shutil,'which',return_value='/usr/bin/sudo'), \
                 patch.object(U.subprocess,'Popen',side_effect=lambda argv,**kw:(calls.append(argv) or fake)), \
                 patch.object(U.select,'select',side_effect=lambda *a,**kw:([fake.stdout],[],[])):
                with U.backend_idle():pass
                self.assertEqual(calls[0],['/usr/bin/sudo','-n','--',str(helper),'--text','--guard'])
                fake=Fake('')
                with self.assertRaises(U.UpdateError):
                    with U.backend_idle():pass

    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux flock protocol')
    def test_backend_guard_refuses_active_and_holds_lock_until_eof(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            lock=Path(tmp)/'lock';script=Path(tmp)/'guard.sh'
            script.write_text('#!/bin/bash\nexec 9>"$TEST_LOCK"\nif ! flock -s -n 9; then echo TVPN_BACKEND_BUSY >&2; exit 3; fi\necho TVPN_GUARD_READY\nIFS= read -r _release || true\n',encoding='utf-8')
            script.chmod(0o755)
            with lock.open('w') as held:
                fcntl.flock(held.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                busy=subprocess.run(['bash',str(script)],env=dict(os.environ,TEST_LOCK=str(lock)),capture_output=True,text=True,timeout=3)
                self.assertEqual(busy.returncode,3)
                self.assertIn('TVPN_BACKEND_BUSY',busy.stderr)
            guard=subprocess.Popen(['bash',str(script)],env=dict(os.environ,TEST_LOCK=str(lock)),stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            try:
                self.assertEqual(guard.stdout.readline().strip(),'TVPN_GUARD_READY')
                with lock.open('rb') as probe:
                    with self.assertRaises(BlockingIOError):fcntl.flock(probe.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                guard.stdin.close();self.assertEqual(guard.wait(timeout=3),0);guard.stdout.close()
            finally:
                if guard.poll() is None:guard.kill();guard.wait()

    @unittest.skipUnless(sys.platform.startswith('linux'),'ttools lifecycle lock is a Linux handoff contract')
    def test_lock_excludes_updater_and_reports_real_ui_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            with U.lifecycle(tmp,'ui'):
                self.assertEqual(U.lifecycle_status(tmp)['pid'],os.getpid())
                with self.assertRaises(U.UpdateError):
                    U.apply(U.Update('9.0.0','unused','0'*64,1),tmp)
            self.assertFalse(U.lifecycle_status(tmp)['running'])

    def test_missing_cleanup_ack_blocks_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'.cleanup.json';p.write_text('{"cleanup":"pending"}',encoding='utf-8')
            with self.assertRaises(U.UpdateError):U.apply(U.Update('9.0.0','unused','0'*64,1),tmp)
            p.write_text('{"cleanup":"failed"}',encoding='utf-8')
            with self.assertRaises(U.UpdateError):U.require_clean(tmp)

    @unittest.skipUnless(sys.platform.startswith('linux') and os.geteuid()!=0,'Linux ordinary user installer')
    def test_install_only_unicode_repeat_preserves_settings_no_system_calls(self):
        with tempfile.TemporaryDirectory(prefix='TVPN кириллица пробел ') as tmp:
            prefix=Path(tmp)/'Установка VPN'
            argv=[sys.executable,str(ROOT/'install.py'),'--prefix',str(prefix),'--no-launch','--defer-system']
            for _ in range(2):
                run=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',timeout=30)
                self.assertEqual(run.returncode,0,run.stdout+run.stderr)
                result=json.loads(run.stdout)
                self.assertFalse(result['launched']);self.assertFalse(result['system_ready'])
                settings=prefix/'settings';settings.mkdir(exist_ok=True)
                (settings/'keep.json').write_text('{"test":"keep"}',encoding='utf-8')
            self.assertEqual((prefix/'settings/keep.json').read_text(),'{"test":"keep"}')
            version=subprocess.run([sys.executable,str(prefix/'manage.py'),'version'],capture_output=True,text=True,timeout=5)
            self.assertEqual(version.returncode,0,version.stderr)
            self.assertEqual(json.loads(version.stdout)['version'],U.local_version(ROOT))
            self.assertFalse((prefix/'.cleanup.json').exists())
            self.assertFalse((prefix/'client.pem').exists())

    def test_update_transaction_unicode_root_and_helper_failure_rollback(self):
        with tempfile.TemporaryDirectory(prefix='TVPN обновление ') as tmp:
            root=Path(tmp);(root/'VERSION').write_text('1.0.0\n')
            (root/'settings').mkdir();(root/'settings/keep').write_text('saved')
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w') as z:
                z.writestr('VERSION','9.0.0\n');z.writestr('riseup-panel.py','new panel')
                z.writestr('Riseup-Amsterdam-SteamDeck.sh','changed helper')
            body=data.getvalue();update=U.Update('9.0.0','https://github.com/user9x21imi/tvpn/test',hashlib.sha256(body).hexdigest(),len(body))
            fetch=lambda url,destination,**kw:Path(destination).write_bytes(body)
            with patch.object(U,'backend_idle',side_effect=contextlib.nullcontext):
                with self.assertRaises(U.UpdateError):
                    U.apply(update,root,fetch=fetch,helper=lambda *a:(_ for _ in ()).throw(U.UpdateError('denied')),platform='linux')
                self.assertEqual(U.local_version(root),'1.0.0')
                U.apply(update,root,fetch=fetch,helper=lambda *a:None,platform='linux')
            self.assertEqual(U.local_version(root),'9.0.0')
            self.assertEqual((root/'settings/keep').read_text(),'saved')
            self.assertFalse((root/'.update.lock').exists())

    @unittest.skipUnless(sys.platform.startswith('linux'),'Unix signal integration')
    def test_machine_stop_waits_for_ack_and_times_out_without_killing(self):
        import importlib.util,time
        spec=importlib.util.spec_from_file_location('manage_test',ROOT/'manage.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for ack in (True,False):
            with self.subTest(ack=ack),tempfile.TemporaryDirectory() as tmp:
                script="""import sys,time,signal,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import updater
root=Path(sys.argv[2])
def stop(*args):
 if sys.argv[3]=='yes':
  (root/'.cleanup.json').write_text(json.dumps({'cleanup':'ok','region':'paris'}))
  raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
with updater.lifecycle(root,'ui'):
 (root/'.cleanup.json').write_text(json.dumps({'cleanup':'pending','region':'paris'}))
 (root/'ready').touch()
 while True:time.sleep(.02)
"""
                child=subprocess.Popen([sys.executable,'-c',script,str(ROOT),tmp,'yes' if ack else 'no'])
                try:
                    deadline=time.monotonic()+5
                    while not (Path(tmp)/'ready').exists() and time.monotonic()<deadline:time.sleep(.01)
                    self.assertTrue((Path(tmp)/'ready').exists())
                    output=io.StringIO()
                    with patch.object(U,'backend_idle',side_effect=contextlib.nullcontext),contextlib.redirect_stdout(output):
                        code=module.main(['--root',tmp,'stop','--timeout','0.25'])
                    self.assertEqual(code,0 if ack else 1,output.getvalue())
                    if ack:
                        child.wait(timeout=2)
                        self.assertEqual(json.loads((Path(tmp)/'.cleanup.json').read_text())['region'],'paris')
                    else:self.assertIsNone(child.poll())
                finally:
                    if child.poll() is None:child.kill();child.wait()



if __name__=='__main__':unittest.main()
