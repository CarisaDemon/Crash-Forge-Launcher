"""Animated, read-only previews for native CTR modular kart exhaust mounts.

Effects are deliberately illustrative (not game-sprite extraction), but their
launch coordinates and exhaust rotation use the game INI and VehTurbo's
local X/Y/Z Euler order. Effects never alter engine reserves or runtime mods.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

from PIL import Image, ImageDraw
from forge_preview_rasterizer import _project

MAX_ACTIVE_EXHAUSTS=4
_FX_FIRE=(255,116,36)
_FX_ARROW=(255,219,85)


def direction(rotation, length=1.0):
    """Game emitter's local (0,+Y,-Z), rotated X then Y then Z.

    VehEmitter.c initializes the exhaust velocity with Y=0x400,
    Z=-0x400. All preview arrows/effects share this orientation.
    """
    if rotation is None:
        rotation=(0.0,0.0,0.0)
    try:
        rx,ry,rz=(math.radians(float(v)) for v in rotation)
    except (ValueError,TypeError,OverflowError):
        rx=ry=rz=0.0
    unit=float(length)/math.sqrt(2.)
    x,y,z=0.,unit,-unit
    y,z=y*math.cos(rx)-z*math.sin(rx),y*math.sin(rx)+z*math.cos(rx)
    x,z=x*math.cos(ry)+z*math.sin(ry),-x*math.sin(ry)+z*math.cos(ry)
    x,y=x*math.cos(rz)-y*math.sin(rz),x*math.sin(rz)+y*math.cos(rz)
    return x,y,z


def _point(p, coords, cam, w, h):
    projection=_project(SimpleNamespace(vertices=[coords]),w,h,**cam)[0]
    px,py=float(projection[0]),float(projection[1])
    if not math.isfinite(px) or not math.isfinite(py):
        return None
    return (px,py)


def build_effect_particles(exhausts, *, time_s=0., normalizer=2.,
                           fire=False,smoke=False):
    """Return reproducible 3D animation particles anchored to each exhaust."""
    particles=[]
    normalizer=max(.1,float(normalizer))
    for nozzle_index,mark in enumerate(list(exhausts or ())[:MAX_ACTIVE_EXHAUSTS]):
        if mark.get("kind")!="Exhaust" or mark.get("rotation") is None:
            continue
        pos=mark["position"]
        vec=direction(mark["rotation"])
        # The flame preview, smoke preview and yellow arrow now share
        # VehEmitter's exact initial local vector (0,+Y,-Z).
        # Smoke gets extra buoyancy only after emission, not at the nozzle.
        smoke_dir=vec
        for kind,count,speed,scale in (
            (("fire",17,2.7,.36) if fire and nozzle_index<2 else ("fire",0,2.7,.36)),
            (("smoke",12,1.15,.58) if smoke else ("smoke",0,1.15,.58))):
            for i in range(count):
                seed=(i*.618033989+nozzle_index*.347+time_s*speed)%1.
                age=seed
                angular=math.sin(i*12.9898+nozzle_index*4.2)*.042
                jitter=math.cos(time_s*2.7+i*7.11)*.031
                width=normalizer*(angular+jitter)*(age+.15)
                drift=(age*.18*normalizer if kind=="smoke" else 0.)
                axis=vec if kind=="fire" else smoke_dir
                distance=normalizer*scale*age
                point=(pos[0]+axis[0]*distance+width,
                       pos[1]+axis[1]*distance+drift,
                       pos[2]+axis[2]*distance+width*.45)
                particles.append({"kind":kind,"position":point,
                                  "age":age,"nozzle":nozzle_index})
    return particles


def paint_exhaust_effects(image, exhausts, *, yaw,pitch,zoom,center,
                          normalizer, time_s=0.0, fire=False, smoke=False,
                          show_arrows=True):
    """Draw local effect previews and visible muzzle direction vectors."""
    if not exhausts or not (fire or smoke or show_arrows):
        return image
    width,height=image.size
    cam=dict(yaw=yaw,pitch=pitch,zoom=zoom,center=center,normalizer=normalizer)
    valid=[m for m in exhausts[:MAX_ACTIVE_EXHAUSTS]
           if m.get("kind")=="Exhaust" and m.get("rotation") is not None]
    if not valid:
        return image
    layer=Image.new("RGBA",(width,height),(0,0,0,0))
    draw=ImageDraw.Draw(layer,"RGBA")
    particles=build_effect_particles(valid,time_s=time_s,normalizer=normalizer,
                                    fire=fire,smoke=smoke)
    if particles:
        projected=_project(
            SimpleNamespace(vertices=[x["position"] for x in particles]),
            width,height,**cam)
        # Draw distant/old particles first; keep flame cores sharp.
        for part,p in sorted(zip(particles,projected),
                             key=lambda a:a[0]["age"],reverse=True):
            x,y=float(p[0]),float(p[1])
            if not (-20<x<width+20 and -20<y<height+20):
                continue
            age=part["age"]
            if part["kind"]=="smoke":
                rad=4+age*13
                alpha=int(90*(1-age)**1.2)
                for expand,aa in ((1.45,.24),(1,.7),(.72,1.)):
                    r=rad*expand
                    draw.ellipse((x-r,y-r,x+r,y+r),
                                 fill=(147,159,168,int(alpha*aa)))
            else:
                rad=3.2+(1-age)*3.0
                fade=max(.06,1.0-age**1.5)
                for expand,color,alpha in (
                    (2.0,(255,65,16),38),(1.3,(255,115,23),122),
                    (.78,(255,210,60),193),(.35,(255,249,190),240)):
                    r=rad*expand
                    draw.ellipse((x-r,y-r,x+r,y+r),
                                 fill=(*color,int(alpha*fade)))

    if show_arrows:
        for mark in valid:
            vec=direction(mark["rotation"],max(.22,normalizer*.32))
            p0=mark["position"]
            p1=tuple(p0[k]+vec[k] for k in range(3))
            start=_point(None,p0,cam,width,height)
            end=_point(None,p1,cam,width,height)
            if start is None or end is None:
                continue
            x,y=start
            ex,ey=end
            if not(-20<x<width+20 and -20<y<height+20):
                continue
            dist=math.hypot(ex-x,ey-y)
            if dist<3:
                # Direction perpendicular to screen: circle with center dot.
                draw.ellipse((x-12,y-12,x+12,y+12),outline=(*_FX_ARROW,240),width=3)
                draw.ellipse((x-2,y-2,x+2,y+2),fill=(255,254,180,255))
                continue
            scale=min(1.,66./dist)
            ex,ey=x+(ex-x)*scale,y+(ey-y)*scale
            angle=math.atan2(ey-y,ex-x)
            draw.line((x,y,ex,ey),fill=(7,14,23,240),width=7)
            draw.line((x,y,ex,ey),fill=(*_FX_ARROW,245),width=3)
            for side in (-.59,.59):
                draw.line((ex,ey,ex-11*math.cos(angle+side),
                           ey-11*math.sin(angle+side)),
                          fill=(*_FX_ARROW,250),width=3)
            draw.ellipse((x-3,y-3,x+3,y+3),fill=(252,250,169,255))
    return Image.alpha_composite(image.convert("RGBA"),layer).convert("RGB")