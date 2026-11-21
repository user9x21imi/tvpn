import curses
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import splash


class Screen:
    def __init__(self,w,h):self.w=w;self.h=h;self.erases=0;self.writes=0
    def getmaxyx(self):return self.h,self.w
    def erase(self):self.erases+=1
    def addnstr(self,y,x,text,n,attr):
        assert 0<=x<self.w-1 and 0<=y<self.h
        self.writes+=1
    def noutrefresh(self):pass


class SplashTests(unittest.TestCase):
    rows=[('Версия','1.3.1'),('Платформа','Linux / x86_64'),('Backend','OpenVPN / bundled x86_64')]
    def test_bounds_for_wide_narrow_tiny_and_resize(self):
        for w,h in [(128,40),(90,28),(60,30),(40,20),(28,14),(10,5),(2,2),(1,1),(0,0)]:
            frame=splash.frame(w,h,self.rows,.8)
            self.assertEqual(len(frame),h)
            self.assertTrue(all(len(row)==w for row in frame))
            self.assertTrue(all(not row or row[-1][0]==' ' for row in frame))
    def test_no_region_marker_or_connection_session_data(self):
        text='\n'.join(''.join(c for c,_ in row) for row in splash.frame(128,40,self.rows,.8))
        for secret in ('@','Подключено','192.','Амстердам','NL'):self.assertNotIn(secret,text)
        self.assertIn('Соединение начинается здесь',text)
    def test_motion_off_has_no_reveal_or_rotation(self):
        self.assertEqual(splash.frame(128,40,self.rows,0,False),splash.frame(128,40,self.rows,.9,False))
        self.assertNotEqual(splash.frame(128,40,self.rows,0),splash.frame(128,40,self.rows,.9))
    def test_skip_consumes_key_resize_is_not_skip_and_duration_is_one_second(self):
        now=[0.]
        with patch.object(curses,'init_pair'),patch.object(curses,'COLORS',256,create=True),patch.object(curses,'COLOR_PAIRS',256,create=True),patch.object(curses,'flushinp') as flush:
            intro=splash.Intro(self.rows,clock=lambda:now[0])
            self.assertFalse(intro.done(curses.KEY_RESIZE));self.assertFalse(intro.done(-1))
            self.assertTrue(intro.done(ord('r')));flush.assert_called_once()
            now[0]=1.01;self.assertTrue(intro.done(-1))
    def test_incremental_draw_default_background_and_resize(self):
        with patch.object(curses,'init_pair') as pair,patch.object(curses,'COLORS',256,create=True),patch.object(curses,'COLOR_PAIRS',256,create=True),patch.object(curses,'color_pair',side_effect=lambda x:x),patch.object(curses,'doupdate'):
            intro=splash.Intro(self.rows,motion=False)
            screen=Screen(128,40);intro.draw(screen);writes=screen.writes
            intro.draw(screen);self.assertEqual(screen.writes,writes);self.assertEqual(screen.erases,1)
            screen.w=60;screen.h=30;intro.draw(screen);self.assertEqual(screen.erases,2)
            self.assertTrue(all(call.args[-1]==-1 for call in pair.call_args_list))
    def test_missing_version_backend_are_omitted_without_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows=dict(splash.metadata(tmp,'/missing/backend'))
            self.assertNotIn('Версия',rows);self.assertNotIn('Backend',rows)


@unittest.skipUnless(sys.platform.startswith('linux'),'PTY terminal integration')
class StartupPTYTests(unittest.TestCase):
    def exercise(self,skip=False,no_splash=False,no_motion=False,resize=False,interrupt=False):
        import fcntl,pty,select,signal,struct,subprocess,termios,time
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',40,128,0,0))
        original=termios.tcgetattr(slave)
        # Any accidental backend/update subprocess in the preview is a test failure.
        script="""import runpy,sys
from unittest.mock import patch
sys.argv=[sys.argv[1],'--demo']+sys.argv[2:]
with patch('subprocess.Popen',side_effect=AssertionError('demo attempted a process')):
 runpy.run_path(sys.argv[0],run_name='__main__')
"""
        flags=(['--no-splash'] if no_splash else [])+(['--no-motion'] if no_motion else [])
        process=subprocess.Popen([sys.executable,'-c',script,str(ROOT/'riseup-panel.py'),*flags],stdin=slave,stdout=slave,stderr=slave,
                                 start_new_session=True,env=dict(os.environ,TERM='xterm-256color'))
        output=bytearray();began=time.monotonic();sent=False;resized=False;main_time=None
        try:
            deadline=began+4
            while time.monotonic()<deadline:
                if select.select([master],[],[],.01)[0]:
                    output.extend(os.read(master,65536))
                if (skip or interrupt) and not sent and 'Соединение начинается здесь'.encode() in output:
                    if interrupt:os.killpg(process.pid,signal.SIGINT)
                    else:os.write(master,b'r')
                    sent=True
                if resize and not resized and time.monotonic()-began>.4:
                    fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,45,0,0))
                    os.killpg(process.pid,signal.SIGWINCH);resized=True
                if 'VPN не запускался'.encode() in output:
                    main_time=time.monotonic()-began;break
            self.assertIsNotNone(main_time,output.decode(errors='replace')[-1500:])
            if skip or interrupt or no_splash:self.assertLess(main_time,.8)
            else:self.assertTrue(.8<=main_time<=1.5,main_time)
            self.assertNotIn('ВЫБОР БЕСПЛАТНОГО РЕГИОНА'.encode(),output)
            os.write(master,b'\x11')
            while process.poll() is None:
                if select.select([master],[],[],.02)[0]:os.read(master,65536)
                if time.monotonic()>deadline:raise AssertionError('Demo did not exit')
            self.assertEqual(process.returncode,0)
            self.assertEqual(termios.tcgetattr(slave),original)
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=3)
            os.close(master);os.close(slave)

    def test_auto_transition_without_any_network_or_backend(self):self.exercise()
    def test_skip_key_is_consumed(self):self.exercise(skip=True)
    def test_ctrl_c_is_consumed_during_intro(self):self.exercise(interrupt=True)
    def test_disabled_splash(self):self.exercise(no_splash=True)
    def test_resize_and_reduced_motion_restore_terminal(self):self.exercise(no_motion=True,resize=True)
