#!/usr/bin/env python3
"""Unprivileged terminal UI for the bundled Riseup backend (standard library)."""
import collections
import curses
import ipaddress
import os
import queue
import re
import signal
import subprocess
import sys
import threading
try:
    import termios
except ImportError:  # Windows uses windows-curses and console input modes.
    termios = None
import time
from pathlib import Path

LABELS = {'catalog': 'ПОЛУЧЕНИЕ СПИСКА ШЛЮЗОВ', 'certificate': 'ПОЛУЧЕНИЕ СЕРТИФИКАТА', 'connecting': 'ПОДКЛЮЧЕНИЕ…',
          'verifying': 'ПРОВЕРКА ВЫХОДА', 'connected': 'ПОДКЛЮЧЕНО',
          'disconnecting': 'ОСТАНОВКА ТУННЕЛЯ', 'fallback': 'ПРОБУЮ РЕЗЕРВНЫЙ ШЛЮЗ', 'error': 'ОШИБКА', 'off': 'ОТКЛЮЧЕНО'}
sys.path.insert(0, str(Path(__file__).resolve().parent))
from riseup_regions import REGIONS
from stoped_title import render as stoped_render
from world_map import render as world_render, position as world_position
REGION_KEYS = list(REGIONS)


def safe(text):
    return ''.join(c for c in text if c.isprintable())[:500]


class Model:
    def __init__(self, selected='amsterdam'):
        self.interface = 'riseupvpn0'
        self.selected = selected
        self.expected = REGIONS[selected]['country']
        self.state = 'connecting'
        self.detail = 'Подготовка туннеля'
        self.gateway = self.city = self.ip = self.region = '—'
        self.city = REGIONS[selected]['city']
        self.since = None
        self.logs = collections.deque(maxlen=120)
        self.hidden = False
        self.last = None
        self.rx = self.tx = self.down = self.up = 0
        self.history = collections.deque(maxlen=60)
        self.cleanup = False

    def line(self, line):
        if line.startswith('@RISEUP\t'):
            fields = line.rstrip('\n').split('\t') + ['', '', '', '']
            kind, a, b, c = fields[1:5]
            if kind == 'state':
                self.state, self.detail = a, safe(b)
                if a == 'error' and self.logs and b.startswith('Ошибка подключения'):
                    self.detail = self.logs[-1][:120]
                if a != 'connected':
                    self.since = None
                    self.ip = self.region = '—'
            elif kind == 'detail':
                self.detail = safe(b)
            elif kind == 'location':
                if a in REGIONS and c == REGIONS[a]['country']:
                    self.selected, self.expected, self.city = a, c, safe(b)
            elif kind == 'interface':
                if a and len(a) < 128 and a == safe(a):
                    self.interface = a
            elif kind == 'gateway':
                self.gateway, self.city = safe(a), safe(b)
                self.last = None
                self.rx = self.tx = self.down = self.up = 0
                self.history.clear()
            elif kind == 'connected':
                try:
                    ipaddress.ip_address(a)
                except ValueError:
                    return
                if b == self.expected:
                    self.state, self.ip, self.region = 'connected', a, b
                    self.since = time.monotonic()
                    self.detail = f'HTTPS через {self.interface}: регион {b} подтверждён'
                    self.last = None
                    self.history.clear()
            elif kind == 'cleanup':
                self.cleanup = a == 'ok'
            return
        # Never display PEM bodies, control sequences, or file contents.
        if '-----BEGIN ' in line:
            self.hidden = True
        elif '-----END ' in line:
            self.hidden = False
        elif not self.hidden and not re.fullmatch(r'[A-Za-z0-9+/=]{40,}', line.strip()):
            value = safe(line.strip())
            if value:
                self.logs.append(value)
                if self.state == 'error':
                    self.detail = value[:100]

    def sample(self, now=None, root=None):
        now = time.monotonic() if now is None else now
        try:
            if root is not None or sys.platform.startswith('linux'):
                root = root or Path('/sys/class/net')/self.interface/'statistics'
                rx, tx = (int((root / name).read_text()) for name in ('rx_bytes', 'tx_bytes'))
            else:
                import psutil
                counters = psutil.net_io_counters(pernic=True, nowrap=False)[self.interface]
                rx, tx = counters.bytes_recv, counters.bytes_sent
        except (OSError, ValueError, KeyError, ImportError):
            self.last = None
            self.down = self.up = 0
            return
        if self.last is None or rx < self.last[1] or tx < self.last[2]:
            self.base = (rx, tx)
            self.history.clear()
            self.down = self.up = 0
        elif now > self.last[0]:
            dt = now - self.last[0]
            self.down = (rx - self.last[1]) / dt / 2**20
            self.up = (tx - self.last[2]) / dt / 2**20
            self.history.append((now, self.down, self.up))
        self.rx, self.tx = rx - self.base[0], tx - self.base[1]
        self.last = (now, rx, tx)
        while self.history and self.history[0][0] < now - 60:
            self.history.popleft()


