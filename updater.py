"""Opt-in, HTTPS + SHA256 checked updates of the user-owned installation."""
import contextlib
import dataclasses
import hashlib
import json
import os
import queue
from pathlib import Path, PurePosixPath
import re
import shutil
import select
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse
import zipfile

MANIFEST_URL='https://raw.githubusercontent.com/user9x21imi/tvpn/main/update.json'
MAX_ARCHIVE=64*1024*1024
MAX_EXPANDED=128*1024*1024
DECLINED=set()
PROTECTED={'.cleanup.json','.lifecycle.lock','.git','.venv','__pycache__','logs','settings','.update.lock'}
PRIVATE_SUFFIXES=('.pem','.key','.ovpn','.log','.pid','.backup','.previous')


@dataclasses.dataclass(frozen=True)
class Update:
    version: str
    url: str
    sha256: str
    size: int


@dataclasses.dataclass(frozen=True)
class Request:
    update: Update
    region: str


class UpdateError(Exception):
    pass


@contextlib.contextmanager
def lifecycle(root,kind='update'):
    """Kernel lock shared by the UI and every updater; kernel releases on exit."""
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    path=root/'.lifecycle.lock'
    with path.open('a+b') as lock:
        try:
            if sys.platform=='win32':
                import msvcrt
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:raise UpdateError('TVPN занят: завершите клиент/обновление и дождитесь cleanup') from error
        try:
            lock.seek(0);lock.truncate();lock.write(json.dumps({'pid':os.getpid(),'kind':kind}).encode());lock.flush()
            yield
        finally:
            if sys.platform=='win32':
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)


def lifecycle_status(root):
    try:
        with lifecycle(root,'probe'):return {'running':False,'pid':None}
    except UpdateError:
        try:info=json.loads((Path(root)/'.lifecycle.lock').read_text(encoding='utf-8'))
        except (OSError,ValueError):info={}
        return {'running':True,'pid':info.get('pid') if info.get('kind')=='ui' else None,'kind':info.get('kind')}


def require_clean(root):
    marker=Path(root)/'.cleanup.json'
    if marker.exists():
        try:state=json.loads(marker.read_text(encoding='utf-8'))
        except (OSError,ValueError) as error:raise UpdateError('Неизвестное состояние cleanup; обновление запрещено') from error
        if state.get('cleanup')!='ok':raise UpdateError('Восстановление сети не подтверждено; обновление запрещено')


@contextlib.contextmanager
def backend_idle():
    """Hold the protected backend's shared kernel lock across update/install."""
    if not sys.platform.startswith('linux'):
        yield
        return
    helper=Path('/var/lib/riseup-vpn/backend.sh')
    if not helper.is_file():
        yield  # isolated user-prefix install before system setup
        return
    command=shutil.which('sudo') or '/usr/bin/sudo'
    guard=None
    try:
        guard=subprocess.Popen([command,'-n','--',str(helper),'--text','--guard'],
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                               text=True,encoding='utf-8',errors='replace')
        if not select.select([guard.stdout],[],[],5)[0]:
            guard.terminate();guard.wait(timeout=2)
            raise UpdateError('Истёк тайм-аут проверки системной блокировки VPN')
        ready=guard.stdout.readline().strip()
        if ready!='TVPN_GUARD_READY':
            try:guard.wait(timeout=5)
            except subprocess.TimeoutExpired:guard.terminate();guard.wait(timeout=2)
            details=guard.stderr.read().strip()
            raise UpdateError('Защищённый backend не смог заблокировать старт VPN; обновление отменено. Обновите системную установку. '+details[:180])
    except (OSError,subprocess.TimeoutExpired) as error:
        if guard is not None:
            if guard.poll() is None:guard.terminate();guard.wait(timeout=2)
            for stream in (guard.stdin,guard.stdout,guard.stderr):stream.close()
        raise UpdateError('Не удалось установить системную блокировку backend; обновление отменено') from error
    except UpdateError:
        for stream in (guard.stdin,guard.stdout,guard.stderr):stream.close()
        raise
    try:
        yield
    finally:
        guard.stdin.close()
        try:guard.wait(timeout=5)
        except subprocess.TimeoutExpired:
            guard.terminate()
            try:guard.wait(timeout=2)
            except subprocess.TimeoutExpired:guard.kill();guard.wait()
        guard.stdout.close();guard.stderr.close()


def version_tuple(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,6}\.\d{1,6}\.\d{1,6}',value):
        raise UpdateError('Некорректный номер версии')
    return tuple(int(n) for n in value.split('.'))


def local_version(root):
    try:
        value=(Path(root)/'VERSION').read_text(encoding='utf-8').strip()
        version_tuple(value)
        return value
    except (OSError,UpdateError):
        return '0.0.0'


