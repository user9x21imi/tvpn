#!/usr/bin/env python3
"""User-mode bridge to the official OpenVPN GUI / Interactive Service on Windows."""
import argparse
import ctypes
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from riseup_regions import REGIONS, normalize

PROFILE = 'RiseupVPN-Panel'
STOP = threading.Event()


class Stopped(Exception):
    pass


def event(kind, a='', b='', c=''):
    values = [str(v).replace('\n', ' ').replace('\r', ' ').replace('\t', ' ') for v in (kind,a,b,c)]
    print('@RISEUP\t'+'\t'.join(values), flush=True)


def check_stop():
    if STOP.is_set():
        raise Stopped()


def powershell(code):
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
                            capture_output=True, text=True, encoding='utf-8', timeout=15)
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:180])
    return result.stdout.strip()


def tunnel_route():
    raw = powershell("[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
                     "$r=@(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/1' -ErrorAction SilentlyContinue); "
                     "if($r.Count -eq 1){$r[0]|Select-Object InterfaceIndex,InterfaceAlias|ConvertTo-Json -Compress}")
    if not raw:
        return None
    route = json.loads(raw)
    return int(route['InterfaceIndex']), route['InterfaceAlias']


def local_address(index):
    value = powershell(f"(Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex {int(index)} | "
                       "Where-Object {$_.IPAddress -notlike '169.254.*'} | Select-Object -First 1).IPAddress")
    return str(ipaddress.IPv4Address(value))


def make_profile(host, address, proto, port, directory):
    # All endpoint values come from the strict provider-catalog normalizer.
    def path(name):
        return str(directory/name).replace('\\', '/')
    return f'''client
dev tun
windows-driver wintun
proto {proto}
remote {address} {port}
nobind
connect-retry-max 1
connect-timeout 8
hand-window 15
auth SHA512
data-ciphers AES-256-GCM
tls-cipher TLS-ECDHE-ECDSA-WITH-AES-256-GCM-SHA384
tls-version-min 1.2
remote-cert-tls server
verify-x509-name {host} name
ca "{path('riseup-ca.crt')}"
cert "{path('client.pem')}"
key "{path('client.pem')}"
pull-filter ignore redirect-gateway
pull-filter ignore ifconfig-ipv6
redirect-gateway def1 ipv6
ifconfig-ipv6 fd42:6760:5255::2/64 fd42:6760:5255::1
block-ipv6
block-outside-dns
writepid "{path('openvpn.pid')}"
verb 3
'''