def volume(n):
    return f'{n / 2**30:.2f} ГиБ' if n >= 2**30 else f'{n / 2**20:.1f} МиБ'


def graph(history, index, width):
    count = min(60, max(1, width))
    buckets = [[] for _ in range(count)]
    if history:
        end = history[-1][0]
        for sample in history:
            age = end - sample[0]
            if 0 <= age < 60:
                bucket = min(count - 1, int((60 - age) / 60 * count))
                buckets[bucket].append(sample[index])
    values = [max(bucket) if bucket else None for bucket in buckets]
    peak = max((v for v in values if v is not None), default=0)
    bars = ''.join(' ' if v is None else
                   '▁▂▃▄▅▆▇█'[min(7, int(v / peak * 7))] if peak else
                   (' ' if v is None else '▁') for v in values)
    return bars, peak


def draw(screen, m, journal, ended, choosing=None):
    screen.erase()
    height, width = screen.getmaxyx()
    def put(y, x, text, color=0, bold=False):
        if 0 <= y < height and 0 <= x < width - 1:
            try:
                screen.addnstr(y, x, text, width - x - 1,
                               curses.color_pair(color) | (curses.A_BOLD if bold else 0))
            except curses.error:
                pass
    color = 2 if m.state == 'connected' else 3 if m.state == 'error' else 4
    put(1, 2, 'R I S E U P   /   W O R L D W I D E', 1, True)
    put(3, 2, '● ' + LABELS.get(m.state, m.state), color, True)
    put(4, 2, m.detail)
    if journal:
        put(6, 2, 'ПОСЛЕДНИЕ СТРОКИ ЖУРНАЛА', 1, True)
        for y, line in enumerate(list(m.logs)[-max(1, height - 11):], 8):
            put(y, 2, line)
    else:
        # Let STOPED occupy the full map area, including on a wide Deck window.
        wide = width >= 120 and m.state != 'off'
        map_width = max(12, width - 46 if wide else width - 4)
        map_height = max(6, min(24, height - (18 if wide else 25)))
        preview = REGION_KEYS[choosing] if choosing is not None else m.selected
        target = REGIONS[preview]
        map_color = 2 if m.state == 'connected' and preview == m.selected else 4
        if m.state == 'off' and choosing is None:
            banner = stoped_render(map_width, map_height)
            top = 6 + max(0, (map_height-len(banner))//2)
            for offset, line in enumerate(banner):
                put(top+offset, 2+max(0, (map_width-len(line))//2), line, 3, True)
            put(6+map_height, 2, 'Туннель остановлен · Ctrl+S — подключить', 5)
        else:
            for row_number, row in enumerate(world_render(map_width, map_height, target['country']), 6):
                start, previous, segment = 0, None, ''
                for column, (char, highlight) in enumerate(row):
                    color_here = map_color if highlight else 6
                    if previous is not None and color_here != previous:
                        put(row_number, 2+start, segment, previous)
                        start, segment = column, ''
                    segment += char
                    previous = color_here
                put(row_number, 2+start, segment, previous or 6)
            px, py = world_position(target['lon'], target['lat'], map_width, map_height)
            put(6+py, 2+px, '@', map_color, True)
            put(6+map_height, 2, '@ ' + target['city'] + ' / ' + target['country'] +
                (' · выход подтверждён' if m.state == 'connected' and preview == m.selected else ' · выбрано'), map_color)
        x, y = (map_width+5, 7) if wide else (2, 6+map_height+2)
        duration = int(time.monotonic() - m.since) if m.since else 0
        timer = f'{duration//3600:02}:{duration//60%60:02}:{duration%60:02}' if m.since else '—'
        rows = [('Локация', m.city), ('Регион выхода', m.region), ('Внешний IP', m.ip),
                ('Шлюз', m.gateway), ('Сессия', timer), ('Интерфейс', m.interface),
                ('Точка @', f'выход {m.region} подтверждён' if m.state == 'connected' else 'выбранная локация')]
        spacing = 2 if wide and height >= 36 else 1
        for i, (label, value) in enumerate(rows):
            put(y+i*spacing, x, f'{label:<15} {value}', 0, i == 2)
        y = max(7 + map_height, y + len(rows)*spacing) + 1
        for index, name, rate, total in [(1, '↓', m.down, m.rx), (2, '↑', m.up, m.tx)]:
            bars, peak = graph(m.history, index, max(1, width-28))
            put(y, 2, f'{name} {rate:7.2f} МиБ/с    Всего {volume(total)}', index, True)
            put(y+1, 2, bars, index)
            put(y+2, 2, f'Последняя минута · пик {peak:.2f} МиБ/с', 5)
            y += 4
        if y > height-1:
            put(height-3, 2, 'Увеличьте окно / уменьшите шрифт для карты и графиков', 4)
    put(height-2, 2, '[R] Регион  [L] Журнал  ' + ('[Ctrl+S] Подключить  [Q] Выход' if ended else '[Ctrl+S] Остановить'), 5)
    if choosing is not None:
        box_width = min(width-4, 66)
        left = max(1, (width-box_width)//2)
        top = max(5, (height-13)//2)
        lines = ['ВЫБОР БЕСПЛАТНОГО РЕГИОНА · RISEUP', '',
                 *[('  › ' if index == choosing else '    ') + f"{info['city']:<18} {info['country']}"
                   for index, info in enumerate(REGIONS.values())], '',
                 '↑/↓ выбрать · Enter подключить · Esc отменить',
                 'Адреса шлюзов загружаются из каталога Riseup.',
                 'Текущее соединение сначала будет закрыто.']
        for offset, line in enumerate(lines):
            put(top+offset, left, line.ljust(box_width)[:box_width],
                4 if offset == choosing+2 else 5, offset == choosing+2 or offset == 0)
    screen.refresh()


def run(script, selected='amsterdam'):
    m, messages = Model(selected), queue.Queue()
    # Backend owns sudo, certificate acquisition and all network cleanup.
    command = [sys.executable if script.endswith('.py') else '/bin/bash', script,
               '--text', '--events', '--region', selected]
    process = subprocess.Popen(command, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, bufsize=1)
    def reader():
        for line in process.stdout:
            messages.put(line)
        messages.put(None)
    threading.Thread(target=reader, daemon=True).start()
    def request_stop():
        if process.poll() is not None:
            return
        if sys.platform == 'win32':
            try:
                process.stdin.write('stop\n')
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
        else:
            process.send_signal(signal.SIGINT)
    closing = False
    def stop(signum=None, frame=None):
        nonlocal closing
        # Ctrl+C also stops in place; TERM/HUP and explicit exit close the UI.
        closing = closing or signum != signal.SIGINT
        # Same foreground process group: backend also receives terminal Ctrl+C.
        if process.poll() is None:
            request_stop()
    old = {sig: signal.signal(sig, stop) for sig in dict.fromkeys((signal.SIGINT, signal.SIGTERM, getattr(signal, 'SIGHUP', signal.SIGTERM)))}
    def ui(screen):
        if termios is not None:
            modes = termios.tcgetattr(sys.stdin.fileno())
            modes[0] &= ~(termios.IXON | termios.IXOFF)
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, modes)
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        for i, c in enumerate([curses.COLOR_CYAN, curses.COLOR_GREEN, curses.COLOR_RED,
                               curses.COLOR_YELLOW, curses.COLOR_WHITE, curses.COLOR_BLUE], 1):
            curses.init_pair(i, c, curses.COLOR_BLACK)
        screen.bkgd(' ', curses.color_pair(5))
        screen.timeout(100)
        curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED)
        journal, ended, sampled = False, False, 0
        choosing, next_region, pausing = None, None, False
        while True:
            while not messages.empty():
                line = messages.get()
                if line is None:
                    ended = True
                    if process.wait() not in (0, 130, 143, -2) or not m.cleanup:
                        m.state = 'error'
                        if m.logs:
                            m.detail = m.logs[-1]
                    elif m.state != 'error':
                        m.state, m.detail = 'off', 'Туннель остановлен; DNS восстановлен'
                        m.ip = m.region = '—'
                        m.since = m.last = None
                        m.down = m.up = 0
                        m.history.clear()
                    pausing = False
                else:
                    m.line(line)
            now = time.monotonic()
            if not ended and now - sampled >= 1:
                m.sample(now)
                sampled = now
            draw(screen, m, journal, ended, choosing)
            if ended and next_region is not None:
                if m.cleanup:
                    return next_region
                m.state, m.detail = 'error', 'Переключение отменено: восстановление сети не подтверждено'
                next_region = None
            if closing and ended:
                return
            key = screen.getch()
            if key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, buttons = curses.getmouse()
                    sh, sw = screen.getmaxyx()
                    top = max(5, (sh-13)//2)
                    left = max(1, (sw-min(sw-4, 66))//2)
                    if buttons & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED):
                        if choosing is None and my == sh-2 and 2 <= mx < 13:
                            key = ord('r')
                        elif choosing is not None and left <= mx < left+min(sw-4, 66) and top+2 <= my < top+8:
                            choosing = my-top-2
                            key = 10
                except curses.error:
                    pass
            if choosing is not None:
                if key in (curses.KEY_UP, ord('k')):
                    choosing = (choosing-1) % len(REGION_KEYS)
                elif key in (curses.KEY_DOWN, ord('j')):
                    choosing = (choosing+1) % len(REGION_KEYS)
                elif key in (10, 13, curses.KEY_ENTER):
                    next_region = REGION_KEYS[choosing]
                    choosing = None
                    if not ended:
                        m.detail = 'Восстановление сети перед сменой региона…'
                        request_stop()
                elif key in (27, ord('r'), ord('R')):
                    choosing = None
                continue
            if key == 19:  # Ctrl+S, with terminal XON/XOFF disabled.
                if ended:
                    if m.cleanup:
                        return m.selected
                    m.detail = 'Повторный запуск запрещён: восстановление сети не подтверждено'
                elif not pausing:
                    pausing = True
                    m.state, m.detail = 'disconnecting', 'Останавливаю туннель и восстанавливаю сеть…'
                    request_stop()
                continue
            if key in (ord('r'), ord('R')):
                choosing = REGION_KEYS.index(m.selected)
            if key in (ord('l'), ord('L')):
                journal = not journal
            if ended and key in (ord('q'), ord('Q'), 10, 27):
                return
    terminal_modes = termios.tcgetattr(sys.stdin.fileno()) if termios is not None else None
    try:
        # Keep the normal terminal available while sudo asks for its password.
        while True:
            line = messages.get()
            if line is None:
                process.wait()
                return process.returncode
            if line.startswith('@RISEUP\t'):
                m.line(line)
                break
            print(line, end='', flush=True)
        next_selected = curses.wrapper(ui)
    finally:
        if process.poll() is None:
            stop()
            process.wait()  # Never kill the backend before its cleanup finishes.
        process.stdin.close()
        if termios is not None and terminal_modes is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, terminal_modes)
        for sig, handler in old.items():
            signal.signal(sig, handler)
    if next_selected is not None:
        return next_selected
    print('RiseupVPN: ' + LABELS.get(m.state, m.state) + '. ' + m.detail)
    return 1 if m.state == 'error' else 0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('script')
    parser.add_argument('--region', choices=REGION_KEYS, default='amsterdam')
    options = parser.parse_args()
    result = options.region
    while isinstance(result, str):
        result = run(options.script, result)
    raise SystemExit(result)
