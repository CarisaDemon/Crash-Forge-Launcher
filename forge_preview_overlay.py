"""Compact on-model markers with real screen projection and no edge-clamping.

Only an actual mount position gets a marker. Missing/offscreen anchors are
reported separately rather than being moved to fake coordinates at the edge.
Long cross-screen leader lines and multi-line coordinate clutter are avoided.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from types import SimpleNamespace

from PIL import ImageDraw, ImageFont
from forge_preview_rasterizer import _project

MAX_MARKERS = 14
try:
    _FONT = ImageFont.truetype(
        str(Path(os.environ.get("WINDIR","C:/Windows"))/"Fonts"/"segoeui.ttf"),12)
except OSError:
    _FONT = ImageFont.load_default()


def _format_coord(value):
    value = float(value)
    if abs(value) < .004:
        return "0"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _rotation_vector(rotation, length):
    rx, ry, rz = (math.radians(v) for v in rotation)
    x, y, z = 0., 0., -length
    y, z = y*math.cos(rx)-z*math.sin(rx), y*math.sin(rx)+z*math.cos(rx)
    x, z = x*math.cos(ry)+z*math.sin(ry), -x*math.sin(ry)+z*math.cos(ry)
    x, y = x*math.cos(rz)-y*math.sin(rz), x*math.sin(rz)+y*math.cos(rz)
    return (x, y, z)


def project_offset_markers(markers, width, height, *, yaw, pitch, zoom,
                           center, normalizer):
    """Projected true positions, never clamped to viewport or model geometry."""
    valid = []
    for marker in list(markers or ())[:MAX_MARKERS]:
        if not isinstance(marker,dict):
            continue
        pos=marker.get("position")
        if (not isinstance(pos,(tuple,list)) or len(pos)!=3):
            continue
        try:
            if not all(math.isfinite(float(v)) for v in pos):
                continue
        except (TypeError,ValueError,OverflowError):
            continue
        valid.append(marker)
    if not valid:
        return []
    pos=_project(SimpleNamespace(vertices=[m["position"] for m in valid]),
                 width,height,yaw,pitch,zoom,center,normalizer)
    result=[]
    for item,p in zip(valid,pos):
        x,y=float(p[0]),float(p[1])
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        result.append({**item,"screen":(x,y),
                       "visible":14<=x<=width-14 and 30<=y<=height-14})
    return result


def _overlap(a,b,space=3):
    return (a[0]<b[2]+space and a[2]+space>b[0] and
            a[1]<b[3]+space and a[3]+space>b[1])


def _label_candidates(x,y,w,h):
    # Very short stems (10-40 px) instead of cross-screen wires.
    for dist in (13,24,36,49):
        yield (x+dist,y-h-dist), (dist*dist+dist*dist)
        yield (x+dist,y+dist), (dist*dist+dist*dist)
        yield (x-dist-w,y-h-dist), (dist*dist+dist*dist)
        yield (x-dist-w,y+dist), (dist*dist+dist*dist)


def paint_offset_markers(image, markers, *, yaw, pitch, zoom, center,
                         normalizer, hovered=None, draw_rotation=True):
    if not markers:
        return image
    rendered=image.copy()
    draw=ImageDraw.Draw(rendered)
    width,height=rendered.size
    cam=dict(yaw=yaw,pitch=pitch,zoom=zoom,center=center,normalizer=normalizer)
    screen=project_offset_markers(markers,width,height,**cam)
    visible=[m for m in screen if m["visible"]]
    hidden=sum(1 for m in screen if not m["visible"])
    if hidden:
        message=f"{hidden} OFFSCREEN  /  FRAME OFFSETS"
        tw=draw.textbbox((0,0),message,font=_FONT)[2]
        x=max(8,width-tw-14)
        draw.rectangle((x-5,6,x+tw+5,24),fill=(11,21,31),
                       outline=(67,87,100))
        draw.text((x,10),message,font=_FONT,fill=(255,176,113))
    if not visible:
        return rendered

    # Coordinate label placement is independent of marker locations: the
    # center crosshair stays on the *real* projected mount.
    blocks=[]
    priority={"Exhaust":0,"Seat":1,"Wheels":2,"Model":3}
    sorted_markers=sorted(visible,key=lambda m:(priority.get(m.get("kind"),4),
                                                m["screen"][1]))
    for marker in sorted_markers:
        sx,sy=marker["screen"]
        name=marker.get("name","OFFSET")
        if name=="MODEL ORIGIN":
            name="ORIGIN"
        name=str(name)[:18]
        if marker.get("name")==hovered:
            name+="  "+"/".join(_format_coord(v) for v in marker.get("values",(0,0,0)))
        rect=draw.textbbox((0,0),name,font=_FONT)
        w,h=rect[2]-rect[0]+9,rect[3]-rect[1]+7
        chosen=None
        best=1e30
        for (x,y),distance2 in _label_candidates(sx,sy,w,h):
            box=(int(x),int(y),int(x+w),int(y+h))
            outside=(max(0,8-box[0])+max(0,box[2]-(width-8))+
                     max(0,33-box[1])+max(0,box[3]-(height-8)))
            collisions=sum(1 for old in blocks if _overlap(box,old,space=4))
            score=distance2+collisions*35000+outside*5000
            if score<best:
                chosen=box;best=score
                if score==distance2:
                    break
        if chosen is None:
            continue
        x,y,r,b=chosen
        # In the rare tiny-window case, omit the label rather than fake a
        # placement across the screen or move the 3D anchor.
        if x<4 or y<28 or r>width-4 or b>height-4:
            continue
        color=tuple(marker.get("color",(254,162,76)))
        blocks.append(chosen)
        corner=(x if x>sx else r, max(y,min(b,sy)))
        draw.line((sx,sy,*corner),fill=color,width=1)
        draw.rounded_rectangle(chosen,radius=3,fill=(10,20,30),
                               outline=(53,67,79),width=1)
        draw.text((x+5,y+3),name,fill=color,font=_FONT)

    for marker in visible:
        x,y=marker["screen"]
        color=tuple(marker.get("color",(255,171,80)))
        rotation=marker.get("rotation")
        if draw_rotation and rotation is not None:
            vector=_rotation_vector(rotation,max(.15,normalizer*.12))
            anchor=marker["position"]
            tip=tuple(anchor[i]+vector[i] for i in range(3))
            end=_project(SimpleNamespace(vertices=[tip]),width,height,**cam)[0]
            ex,ey=float(end[0]),float(end[1])
            if all(math.isfinite(v) for v in (ex,ey)):
                # Rotation rays are short and directly attached to the nozzle.
                dx,dy=ex-x,ey-y
                distance=max(1.,math.hypot(dx,dy))
                factor=min(1.,36./distance)
                ex,ey=x+dx*factor,y+dy*factor
                draw.line((x,y,ex,ey),fill=(9,20,30),width=5)
                draw.line((x,y,ex,ey),fill=color,width=2)
                direction=math.atan2(ey-y,ex-x)
                for side in (-.7,.7):
                    draw.line((ex,ey,ex-7*math.cos(direction+side),
                               ey-7*math.sin(direction+side)),fill=color,width=2)
        r=7 if marker.get("name")==hovered else 5
        draw.ellipse((x-r-1,y-r-1,x+r+1,y+r+1),
                     fill=(8,17,27),outline=(203,217,229),width=1)
        draw.ellipse((x-3,y-3,x+3,y+3),fill=color)
    return rendered