def trusted_url(value):
    if not isinstance(value,str):return False
    try:
        url=urlparse(value)
        port=url.port
    except ValueError:
        return False
    if url.scheme!='https' or url.username or url.password or port not in (None,443):return False
    if url.netloc=='raw.githubusercontent.com':
        return url.path.startswith(('/user9x21imi/tvpn/','/user9x21imi/riseup-vpn-panel/'))
    if url.netloc=='github.com':
        return url.path.startswith(('/user9x21imi/tvpn/','/user9x21imi/riseup-vpn-panel/'))
    return False


def curl_path():
    if sys.platform=='win32':return str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/curl.exe')
    return shutil.which('curl') or '/usr/bin/curl'


def download(url,destination,limit=MAX_ARCHIVE,timeout=120):
    if not trusted_url(url):raise UpdateError('Обновление должно приходить из официального репозитория проекта')
    try:
        result=subprocess.run([curl_path(),'-qfsSL','--proto','=https','--proto-redir','=https',
                               '--noproxy','*','--connect-timeout','4','--max-time',str(timeout),
                               '--max-filesize',str(limit),url,'-o',str(destination)],
                              capture_output=True,timeout=timeout+3)
    except (OSError,subprocess.TimeoutExpired) as error:
        raise UpdateError('Сервер обновлений недоступен') from error
    if result.returncode or not Path(destination).is_file() or Path(destination).stat().st_size>limit:
        raise UpdateError('Не удалось скачать обновление')


def parse_manifest(document,current):
    if not isinstance(document,dict):raise UpdateError('Некорректный ответ сервера обновлений')
    latest=document.get('version')
    if version_tuple(latest)<=version_tuple(current):return None
    url=document.get('url')
    digest=document.get('sha256')
    size=document.get('size')
    if not trusted_url(url) or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):
        raise UpdateError('Некорректные адрес или SHA256 обновления')
    if not isinstance(size,int) or isinstance(size,bool) or not 1<=size<=MAX_ARCHIVE:
        raise UpdateError('Некорректный размер обновления')
    return Update(latest,url,digest,size)


def decline(update):
    DECLINED.add(update.version)



def check(root,fetch=download):
    with tempfile.TemporaryDirectory(prefix='tvpn-version-') as directory:
        manifest=Path(directory)/'version.json'
        fetch(MANIFEST_URL,manifest,limit=65536,timeout=5)
        try:document=json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError,ValueError) as error:raise UpdateError('Некорректный ответ сервера обновлений') from error
    return parse_manifest(document,local_version(root))


class Watcher:
    """Check at startup and hourly without blocking the UI or the tunnel."""
    def __init__(self,root,loader=None,interval=3600):
        self.loader=loader or (lambda:check(root))
        self.interval=max(60,interval)
        self._next=0
        self._thread=None
        self._results=queue.Queue()

    def poll(self):
        result=None
        while not self._results.empty():
            value,failed=self._results.get()
            self._next=time.monotonic()+(300 if failed else self.interval)
            if value is not None and value.version not in DECLINED:result=value
        if time.monotonic()>=self._next and (self._thread is None or not self._thread.is_alive()):
            self._next=time.monotonic()+self.interval
            def load():
                try:self._results.put((self.loader(),False))
                except Exception:self._results.put((None,True))
            self._thread=threading.Thread(target=load,daemon=True)
            self._thread.start()
        return result


def extract(archive,directory):
    directory=Path(directory)
    with zipfile.ZipFile(archive) as source:
        entries=source.infolist()
        if len(entries)>2000 or sum(e.file_size for e in entries)>MAX_EXPANDED:
            raise UpdateError('Архив обновления слишком большой')
        seen=set()
        for entry in entries:
            name=entry.orig_filename
            if name != entry.filename:
                raise UpdateError('Изменённый путь в архиве обновления')
            parts=PurePosixPath(name).parts
            mode=entry.external_attr>>16
            if (not parts or '\\' in name or ':' in name or name.startswith('/') or
                '..' in parts or any(p.casefold() in PROTECTED for p in parts) or
                stat.S_ISLNK(mode) or any(p.startswith('.') and p not in ('.github','.gitignore') for p in parts) or
                name.endswith(PRIVATE_SUFFIXES)):
                raise UpdateError('Недопустимый файл в архиве обновления')
            if entry.is_dir():continue
            if name.casefold() in seen:raise UpdateError('Повторяющийся путь в архиве')
            seen.add(name.casefold())
            dest=directory.joinpath(*parts)
            dest.parent.mkdir(parents=True,exist_ok=True)
            with source.open(entry) as data,dest.open('wb') as out:shutil.copyfileobj(data,out)
            dest.chmod(0o755 if mode&0o111 else 0o644)
    if not (directory/'VERSION').is_file() or not (directory/'riseup-panel.py').is_file():
        raise UpdateError('В архиве отсутствуют обязательные файлы')


