"""Original CTR effect assets recovered from the user's retail disc (local QA).

Turbo: all eight retail 3D animation meshes/MTLs/UVs from shared.mpk.
fireSize=8 gives the largest real turbo matrix scale (8/8 == 1).
Smoke: retail dustpuff/smokering artwork animated using the high-LOD exhaust
five-tick lifespan parameters. The OpenGL viewport now ports the actual
emitter axis equations from game source, using a native-resolution smoke quad.
A simplified 2D sprite projection is retained ONLY on computers without GL.
"""
from __future__ import annotations

from functools import lru_cache
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
from forge_preview_rasterizer import _project

ASSETS=Path(__file__).resolve().parent / "preview_original_ctr_fx"
TURBO_FRAME_COUNT=8
TURBO_FIRE_SIZE=8
NATIVE_SMOKE_HI_LIFESPAN=5
ORIGINAL_FPS=30
SMOKE_FRAME_COUNT=5
# Particle velocity, acceleration, scale, color and 30Hz lifetime come from
# forge_preview_ctr_particle.py (a documented port of native game code).


def rotation_matrix(degrees):
    """Local X then Y then Z: same matrix order as VehTurbo_BuildLocalRotation."""
    rx,ry,rz=(math.radians(float(v)) for v in degrees)
    sx,cx=math.sin(rx),math.cos(rx)
    sy,cy=math.sin(ry),math.cos(ry)
    sz,cz=math.sin(rz),math.cos(rz)
    return np.asarray([
        [cz*cy,cz*sy*sx-sz*cx,cz*sy*cx+sz*sx],
        [sz*cy,sz*sy*sx+cz*cx,sz*sy*cx-cz*sx],
        [-sy,cy*sx,cy*cx]
    ],dtype=np.float32)


def frame_index(time_s,nozzle=0):
    # VehTurbo.c advances one frame per legacy 30Hz tick; other outlet +3.
    return (int(max(0.0,float(time_s))*ORIGINAL_FPS)+(3 if nozzle==1 else 0))&7


def _material_images(path):
    found={}
    if not path.is_file():
        return found
    name=None
    for line in path.read_text(encoding="utf-8",errors="replace").splitlines():
        line=line.strip()
        if line.startswith("newmtl "):
            name=line.split(None,1)[1].strip()
        elif line.startswith("map_Kd ") and name:
            rel=Path(line.split(None,1)[1].strip().replace("\\","/"))
            if rel.is_absolute() or ".." in rel.parts:
                continue
            image=(path.parent/rel).resolve()
            if image.is_relative_to(path.parent.resolve()) and image.is_file():
                found[name]=image
    return found


@lru_cache(maxsize=1)
def load_retail_turbo_frames():
    """Tuple[frame] of (path|None, float32 contiguous triangle vertex records).

    Every vertex stores x/y/z, texture u/v, original r/g/b. No simplification:
    all of the recovered retail OBJ triangles are preserved.
    """
    frames=[]
    for i in range(TURBO_FRAME_COUNT):
        stem="turbo" if i==0 else f"turbo{i}"
        sub=ASSETS/stem
        name="turbo.turbo0.00" if i==0 else f"{stem}.{stem}.00"
        path=sub/(name+".obj")
        if not path.is_file():
            return ()
        materials=_material_images(sub/(name+".mtl"))
        vertices=[]
        texcoords=[]
        triangles={}
        active=""
        for row in path.read_text(encoding="utf-8",errors="replace").splitlines():
            bits=row.strip().split()
            if not bits:
                continue
            op=bits[0]
            if op=="v" and len(bits)>=4:
                xyz=[float(x) for x in bits[1:4]]
                rgb=[float(x) for x in bits[4:7]] if len(bits)>=7 else [1.,1.,1.]
                vertices.append(xyz+rgb)
            elif op=="vt" and len(bits)>=3:
                texcoords.append([float(bits[1]),float(bits[2])])
            elif op=="usemtl" and len(bits)>=2:
                active=" ".join(bits[1:])
            elif op=="f" and len(bits)>=4:
                indices=[]
                for spec in bits[1:]:
                    index=spec.split("/")
                    vi=int(index[0])-1
                    ui=int(index[1])-1 if len(index)>1 and index[1] else -1
                    indices.append((vi,ui))
                key=materials.get(active)
                tri=triangles.setdefault(key,[])
                for k in range(1,len(indices)-1):
                    for vi,ui in (indices[0],indices[k],indices[k+1]):
                        xyzrgb=vertices[vi]
                        uv=texcoords[ui] if 0<=ui<len(texcoords) else (0.,0.)
                        tri.append([*xyzrgb[:3],*uv,*xyzrgb[3:6]])
        batch=[]
        for tex,rows in triangles.items():
            array=np.ascontiguousarray(rows,dtype=np.float32)
            if len(array):
                batch.append((tex,array))
        if not batch:
            return ()
        frames.append(tuple(batch))
    return tuple(frames)


@lru_cache(maxsize=1)
def load_retail_smoke_textures():
    """User's retail VRM dust puffs, with black pixels made transparent."""
    result=[]
    for i in range(SMOKE_FRAME_COUNT):
        path=ASSETS/f"dustpuff{i:02d}.png"
        if not path.is_file():
            return ()
        with Image.open(path) as file:
            # CTR-tools extracted original PSX CLUT transparency correctly.
            # Keep the native alpha instead of reconstructing it from RGB.
            result.append(file.convert("RGBA"))
    return tuple(result)


def paint_retail_smoke(image,exhausts,*,yaw,pitch,zoom,center,normalizer,time_s):
    """Native exhaust emSet_High physics, CPU-only perspective fallback.

    The OpenGL path renders the exact 3D quadrilateral from
    forge_preview_ctr_particle. On computers without GL3.3, project each
    native quad to a 2D bounding region, keeping the original tick clock,
    scale, color axis and group 1 icon 0. Only the quad's 2D orientation
    and blend resolution are simplified by the fallback.
    """
    from forge_preview_ctr_particle import native_smoke_vertex_data
    coords=native_smoke_vertex_data(
        exhausts,time_s,yaw=yaw,pitch=pitch,
        center=center,normalizer=normalizer)
    if coords.size==0:
        return image
    icon_set=load_retail_smoke_textures()
    if not icon_set:
        return image
    w,h=image.size
    vertices=_project(SimpleNamespace(vertices=coords[:,:3]),w,h,
                      yaw=yaw,pitch=pitch,zoom=zoom,
                      center=center,normalizer=normalizer)
    output=np.asarray(image.convert("RGB"),dtype=np.uint8).copy()
    source=icon_set[0]  # iconGroup[1] has NO animated axis10, never cycle
    for i in range(0,len(vertices),6):
        corners=vertices[[i,i+1,i+2,i+4],:2]
        left=max(0,int(np.floor(np.min(corners[:,0]))))
        top=max(0,int(np.floor(np.min(corners[:,1]))))
        right=min(w,int(np.ceil(np.max(corners[:,0]))))
        bottom=min(h,int(np.ceil(np.max(corners[:,1]))))
        if right<=left or bottom<=top:
            continue
        shade=float(coords[i,5])
        icon=source.resize((right-left,bottom-top),Image.Resampling.BILINEAR)
        values=np.asarray(icon,dtype=np.float32)
        alpha=values[:,:,3:4]*(shade/255.0)
        rgb=output[top:bottom,left:right].astype(np.float32)
        output[top:bottom,left:right]=np.clip(
            rgb+values[:,:,:3]*alpha,0,255).astype(np.uint8)
    return Image.fromarray(output,"RGB")