class Backend:
    def __init__(self, selected):
        self.selected = selected
        self.info = REGIONS[selected]
        self.started = False
        self.index = None
        self.pid = None
        self.directory = self.log = None
        self.lock = None
        self.owns_lock = False
        self.gui = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))/'OpenVPN/bin/openvpn-gui.exe'
        self.curl = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/curl.exe'

    def command(self, action):
        subprocess.run([str(self.gui), '--command', action, PROFILE] if action != 'rescan' else
                       [str(self.gui), '--command', 'rescan'], check=True, timeout=15)

    def fetch(self, endpoint, output):
        for port in (4430, 443):
            for address in ('198.252.153.67', '198.252.153.106'):
                check_stop()
                event('detail', 'certificate' if endpoint == 'cert' else 'catalog', f'Riseup {address}:{port} · до 12 с')
                args = [str(self.curl), '-q4fsS', '--noproxy', '*', '--resolve',
                        f'api.black.riseup.net:{port}:{address}', '--connect-timeout', '6', '--max-time', '12']
                if port == 4430:
                    args += ['--cacert', str(self.directory/'riseup-ca.crt')]
                args += [f'https://api.black.riseup.net:{port}/3/{endpoint}', '-o', str(output)]
                result = subprocess.run(args, capture_output=True, timeout=15)
                if result.returncode == 0:
                    return
                print(result.stderr.decode(errors='replace').strip()[:300], flush=True)
        raise RuntimeError('Riseup не ответил после четырёх попыток')

    def setup(self):
        if sys.platform != 'win32':
            raise RuntimeError('Этот backend предназначен для Windows')
        if not self.gui.exists():
            raise RuntimeError('Установите OpenVPN Community с GUI и Interactive Service')
        import winreg
        values = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\OpenVPN-GUI') as key:
                for name in ('config_dir', 'log_dir'):
                    try: values[name] = os.path.expandvars(winreg.QueryValueEx(key, name)[0])
                    except OSError: pass
        except OSError:
            pass
        base = Path(values.get('config_dir', str(Path.home()/'OpenVPN/config')))
        self.log = Path(values.get('log_dir', str(Path.home()/'OpenVPN/log')))/(PROFILE+'.log')
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.directory = base/PROFILE
        if self.directory.exists() and not (self.directory/'.panel-owned').exists():
            raise RuntimeError('Одноимённый профиль уже существует; переименуйте его в OpenVPN GUI')
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory/'.panel-owned').touch()
        self.lock = self.directory/'panel.lock'
        fd = os.open(self.lock, os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        os.close(fd)
        self.owns_lock = True
        if tunnel_route() is not None:
            raise RuntimeError('Сначала отключите другой VPN с маршрутами 0.0.0.0/1')
        # Current user's profile only; remove inherited ACLs that could expose the key.
        identity = powershell('[Security.Principal.WindowsIdentity]::GetCurrent().Name')
        subprocess.run(['icacls.exe', str(self.directory), '/inheritance:r', '/grant:r',
                        identity+':(OI)(CI)F', 'SYSTEM:(OI)(CI)F'], check=True, capture_output=True)
        shutil.copy2(ROOT/'assets/riseup-ca.crt', self.directory/'riseup-ca.crt')
        event('location', self.selected, self.info['city'], self.info['country'])
        event('state', 'catalog', 'Получение списка шлюзов')
        inventory = self.directory/'gateways.json'
        self.fetch('config/eip-service.json', inventory)
        gateways = normalize(json.loads(inventory.read_text()), self.selected)
        if not gateways:
            raise RuntimeError('Нет публичных OpenVPN-шлюзов выбранного города')
        event('state', 'certificate', 'Получение сертификата')
        certificate = self.directory/'client.pem'
        self.fetch('cert', certificate)
        text = certificate.read_text()
        if '-----BEGIN CERTIFICATE-----' not in text or not re.search(r'-----BEGIN (RSA )?PRIVATE KEY-----', text):
            raise RuntimeError('Сервер не выдал корректный сертификат')
        subprocess.Popen([str(self.gui), '--silent_connection', '1'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(.8)
        return gateways

    def stopped_pid(self):
        if self.pid is None:
            pidfile = self.directory/'openvpn.pid'
            if pidfile.exists():
                self.pid = int(pidfile.read_text().strip())
        if self.pid is None:
            return False
        import psutil
        return not psutil.pid_exists(self.pid)

    def disconnect(self):
        if not self.started:
            return True
        self.command('disconnect')
        until = time.monotonic()+30
        while time.monotonic() < until:
            if self.stopped_pid():
                # Interactive Service owns DNS/routes and undoes them at process exit.
                route = tunnel_route()
                if route is None or self.index is None or route[0] != self.index:
                    self.started = False
                    self.index = self.pid = None
                    return True
            time.sleep(.2)
        return False

    def connect(self, gateway):
        host, address, proto, port, city, country = gateway
        check_stop()
        (self.directory/(PROFILE+'.ovpn')).write_text(make_profile(host,address,proto,port,self.directory))
        self.log.write_text('')
        (self.directory/'openvpn.pid').unlink(missing_ok=True)
        self.pid = self.index = None
        event('gateway', host, city, address)
        event('state', 'connecting', 'Подключение через OpenVPN Interactive Service')
        self.command('rescan')
        self.started = True
        self.command('connect')
        until = time.monotonic()+40
        while time.monotonic() < until:
            check_stop()
            text = self.log.read_text(errors='replace') if self.log.exists() else ''
            if 'Initialization Sequence Completed' in text:
                route = tunnel_route()
                if route is None:
                    raise RuntimeError('OpenVPN не установил маршруты туннеля')
                self.index, alias = route
                local = local_address(self.index)
                event('interface', alias)
                event('state', 'verifying', 'Проверка выхода через '+alias)
                for checker in ('1.1.1.1', '1.0.0.1'):
                    check_stop()
                    result = subprocess.run([str(self.curl), '-q4fsS', '--noproxy', '*', '--interface', local,
                                             '--connect-timeout','5','--max-time','8', f'https://{checker}/cdn-cgi/trace'],
                                            capture_output=True, text=True, timeout=11)
                    trace = dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
                    try: public = str(ipaddress.IPv4Address(trace.get('ip','')))
                    except ValueError: continue
                    if result.returncode == 0 and trace.get('loc') == country:
                        event('connected', public, country)
                        return True
                return False
            if 'Exiting due to fatal error' in text:
                print('\n'.join(text.splitlines()[-12:]), flush=True)
                return False
            STOP.wait(.2)
        return False

    def run(self):
        code = 0
        try:
            gateways = self.setup()
            for number, gateway in enumerate(gateways):
                if number:
                    event('state', 'fallback', 'Пробую резервный шлюз')
                if self.connect(gateway):
                    while not STOP.wait(.5):
                        if self.stopped_pid():
                            raise RuntimeError('OpenVPN неожиданно завершился')
                    break
                if not self.disconnect():
                    raise RuntimeError('Остановка предыдущего OpenVPN не подтверждена')
            else:
                raise RuntimeError('Ни один шлюз не прошёл HTTPS-проверку страны')
        except Stopped:
            pass
        except Exception as error:
            event('state', 'error', str(error)[:200])
            code = 1
        finally:
            try:
                if self.disconnect():
                    if self.directory and self.owns_lock:
                        for name in ('client.pem', PROFILE+'.ovpn', 'openvpn.pid', 'gateways.json'):
                            (self.directory/name).unlink(missing_ok=True)
                    event('cleanup', 'ok')
                else:
                    event('state', 'error', 'OpenVPN не остановлен; отключите профиль в OpenVPN GUI')
                    code = 1
            except Exception as error:
                event('state', 'error', 'Ошибка остановки: '+str(error)[:160])
                code = 1
            if self.lock and self.owns_lock:
                self.lock.unlink(missing_ok=True)
        return code


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--text',action='store_true')
    parser.add_argument('--events',action='store_true')
    parser.add_argument('--region',choices=list(REGIONS),default='amsterdam')
    options=parser.parse_args()
    signal.signal(signal.SIGINT,lambda *_: STOP.set())
    signal.signal(signal.SIGTERM,lambda *_: STOP.set())
    def commands():
        for line in sys.stdin:
            if line.strip() == 'stop': STOP.set(); return
        STOP.set()
    threading.Thread(target=commands,daemon=True).start()
    raise SystemExit(Backend(options.region).run())
