"""Dependency-free orthographic ASCII Earth with an animated orbit camera.

Geometry is Natural Earth, public domain. Projection and camera are original
TVPN code; the globe-cli project is a UX reference, not a runtime dependency.
"""
import functools
import math
import time
from typing import NamedTuple
from world_map import land,COUNTRIES


class Cell(NamedTuple):
    char:str
    role:int=0  # 0 sky, 1 sea/limb, 2 land, 3 selected country, 4 city marker


def wrap(longitude):return (longitude+180)%360-180


@functools.lru_cache(maxsize=1)
def texture():
    width,height=720,360
    pixels=[bytearray(width) for _ in range(height)]
    ids={}
    for number,feature in enumerate(land(),1):
        ids[feature['id']]=number
        polygons=feature['coordinates'] if feature['type']=='MultiPolygon' else [feature['coordinates']]
        for rings in polygons:
            edges=[(a,b) for ring in rings for a,b in zip(ring,ring[1:]) if a[1]!=b[1]]
            if not edges:continue
            south=min(p[1] for ring in rings for p in ring);north=max(p[1] for ring in rings for p in ring)
            first=max(0,int((90-north)/180*height)-1);last=min(height,int((90-south)/180*height)+2)
            for y in range(first,last):
                latitude=90-(y+.5)/height*180
                crossings=sorted(a[0]+(latitude-a[1])*(b[0]-a[0])/(b[1]-a[1]) for a,b in edges if (a[1]>latitude)!=(b[1]>latitude))
                for west,east in zip(crossings[::2],crossings[1::2]):
                    start=max(0,math.ceil((west+180)/360*width-.5));end=min(width,math.ceil((east+180)/360*width-.5))
                    pixels[y][start:end]=bytes([number])*max(0,end-start)
    return pixels,ids


def size(width,height,zoom=1):
    radius=max(.5,min((height-1)/2,(width-2)/4))*zoom
    return radius*2,radius


def project(latitude,longitude,cam_lat,cam_lon,width,height,zoom=1):
    lat,center,delta=map(math.radians,(latitude,cam_lat,wrap(longitude-cam_lon)))
    facing=math.sin(center)*math.sin(lat)+math.cos(center)*math.cos(lat)*math.cos(delta)
    if facing<=0:return None
    x=math.cos(lat)*math.sin(delta)
    y=math.cos(center)*math.sin(lat)-math.sin(center)*math.cos(lat)*math.cos(delta)
    rx,ry=size(width,height,zoom)
    px,py=round((width-1)/2+rx*x),round((height-1)/2-ry*y)
    return (px,py) if 0<=px<width and 0<=py<height else None


def render(width,height,latitude,longitude,country,zoom=1,location=None):
    pixels,ids=texture();selected=ids.get(COUNTRIES.get(country,''),-1)
    rx,ry=size(width,height,zoom);phi,theta=map(math.radians,(latitude,longitude))
    sp,cp,st,ct=math.sin(phi),math.cos(phi),math.sin(theta),math.cos(theta)
    def surface(x,y):
        nx=(x-(width-1)/2)/rx;ny=((height-1)/2-y)/ry;r2=nx*nx+ny*ny
        if r2>1:return None
        nz=math.sqrt(max(0,1-r2))
        wx=-nx*st-ny*sp*ct+nz*cp*ct
        wy=nx*ct-ny*sp*st+nz*cp*st
        wz=ny*cp+nz*sp
        lat=math.degrees(math.asin(max(-1,min(1,wz))));lon=math.degrees(math.atan2(wy,wx))
        tx=min(719,max(0,int((lon+180)/360*720)));ty=min(359,max(0,int((90-lat)/180*360)))
        return pixels[ty][tx],nx,ny,nz,lat,lon
    rows=[]
    for y in range(height):
        row=[]
        for x in range(width):
            center=surface(x,y)
            if center is None:row.append(Cell(' '));continue
            identity,nx,ny,nz,lat,lon=center
            samples=[surface(x+dx,y+dy) for dx,dy in ((-.25,-.25),(.25,-.25),(-.25,.25),(.25,.25))]
            if any(sample and sample[0]==selected for sample in samples):
                row.append(Cell('.',3));continue
            solid=sum(bool(sample and sample[0]) for sample in samples)
            if solid:
                light=max(0,min(1,-nx*.25+ny*.15+nz*.9))
                char='.:+=*#'[min(5,int(light*5))] if solid>=3 else ':' if solid==2 else '.'
                row.append(Cell(char,2))
            else:
                grid=min(abs((lat+15)%30-15),abs((lon+15)%30-15))<1.2
                row.append(Cell('.' if nz<.30 else ':' if grid else ' ',1))
        rows.append(row)
    if location:
        marker=project(location[0],location[1],latitude,longitude,width,height,zoom)
        if marker:rows[marker[1]][marker[0]]=Cell('@',4)
    return rows


class Camera:
    def __init__(self):
        self.latitude=18.;self.longitude=-35.;self.zoom=1.
        self.target=None;self.region=None;self.spinning=False;self.box=None
        self.last=time.monotonic()

    def focus(self,latitude,longitude):
        self.target=(max(-80,min(80,latitude)),wrap(longitude))
        self.spinning=False

    def select(self,region,latitude,longitude):
        if self.region!=region:
            self.region=region
            self.focus(latitude,longitude)

    def tick(self,now=None):
        now=time.monotonic() if now is None else now
        dt=max(0,min(.15,now-self.last));self.last=now
        if self.spinning:
            self.longitude=wrap(self.longitude+dt*12)
        elif self.target:
            latitude,longitude=self.target
            amount=1-math.exp(-dt*5)
            self.latitude+=(latitude-self.latitude)*amount
            self.longitude=wrap(self.longitude+wrap(longitude-self.longitude)*amount)
            if abs(latitude-self.latitude)<.02 and abs(wrap(longitude-self.longitude))<.02:
                self.latitude,self.longitude=latitude,longitude
                self.target=None

    def pan(self,latitude,longitude):
        self.target=None;self.spinning=False
        self.latitude=max(-80,min(80,self.latitude+latitude))
        self.longitude=wrap(self.longitude+longitude)

    def scale(self,factor):
        self.zoom=max(.65,min(2.5,self.zoom*factor))

    def toggle(self):
        self.target=None
        self.spinning=not self.spinning

    def contains(self,x,y):
        return bool(self.box and self.box[0]<=x<self.box[0]+self.box[2] and
                    self.box[1]<=y<self.box[1]+self.box[3])