def needs_helper_update(root,stage,platform):
    paths=(['platforms/macos/backend.sh','platforms/macos/dns-hook','platforms/macos/install.sh','riseup_regions.py','verify_exit.py','assets/riseup-ca.crt']
           if platform=='darwin' else ['Riseup-Amsterdam-SteamDeck.sh','install-passwordless.sh','riseup_regions.py','verify_exit.py']
           if platform.startswith('linux') else [])
    for name in paths:
        new,old=Path(stage)/name,Path(root)/name
        if new.is_file() and (not old.is_file() or new.read_bytes()!=old.read_bytes()):return True
    return False


def install_helper(stage,platform):
    if platform=='darwin':
        apple='on run argv\ndo shell script "/bin/bash " & quoted form of (item 1 of argv) & " " & quoted form of (item 2 of argv) with administrator privileges\nend run\n'
        account=subprocess.check_output(['id','-un'],text=True).strip()
        result=subprocess.run(['osascript','-',str(Path(stage)/'platforms/macos/install.sh'),account],input=apple,text=True)
    elif platform.startswith('linux'):
        result=subprocess.run(['pkexec','/bin/bash',str(Path(stage)/'install-passwordless.sh')])
    else:return
    if result.returncode:raise UpdateError('Системное обновление не разрешено или завершилось ошибкой')


def replace_files(root,stage,finalize=None):
    """Keep user data/venv; roll back every already-written file on a write error."""
    root,stage=Path(root).resolve(),Path(stage)
    with tempfile.TemporaryDirectory(prefix='.riseup-backup-',dir=root.parent) as backup:
        backup=Path(backup)
        changed=[]
        try:
            for path in sorted(stage.rglob('*')):
                if not path.is_file():continue
                relative=path.relative_to(stage)
                target=root/relative
                resolved=target.resolve()
                if not resolved.is_relative_to(root) or target.is_symlink():
                    raise UpdateError('Путь обновления ведёт за пределы установки')
                existed=target.exists()
                if existed:
                    saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
                target.parent.mkdir(parents=True,exist_ok=True)
                # Same filesystem as target, so a single file replacement is atomic.
                descriptor,temporary_name=tempfile.mkstemp(prefix='.update-new-',dir=target.parent)
                os.close(descriptor)
                temporary=Path(temporary_name)
                try:
                    shutil.copy2(path,temporary)
                    os.replace(temporary,target)
                finally:
                    temporary.unlink(missing_ok=True)
                changed.append((relative,existed))
            if finalize is not None:finalize()
        except BaseException:
            for relative,existed in reversed(changed):
                target=root/relative
                if existed:shutil.copy2(backup/relative,target)
                else:target.unlink(missing_ok=True)
            raise


def _apply_locked(update,root,fetch=download,helper=install_helper,platform=None):
    platform=sys.platform if platform is None else platform
    root=Path(root).resolve()
    lock=root/'.update.lock'
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as error:raise UpdateError('Обновление уже выполняется') from error
    os.close(fd)
    try:
        with tempfile.TemporaryDirectory(prefix='.riseup-update-',dir=root.parent) as directory:
            directory=Path(directory);archive=directory/'update.zip';stage=directory/'stage';stage.mkdir()
            fetch(update.url,archive,limit=MAX_ARCHIVE,timeout=180)
            if archive.stat().st_size!=update.size or hashlib.sha256(archive.read_bytes()).hexdigest()!=update.sha256:
                raise UpdateError('SHA256 или размер не совпадает; обновление отменено')
            extract(archive,stage)
            if local_version(stage)!=update.version:raise UpdateError('Версия архива не совпадает с манифестом')
            changed=needs_helper_update(root,stage,platform)
            # Upgrade the root guard first. Older installations cannot yet hold the
            # shared lock, but the privileged installer itself refuses an active backend.
            if changed:helper(stage,platform)
            with backend_idle():replace_files(root,stage)
    finally:lock.unlink(missing_ok=True)


def apply(update,root,fetch=download,helper=install_helper,platform=None):
    root=Path(root).resolve()
    with lifecycle(root):
        require_clean(root)
        return _apply_locked(update,root,fetch=fetch,helper=helper,platform=platform)


def restart(root,region):
    root=Path(root).resolve()
    if sys.platform=='darwin':
        os.execv('/bin/bash',['/bin/bash',str(root/'start-macos.command'),'--region',region])
    elif sys.platform=='win32':
        # execl replaces this Python process; cmd handles the installed venv launcher.
        os.execl(os.environ.get('COMSPEC',r'C:\Windows\System32\cmd.exe'),'cmd.exe','/c',str(root/'start-windows.cmd'),'--region',region)
    else:
        os.execv('/bin/bash',['/bin/bash',str(root/'Riseup-Amsterdam-SteamDeck.sh'),'--region',region])
