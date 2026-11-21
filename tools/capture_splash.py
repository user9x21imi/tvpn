#!/usr/bin/env python3
"""Linux preview capture through a real xterm, always --demo (no VPN)."""
import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]


def driver(args):
    import fcntl,pty,struct,termios
    master,slave=pty.openpty()
    size=os.get_terminal_size()
    fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',size.lines,size.columns,0,0))
    while not args.go.exists():time.sleep(.01)
    start=time.monotonic()
    command=[sys.executable,str(ROOT/'riseup-panel.py'),str(ROOT/'Riseup-Amsterdam-SteamDeck.sh'),'--demo']
    proc=subprocess.Popen(command,stdin=slave,stdout=slave,stderr=slave,start_new_session=True,
                          env=dict(os.environ,RISEUP_NO_UPDATE_CHECK='1',TERM='xterm-256color'))
    os.close(slave)
    with args.cast.open('w',encoding='utf-8') as out:
        out.write(json.dumps({'version':2,'width':size.columns,'height':size.lines,'timestamp':int(time.time()),'env':{'TERM':'xterm-256color'},'title':'TVPN offline terminal startup'})+'\n')
        stopped=False
        while proc.poll() is None:
            elapsed=time.monotonic()-start
            if elapsed>2.7 and not stopped:os.write(master,b'\x11');stopped=True
            if elapsed>5:proc.terminate()
            if select.select([master],[],[],.02)[0]:
                try:data=os.read(master,65536)
                except OSError:break
                out.write(json.dumps([round(elapsed,6),'o',data.decode('utf-8',errors='replace')],ensure_ascii=False)+'\n')
                os.write(sys.stdout.fileno(),data)
    proc.wait(timeout=5);os.close(master)


def capture(args):
    args.output.mkdir(parents=True,exist_ok=True)
    for name,geometry in [('wide','128x40'),('narrow','60x30')]:
        title='TVPN-preview-'+name+'-'+str(os.getpid())
        go=args.output/(name+'.go');go.unlink(missing_ok=True)
        cast=args.output/(name+'.cast')
        terminal=subprocess.Popen(['xterm','-hold','-T',title,'-geometry',geometry,
                                   '-fa','DejaVu Sans Mono','-fs','12','-bg','#11151b','-fg','#e4dfea',
                                   '-e',sys.executable,str(Path(__file__).resolve()),'--driver','--go',str(go),'--cast',str(cast)])
        window=None
        try:
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                found=subprocess.run(['xdotool','search','--name',title],capture_output=True,text=True)
                if found.returncode==0:window=found.stdout.splitlines()[-1];break
                time.sleep(.05)
            if not window:raise RuntimeError('Preview terminal did not appear')
            subprocess.run(['xdotool','windowmove',window,'120','80'],check=True)
            video=args.output/('startup-'+name+'.mp4')
            recorder=subprocess.Popen(['ffmpeg','-y','-loglevel','error','-f','x11grab','-framerate','25','-window_id',window,'-i',os.environ.get('DISPLAY',':0'),'-t','3.6','-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-c:v','libx264','-pix_fmt','yuv420p',str(video)])
            time.sleep(.35);go.touch();time.sleep(.64)
            subprocess.run(['ffmpeg','-y','-loglevel','error','-f','x11grab','-window_id',window,'-i',os.environ.get('DISPLAY',':0'),'-frames:v','1',str(args.output/('splash-'+name+'.png'))],check=True)
            recorder.wait(timeout=10)
            if recorder.returncode:raise RuntimeError('Terminal recording failed')
            go.unlink(missing_ok=True)
        finally:
            terminal.terminate()
            try:terminal.wait(timeout=3)
            except subprocess.TimeoutExpired:terminal.kill();terminal.wait()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--driver',action='store_true');parser.add_argument('--go',type=Path)
    parser.add_argument('--cast',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    driver(args) if args.driver else capture(args)
