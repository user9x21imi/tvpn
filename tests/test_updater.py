import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import updater as U


class UpdaterTests(unittest.TestCase):
    def setUp(self):U.DECLINED.clear()
    def tearDown(self):U.DECLINED.clear()

    def archive(self,extra=None,version='1.2.0'):
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('VERSION',version+'\n')
            z.writestr('riseup-panel.py','new panel')
            for name,data in (extra or {}).items():z.writestr(name,data)
        return output.getvalue()

    def update(self,data):
        return U.Update('1.2.0','https://raw.githubusercontent.com/user9x21imi/riseup-vpn-panel/main/assets/update-bundle.zip',hashlib.sha256(data).hexdigest(),len(data))

    def fetcher(self,data):
        return lambda url,destination,**kwargs:Path(destination).write_bytes(data)

    def test_semantic_versions_and_no_downgrade(self):
        doc=vars(self.update(b'x')).copy();doc['version']='1.10.0'
        self.assertEqual(U.parse_manifest(doc,'1.9.9').version,'1.10.0')
        self.assertIsNone(U.parse_manifest(doc,'1.10.0'))
        self.assertIsNone(U.parse_manifest(doc,'2.0.0'))

    def test_manifest_rejects_other_hosts_bad_hash_and_size(self):
        for changes in [{'url':'https://evil.test/update.zip'},{'url':'http://github.com/user9x21imi/riseup-vpn-panel/raw/main/update.zip'},
                        {'sha256':'123'},{'size':True},{'size':U.MAX_ARCHIVE+1}]:
            doc=vars(self.update(b'x')).copy();doc.update(changes)
            with self.assertRaises(U.UpdateError):U.parse_manifest(doc,'1.0.0')
        self.assertFalse(U.trusted_url('https://raw.githubusercontent.com:bad/user9x21imi/riseup-vpn-panel/a'))

    def test_verified_update_preserves_environment_and_settings(self):
        data=self.archive({'new.py':'hello'})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'app';root.mkdir();(root/'VERSION').write_text('1.0.0\n', encoding='utf-8');(root/'riseup-panel.py').write_text('old panel', encoding='utf-8')
            (root/'.venv').mkdir();(root/'.venv/user-data').write_text('preserve', encoding='utf-8')
            (root/'settings').mkdir();(root/'settings/user.json').write_text('{}', encoding='utf-8')
            U.apply(self.update(data),root,fetch=self.fetcher(data),platform='win32')
            self.assertEqual(U.local_version(root),'1.2.0')
            self.assertEqual((root/'riseup-panel.py').read_text(encoding='utf-8'),'new panel')
            self.assertEqual((root/'.venv/user-data').read_text(encoding='utf-8'),'preserve')
            self.assertTrue((root/'settings/user.json').exists())
            self.assertFalse((root/'.update.lock').exists())

    def test_corrupt_download_keeps_old_version(self):
        data=self.archive()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'VERSION').write_text('1.0.0\n', encoding='utf-8')
            with self.assertRaisesRegex(U.UpdateError,'SHA256'):
                U.apply(self.update(data),root,fetch=self.fetcher(data+b'corrupt'),platform='win32')
            self.assertEqual(U.local_version(root),'1.0.0')
            self.assertFalse((root/'.update.lock').exists())

    def test_archive_version_must_match_manifest(self):
        data=self.archive(version='9.9.9')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(U.UpdateError,'Версия архива'):
                U.apply(self.update(data),Path(tmp),fetch=self.fetcher(data),platform='win32')

    def test_zip_slip_private_keys_and_venv_are_rejected(self):
        for name in ['../escaped.py','/absolute.py','C:/evil.py','a\\evil.py','.git/config','.venv/python','client.pem','client.key','settings/private.json']:
            with tempfile.TemporaryDirectory() as tmp:
                archive=Path(tmp)/'update.zip';archive.write_bytes(self.archive({name:'bad'}))
                with self.assertRaises(U.UpdateError):U.extract(archive,Path(tmp)/'stage')

    def test_archive_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)/'link.zip'
            with zipfile.ZipFile(archive,'w') as z:
                info=zipfile.ZipInfo('evil');info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,'/etc')
            with self.assertRaises(U.UpdateError):U.extract(archive,Path(tmp)/'stage')

    def test_write_failure_rolls_back_all_completed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root,stage=Path(tmp)/'app',Path(tmp)/'stage';root.mkdir();stage.mkdir()
            (root/'a.py').write_text('old A', encoding='utf-8');(root/'b.py').write_text('old B', encoding='utf-8')
            (stage/'a.py').write_text('new A', encoding='utf-8');(stage/'b.py').write_text('new B', encoding='utf-8')
            original=U.os.replace
            def fail_b(source,destination):
                if Path(destination).name=='b.py':raise OSError('disk full')
                return original(source,destination)
            with patch.object(U.os,'replace',side_effect=fail_b):
                with self.assertRaises(OSError):U.replace_files(root,stage)
            self.assertEqual((root/'a.py').read_text(encoding='utf-8'),'old A')
            self.assertEqual((root/'b.py').read_text(encoding='utf-8'),'old B')
            self.assertFalse(list(root.glob('*.update-new')))

    def test_existing_parent_symlink_cannot_escape_installation(self):
        if sys.platform=='win32':self.skipTest('Creating symlinks requires extra Windows privileges')
        with tempfile.TemporaryDirectory() as tmp:
            root,stage,outside=(Path(tmp)/n for n in ['app','stage','outside'])
            root.mkdir();stage.mkdir();outside.mkdir();(root/'assets').symlink_to(outside,target_is_directory=True)
            (stage/'assets').mkdir();(stage/'assets/evil.py').write_text('bad', encoding='utf-8')
            with self.assertRaises(U.UpdateError):U.replace_files(root,stage)
            self.assertFalse((outside/'evil.py').exists())

    def test_helper_authorization_is_requested_only_for_changed_backend(self):
        data=self.archive({'Riseup-Amsterdam-SteamDeck.sh':'new backend'})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'VERSION').write_text('1.0.0\n', encoding='utf-8');called=[]
            U.apply(self.update(data),root,fetch=self.fetcher(data),helper=lambda *args:called.append(args),platform='linux')
            self.assertEqual(len(called),1)
            U.apply(self.update(data),root,fetch=self.fetcher(data),helper=lambda *args:called.append(args),platform='linux')
            self.assertEqual(len(called),1)

    def test_denied_helper_update_leaves_user_files_untouched(self):
        data=self.archive({'Riseup-Amsterdam-SteamDeck.sh':'new backend'})
        def deny(*args):raise U.UpdateError('permission denied')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'VERSION').write_text('1.0.0\n', encoding='utf-8')
            with self.assertRaises(U.UpdateError):U.apply(self.update(data),root,fetch=self.fetcher(data),helper=deny,platform='linux')
            self.assertEqual(U.local_version(root),'1.0.0')

    def test_background_check_and_no_suppress_same_version(self):
        found=self.update(b'x');watcher=U.Watcher(ROOT,loader=lambda:found)
        self.assertIsNone(watcher.poll());watcher._thread.join(1)
        self.assertEqual(watcher.poll(),found)
        U.decline(found)
        other=U.Watcher(ROOT,loader=lambda:found);other.poll();other._thread.join(1)
        self.assertIsNone(other.poll())

    def test_offline_server_is_quiet_and_does_not_block_ui(self):
        def offline():raise U.UpdateError('offline')
        watcher=U.Watcher(ROOT,loader=offline);self.assertIsNone(watcher.poll());watcher._thread.join(1)
        self.assertIsNone(watcher.poll())


if __name__=='__main__':unittest.main(verbosity=2)
