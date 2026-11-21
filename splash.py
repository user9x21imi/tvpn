"""Terminal-only introduction: original globe geometry, no network/session data."""
import curses
import math
import os
from pathlib import Path
import platform
import sys
import time
from globe import render as render_globe

DURATION=1.0


def metadata(root,backend=None):
    rows=[]
    try:
        version=(Path(root)/'VERSION').read_text(encoding='utf-8').strip()
        if version and len(version)<24:rows.append(('Версия',version))
    except OSError:pass
    machine=platform.machine()
    rows.append(('Платформа',{'linux':'Linux','darwin':'macOS','win32':'Windows'}.get(sys.platform,sys.platform)+(' / '+machine if machine else '')))
    if backend and Path(backend).is_file():
        if sys.platform.startswith('linux') and machine=='x86_64' and Path(backend).name=='Riseup-Amsterdam-SteamDeck.sh':
            rows.append(('Backend','OpenVPN / bundled x86_64'))
        elif sys.platform=='darwin' and Path('/Library/PrivilegedHelperTools/riseup-vpn-panel/backend.sh').is_file():
            rows.append(('Backend','OpenVPN / macOS helper'))
        elif sys.platform=='win32' and (Path(os.environ.get('ProgramFiles','C:/Program Files'))/'OpenVPN/bin/openvpn-gui.exe').is_file():
            rows.append(('Backend','OpenVPN / Interactive Service'))
    return rows


def frame(width,height,rows,elapsed=0.,motion=True,unicode=True):
    """Return a bounded character canvas (role 0=text, 1=accent, 2=muted)."""
    canvas=[[(' ',0) for _ in range(max(0,width))] for _ in range(max(0,height))]
    if width<2 or height<2:return canvas
    def put(x,y,text,role=0):
        if 0<=y<height:
            for i,char in enumerate(text):
                if 0<=x+i<width-1:canvas[y][x+i]=(char,role)
    wide=width>=104 and height>=22
    graphic=width>=40 and height>=20
    left=4 if width>=65 else 2 if width>=20 else 0
    if wide:
        box=(width//2,2,width-width//2-3,height-6)
        top=max(2,(height-17)//2)
    else:
        top=2 if height>=12 else 0
        box=(left,12,width-left*2,max(0,height-16))
    if wide:
        title=['TTTTT V   V PPPP  N   N','  T   V   V P   P NN  N','  T   V   V PPPP  N N N','  T    V V  P     N  NN','  T     V   P     N   N']
        for y,line in enumerate(title):put(left,top+y,line,1)
    else:put(left,top,'TVPN',1)
    tagline_y=top+(7 if wide else 2)
    if height>=8 and width>=34:put(left,tagline_y,'Соединение начинается здесь')
    label_width=max((len(label) for label,_ in rows),default=0)
    for index,(label,value) in enumerate(rows):
        line=f'{label:<{label_width}}  {value}'
        row_y=top+(10 if wide else 5)+index
        if height>=12 and row_y<height-5:
            if len(line)<width-left-1:put(left,row_y,line)
            elif len(value)<width-left-1:put(left,row_y,value)
    if wide or graphic:
        x0,y0,w,h=box
        if w>=18 and h>=4:
            image=[[(' ',0) for _ in range(w)] for _ in range(h)]
            orbit={}
            for tilt in (-.62,.55):
                steps=max(320,w*12)
                for n in range(steps):
                    angle=n*2*math.pi/steps
                    u,v=.97*math.cos(angle),.28*math.sin(angle)
                    nx=(1+u*math.cos(tilt)-v*math.sin(tilt))/2
                    ny=(1+u*math.sin(tilt)+v*math.cos(tilt))/2
                    if unicode:
                        sx,sy=round(nx*(w*2-1)),round(ny*(h*4-1))
                        x,y=sx//2,sy//4
                        bit=((0,1,2,6),(3,4,5,7))[sx%2][sy%4]
                        if 0<=x<w and 0<=y<h:orbit[(x,y)]=orbit.get((x,y),0)|(1<<bit)
                    else:
                        x,y=round(nx*(w-1)),round(ny*(h-1))
                        if 0<=x<w and 0<=y<h:orbit[(x,y)]=1
            for (x,y),bits in orbit.items():image[y][x]=(chr(0x2800+bits) if unicode else '.',2)
            sphere=render_globe(w,h,20,-27+(elapsed*5 if motion else 0),'',zoom=.69)
            from globe import size
            rx,ry=size(w,h,.69)
            for y,row in enumerate(sphere):
                for x,cell in enumerate(row):
                    inside=((x-(w-1)/2)/rx)**2+((y-(h-1)/2)/ry)**2<=1
                    if inside:image[y][x]=(' ',0)
                    if cell.char!=' ':
                        char=cell.char
                        if unicode and cell.role==2:char={'.':'·',':':'░','+':'▒','=':'▒','*':'▓','#':'▓'}.get(char,char)
                        image[y][x]=(char,1 if cell.role==2 else 2)
            reveal=min(1.,elapsed/.38) if motion else 1.
            for y,row in enumerate(image):
                for x,(char,role) in enumerate(row):
                    if char!=' ' and (not motion or ((x*37+y*19)%97)/97<=reveal):put(x0+x,y0+y,char,role)
    if height>=6:
        line_y=height-4
        put(left,line_y,('─' if unicode else '-')*max(0,width-left*2-1),2)
        hint='Любая клавиша — перейти' if width>=36 else 'Клавиша — далее' if width>=20 else 'TVPN'
        put(left,height-2,hint,2)
    return canvas


class Intro:
    def __init__(self,rows,motion=True,unicode=True,clock=time.monotonic):
        self.clock=clock;self.started=clock();self.rows=rows;self.motion=motion;self.unicode=unicode
        self.previous=None
        # Default terminal background, including transparency. No palette mutation.
        self.pairs={0:0,1:0,2:0}
        try:
            colors=curses.COLORS
            for pair,fg in ((7,141 if colors>=256 else curses.COLOR_MAGENTA),(8,103 if colors>=256 else curses.COLOR_MAGENTA)):
                if pair<curses.COLOR_PAIRS:curses.init_pair(pair,fg,-1);self.pairs[pair-6]=pair
        except curses.error:pass

    def draw(self,screen):
        height,width=screen.getmaxyx()
        current=frame(width,height,self.rows,self.clock()-self.started,self.motion,self.unicode)
        changed=self.previous is None or len(self.previous)!=height or (not self.previous or len(self.previous[0])!=width)
        if changed:screen.erase()  # Only first frame and resize, never every animation tick.
        for y,row in enumerate(current):
            for x,(char,role) in enumerate(row):
                if x>=width-1:continue
                if changed or row[x]!=self.previous[y][x]:
                    attr=curses.color_pair(self.pairs[role]) | (curses.A_BOLD if role==1 else curses.A_DIM if role==2 else 0)
                    try:screen.addnstr(y,x,char,1,attr)
                    except curses.error:pass
        screen.noutrefresh();curses.doupdate();self.previous=current

    def done(self,key):
        if key not in (-1,curses.KEY_RESIZE):
            curses.flushinp()  # Discard queued input; skip never reaches the main menu.
            return True
        return self.clock()-self.started>=DURATION
