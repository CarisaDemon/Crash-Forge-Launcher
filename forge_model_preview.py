"""Crash Forge native 3D preview for Character / Kart / Wheels / Track.

This is an isolated, read-only software viewport. No GPU hooks, game input,
file mutation or Blender installation required. OBJ shows MTL/UV material
colors, with optional replacement texture. CTR LEV uses its REAL quad blocks
and hi-detail vertex colors (VRM imagery is not decoded in this preview).
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from pathlib import Path
import struct
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw
from forge_preview_rasterizer import render_scene, MAX_WIDTH, MAX_HEIGHT
from forge_preview_fast import render_fast
from forge_preview_gpu import GpuPreviewRenderer
from forge_preview_exhaust_fx import paint_exhaust_effects
from forge_preview_retail_fx import frame_index, paint_retail_smoke
from forge_preview_ctr_particle import NATIVE_TICKS_PER_SECOND
from forge_preview_overlay import paint_offset_markers, project_offset_markers

MAX_SOURCE_SIZE = 70 * 1024 * 1024
MAX_VERTICES = 150000
MAX_TRIANGLES = 14000
MAX_RENDER_TRIANGLES = 8000
MAX_TEXTURES = 24

class PreviewError(ValueError):
    pass

@dataclass
class Scene:
    vertices: list
    faces: list                 # (v0, v1, v2, uv0, uv1, uv2, material)
    uvs: list
    textures: dict              # key -> path
    colors: list                # per-vertex RGB, for LEV
    kind: str
    source: str
    description: str


def _safe_image_path(folder, raw):
    name = str(raw).strip().strip('"').replace("\\", "/")
    if not name or name.startswith("/") or ":" in name or ".." in Path(name).parts:
        return None
    try:
        path=(folder / name).resolve()
        if path.is_relative_to(folder.resolve()) and path.is_file() and (
                path.suffix.lower() in (".png", ".bmp", ".jpg", ".jpeg", ".tga")):
            return path
    except (OSError, ValueError):
        return None
    return None


def load_obj(path):
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".obj":
        raise PreviewError("Select a native .OBJ model for a 3D preview.")
    if path.stat().st_size > MAX_SOURCE_SIZE:
        raise PreviewError("OBJ exceeds the safe preview size (70 MiB).")
    verts, uvs, faces = [], [], []
    mtllibs, textures = [], {}
    material = ""
    with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
        for row in stream:
            line = row.strip()
            if not line or line.startswith("#"): continue
            parts = line.split()
            kind = parts[0]
            try:
                if kind == "v" and len(parts) >= 4:
                    if len(verts) >= MAX_VERTICES:
                        raise PreviewError("Too many vertices in OBJ.")
                    pos=tuple(float(x) for x in parts[1:4])
                    if all(math.isfinite(x) for x in pos):
                        verts.append(pos)
                elif kind == "vt" and len(parts) >= 3 and len(uvs) <= MAX_VERTICES*2:
                    uv=tuple(float(x) for x in parts[1:3])
                    uvs.append(uv if all(math.isfinite(x) for x in uv) else (0.,0.))
                elif kind == "mtllib":
                    mtllibs.extend(parts[1:3])
                elif kind == "usemtl":
                    material=" ".join(parts[1:])
                elif kind == "f" and len(parts) >= 4:
                    pairs=[]
                    for vertex in parts[1:]:
                        values=vertex.split("/")
                        vi=int(values[0])
                        vi=vi-1 if vi>0 else len(verts)+vi
                        if not 0 <= vi < len(verts):raise ValueError()
                        uv=None
                        if len(values)>1 and values[1]:
                            uv_i=int(values[1])
                            uv_i=uv_i-1 if uv_i>0 else len(uvs)+uv_i
                            if 0<=uv_i<len(uvs):uv=uv_i
                        pairs.append((vi,uv))
                    for i in range(1,len(pairs)-1):
                        if len(faces) >= MAX_TRIANGLES:break
                        group=(pairs[0],pairs[i],pairs[i+1])
                        faces.append((group[0][0],group[1][0],group[2][0],
                                      group[0][1],group[1][1],group[2][1],material))
            except (ValueError, IndexError):
                continue
    if not verts or not faces:raise PreviewError("OBJ must include vertices and faces.")
    for mtl_name in mtllibs[:5]:
        mtl=_safe_image_path(path.parent, mtl_name)
        # The MTL is a text file, checked separately from allowed image types.
        if mtl is None and mtl_name and ".." not in Path(mtl_name).parts:
            candidate=(path.parent/mtl_name).resolve()
            if candidate.is_relative_to(path.parent.resolve()) and candidate.suffix.lower()==".mtl" and candidate.is_file():
                mtl=candidate
        if mtl is None or mtl.suffix.lower()!=".mtl":continue
        current=""
        with mtl.open("r",encoding="utf-8-sig",errors="replace") as stream:
            for row in stream:
                line=row.strip()
                if line.startswith("newmtl "):
                    current=line[7:].strip()
                elif line.startswith("map_Kd ") and current:
                    candidate=_safe_image_path(path.parent,line[7:].strip())
                    if candidate and len(textures)<MAX_TEXTURES:
                        textures[current]=candidate
    return Scene(verts,faces,uvs,textures,[],"OBJ",str(path),
                 str(len(verts))+" vertices / "+str(len(faces))+
                 " triangles / "+str(len(textures))+" textures")


def load_ctr_lev(path):
    """Read-only CTR LEV preview using its mesh pointer, vertices, quad blocks.

    Pointers are offsets relative to the 4-byte LEV container prefix. All
    untrusted offsets/counts are bounded before dereference. Does NOT validate
    collision, checkpoints, materials, or gameplay registration.
    """
    path=Path(path)
    if not path.is_file() or path.suffix.lower()!=".lev":
        raise PreviewError("Select a native .LEV scene.")
    if not 4096<=path.stat().st_size<=128*1024*1024:
        raise PreviewError("LEV must be 4 KiB to 128 MiB.")
    data=path.read_bytes()
    size=len(data)
    base=4
    struct_size=struct.unpack_from("<I",data,0)[0]&0x7fffffff
    if struct_size<256 or struct_size>size-base:
        raise PreviewError("Invalid LEV main structure length.")
    mesh_ptr=struct.unpack_from("<I",data,base)[0]
    pos=base+mesh_ptr
    if mesh_ptr<64 or pos+32>size:
        raise PreviewError("Cannot locate CTR LEV mesh header.")
    nq,nv,_unknown,q_ptr,v_ptr,_other,_bsp_ptr,_bsp_count=struct.unpack_from("<IIIIIIII",data,pos)
    if not (0<nq<=150000 and 0<nv<=MAX_VERTICES):
        raise PreviewError("LEV mesh contains no supported quads/vertices.")
    vpos=base+v_ptr
    qpos=base+q_ptr
    if (v_ptr<64 or q_ptr<64 or vpos+nv*16>size or qpos+nq*92>size):
        raise PreviewError("LEV mesh arrays are invalid or use an unsupported pointer format.")
    verts=[]
    colors=[]
    for i in range(nv):
        x,y,z,flag,b,g,r,alpha=struct.unpack_from("<hhhHBBBB",data,vpos+i*16)
        verts.append((float(x),float(-y),float(z)))
        colors.append((r,g,b))
    faces=[]
    step=max(1,math.ceil(nq/(MAX_TRIANGLES//8)))
    for i in range(0,nq,step):
        idx=struct.unpack_from("<9H",data,qpos+i*92)
        if any(x>=nv for x in idx):
            continue
        # CTR's nine-index quad grid has four mid-level tiles.
        # Each quad becomes two preview triangles; this is *not* a
        # physics or collision reconstruction.
        for a,b,c,e in ((0,1,4,3),(1,2,5,4),(3,4,7,6),(4,5,8,7)):
            faces.append((idx[a],idx[b],idx[c],None,None,None,""))
            faces.append((idx[a],idx[c],idx[e],None,None,None,""))
    if not faces:raise PreviewError("LEV quad blocks contain no valid visible geometry.")
    return Scene(verts,faces,[],{},colors,"LEV",str(path),
                 str(nq)+" quad blocks / "+str(nv)+" vertices / "+
                 str(len(faces))+" preview triangles (vertex colors)")


def model_sources_from_folder(folder, category="Character"):
    root=Path(folder)
    if not root.is_dir():return []
    ext=".lev" if category=="Track" else ".obj"
    files=sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.lower()==ext),
                 key=lambda p:(len(p.relative_to(root).parts),p.name.casefold()))
    return files[:20]


def texture_sources_from_folder(folder):
    root=Path(folder)
    if not root.is_dir():return []
    return sorted((p for p in root.rglob("*") if p.is_file() and
                   p.suffix.lower() in (".png",".bmp",".jpg",".jpeg",".tga")),
                  key=lambda p:p.name.casefold())[:48]


class PreviewPane(ttk.Frame):
    """Small, reusable interactive 3D viewer for any importer/packager form."""
    def __init__(self, parent, *, width=610, height=315, category="Character"):
        super().__init__(parent)
        self.width=width
        self.height=height
        self.scene=None
        self.yaw=.7
        self.pitch=.42
        self.zoom=1.0
        self.center=(0.,0.,0.)
        self.normalizer=1.
        self._scheduled=None
        self._drag=None
        self._preview_photo=None
        self._texture_images={}
        self.texture_override=None
        self._base_image=None
        self._base_signature=None
        self.offset_markers=()
        self.exhaust_markers=()
        self.preview_fire=False
        self.preview_smoke=False
        self.preview_arrows=True
        self._fx_job=None
        self._fx_start=time.monotonic()
        self._gpu_renderer=None
        self._gpu_failed=False
        self._hovered_name=None
        self._idle_render_job=None
        self._interactive_until=0.
        self._detail_original=""
        self.category=category
        self.detail=tk.StringVar(value="Select an OBJ model or LEV track for preview.")
        # Resizable viewport; the outer PanedWindow sash controls its height.
        # No fixed 232px cap or photo-induced Tk geometry feedback.
        outer=tk.Frame(self,bg="#121820",height=self.height,
                       highlightthickness=1,highlightbackground="#444B54")
        outer.pack(fill="both",expand=True)
        outer.pack_propagate(False)
        self.image=tk.Label(outer,bg="#0c141c",fg="#ffac73",text="3D PREVIEW\nSELECT FILE")
        self.image.pack(fill="both",expand=True,padx=3,pady=3)
        self.image.bind("<ButtonPress-1>",self._down)
        self.image.bind("<B1-Motion>",self._move)
        self.image.bind("<ButtonRelease-1>",self._up)
        self.image.bind("<Motion>",self._hover)
        self.image.bind("<Leave>",self._clear_hover)
        self.image.bind("<MouseWheel>",self._wheel)
        self.image.bind("<Button-4>",self._wheel_linux)
        self.image.bind("<Button-5>",self._wheel_linux)
        self.image.bind("<Configure>",self._configure)
        controls=tk.Frame(self,bg="#121820")
        controls.pack(fill="x")
        tk.Label(controls,text="DRAG ROTATE  •  WHEEL ZOOM",
                 bg="#121820",fg="#ff8c34",font=("Segoe UI",8)).pack(side="left")
        tk.Button(controls,text="RESET",command=self.reset,
                  bg="#30363F",fg="white",relief="flat",padx=12).pack(side="right")
        tk.Label(self,textvariable=self.detail,fg="#ACB5BE",
                 bg="#121820",anchor="w",wraplength=width,
                 font=("Segoe UI",8)).pack(fill="x")
    def _configure(self,event):
        if event.width>30 and event.height>30:
            self.width=event.width
            self.height=event.height
            self._schedule()
    def load(self, path, *, category=None, texture_override=None):
        if category:self.category=category
        try:
            path=Path(path)
            parsed=load_ctr_lev(path) if path.suffix.lower()==".lev" else load_obj(path)
            self.scene=parsed
            self._base_image=None
            self._base_signature=None
            self.texture_override=Path(texture_override) if texture_override else None
            self._texture_images.clear()
            self._fit()
            self._detail_original=parsed.kind+" • "+parsed.description
            self.detail.set(self._detail_original)
            self._hovered_name=None
            self._schedule()
            return True
        except (OSError,ValueError,struct.error) as exc:
            self.scene=None
            self.image.configure(image="",text=str(exc)[:170])
            self.detail.set("Preview unavailable: "+str(exc)[:140])
            return False
    def set_variant(self,texture):
        self.texture_override=Path(texture) if texture else None
        self._base_image=None
        self._schedule()
    def set_markers(self, markers):
        # Lightweight overlays: no need to reload OBJ, textures or triangles.
        self.offset_markers=tuple(markers or ())
        self._schedule()

    def set_exhaust_preview(self, markers, *, fire=False, smoke=False,
                            arrows=True):
        self.exhaust_markers=tuple(markers or ())
        self.preview_fire=bool(fire) and bool(self.exhaust_markers)
        self.preview_smoke=bool(smoke) and bool(self.exhaust_markers)
        self.preview_arrows=bool(arrows)
        if self.preview_fire or self.preview_smoke:
            if self._fx_job is None:
                self._fx_start=time.monotonic()
                self._fx_job=self.after(33,self._animate_effects)
        elif self._fx_job is not None:
            self.after_cancel(self._fx_job)
            self._fx_job=None
        self._schedule()

    def _animate_effects(self):
        self._fx_job=None
        if not self.winfo_exists():
            return
        if self.scene and (self.preview_fire or self.preview_smoke):
            # Repaint only the lightweight effect overlay while camera is idle.
            self._schedule()
        if self.preview_fire or self.preview_smoke:
            self._fx_job=self.after(33,self._animate_effects)
    def _set_frame_bounds(self, points, padding=1.0):
        bounds=[(min(v[k] for v in points),max(v[k] for v in points))
                for k in range(3)]
        self.center=tuple((a+b)*.5 for a,b in bounds)
        self.normalizer=(max((b-a for a,b in bounds),default=1) or 1.)*padding
    def _fit(self):
        self.reset()
    def reset(self):
        if self.scene:
            self._set_frame_bounds(self.scene.vertices)
        self.yaw=.7
        self.pitch=.45
        self.zoom=1
        self._schedule()
    def frame_markers(self):
        # An explicit view command so distant exhaust markers can be seen
        # without making the model tiny by default.
        if not self.scene:
            return
        points=list(self.scene.vertices)
        points.extend(marker["position"] for marker in self.offset_markers)
        exhaust=getattr(self,"exhaust_markers",())
        if exhaust and (getattr(self,"preview_arrows",False) or
                        getattr(self,"preview_fire",False) or
                        getattr(self,"preview_smoke",False)):
            points.extend(marker["position"] for marker in exhaust)
        self._set_frame_bounds(points,padding=1.18)
        self.zoom=.82
        self._schedule()
    def _down(self,e):
        self._drag=(e.x,e.y)
        self._interactive_until=time.monotonic()+.25
        self._cancel_idle_render()

    def _move(self,e):
        if self._drag is None:
            return
        dx,dy=e.x-self._drag[0],e.y-self._drag[1]
        if dx==0 and dy==0:
            return
        self._drag=(e.x,e.y)
        self.yaw+=dx*.012
        self.pitch=max(-1.45,min(1.45,self.pitch+dy*.012))
        self._interactive_until=time.monotonic()+.18
        self._schedule()

    def _up(self,e=None):
        self._drag=None
        self._interactive_until=time.monotonic()+.10
        self._request_idle_render()

    def _cancel_idle_render(self):
        if self._idle_render_job is not None:
            self.after_cancel(self._idle_render_job)
            self._idle_render_job=None

    def _request_idle_render(self):
        self._cancel_idle_render()
        self._idle_render_job=self.after(190,self._settle)

    def _settle(self):
        self._idle_render_job=None
        if self.scene and self.winfo_exists() and self._drag is None:
            self._interactive_until=0.
            self._schedule()

    def _zoom(self,factor):
        self.zoom=max(.23,min(6,self.zoom*factor))
        self._interactive_until=time.monotonic()+.20
        self._schedule()
        self._request_idle_render()

    def _wheel(self,e):
        if getattr(e,"delta",0):
            self._zoom(1.1 if e.delta>0 else 1/1.1)
        # Do not bubble the zoom wheel into the parent's page-scroller.
        return "break"

    def _wheel_linux(self,e):
        self._zoom(1.12 if e.num==4 else 1/1.12)
        return "break"

    def _hover(self,e):
        if self.scene is None or not self.offset_markers:
            return
        projected=project_offset_markers(
            self.offset_markers,max(120,self.width),max(95,self.height),
            yaw=self.yaw,pitch=self.pitch,zoom=self.zoom,
            center=self.center,normalizer=self.normalizer)
        nearby=[(math.hypot(e.x-m["screen"][0],e.y-m["screen"][1]),m)
                for m in projected if m["visible"]]
        nearest=min(nearby,key=lambda row:row[0]) if nearby else None
        mark=nearest[1] if nearest and nearest[0]<16 else None
        name=mark.get("name") if mark else None
        if name==self._hovered_name:
            return
        self._hovered_name=name
        if mark is None:
            self.detail.set(self._detail_original)
        else:
            values=mark.get("values",(0,0,0))
            txt=(str(name)+"   X: "+f"{values[0]:g}"+
                 "   Y: "+f"{values[1]:g}"+"   Z: "+f"{values[2]:g}")
            rotation=mark.get("rotation")
            if rotation is not None:
                txt+="   Rotation: "+", ".join(f"{v:g}" for v in rotation)
            self.detail.set(txt)
        self._schedule()

    def _clear_hover(self,e=None):
        if self._hovered_name is not None:
            self._hovered_name=None
            self.detail.set(self._detail_original)
            self._schedule()

    def _schedule(self):
        if self._scheduled is None and self.scene:
            self._scheduled=self.after(12,self._paint)
    def _source_texture(self,material):
        if self.texture_override and self.texture_override.is_file():
            return self.texture_override
        return self.scene.textures.get(material) if self.scene else None
    def _texture(self,path):
        if path is None:return None
        path=str(path)
        if path not in self._texture_images:
            if len(self._texture_images)>MAX_TEXTURES:return None
            try:
                with Image.open(path) as image:
                    if image.width*image.height>12_000_000:
                        return None
                    self._texture_images[path]=image.convert("RGB")
            except (OSError,ValueError):
                self._texture_images[path]=None
        return self._texture_images[path]
    def _paint(self):
        self._scheduled = None
        if not self.winfo_exists() or not self.scene:
            return
        # Correct per-pixel UV atlas mapping, z-buffer and vertex colors.
        # Renderer is independent of Tk so all four native editor categories
        # share it and its output can be regression-tested without opening GUI.
        width,height=max(120,self.width),max(95,self.height)
        camera=(self.yaw,self.pitch,self.zoom,self.center,self.normalizer)
        interactive=(self._drag is not None or
                     time.monotonic()<self._interactive_until)
        # Hardware rendering retains the same full-resolution UV texture,
        # z-buffer and model fidelity while rotating and at rest.
        if not self._gpu_failed and self._gpu_renderer is None:
            try:
                self._gpu_renderer=GpuPreviewRenderer()
            except Exception:
                self._gpu_failed=True
        quality=("gpu" if self._gpu_renderer is not None
                 else ("fast" if interactive else "full"))
        elapsed=time.monotonic()-self._fx_start
        native_fire=bool(self.preview_fire and self.exhaust_markers)
        native_smoke=bool(self.preview_smoke and self.exhaust_markers)
        mount_key=tuple((tuple(m.get("position",(0,0,0))),
                         tuple(m.get("rotation") or (0,0,0)))
                        for m in self.exhaust_markers[:2]) if native_fire else ()
        signature=(id(self.scene),width,height,camera,str(self.texture_override),
                   self.category,quality,frame_index(elapsed) if native_fire else -1,
                   mount_key,
                   int(elapsed*NATIVE_TICKS_PER_SECOND) if native_smoke else -1,
                   tuple((tuple(m["position"]),tuple(m.get("rotation") or ()))
                         for m in self.exhaust_markers) if native_smoke else ())
        if self._base_image is None or self._base_signature != signature:
            # Both paths preserve camera aspect and exact anchor projection.
            try:
                if self._gpu_renderer is None:
                    raise RuntimeError("GPU unavailable")
                # Use true viewport resolution on normal desktop windows.
                # For unusually large panels, downscale *uniformly* so a
                # 16:9 or 4:3 OBJ never becomes flattened by the resize.
                gpu_factor=min(1.0,2560/width,1440/height)
                small_w=max(100,round(width*gpu_factor))
                small_h=max(88,round(height*gpu_factor))
                image=self._gpu_renderer.render(
                    self.scene,small_w,small_h,yaw=self.yaw,pitch=self.pitch,
                    zoom=self.zoom,center=self.center,normalizer=self.normalizer,
                    texture_loader=self._texture,
                    texture_override=self.texture_override,
                    category=self.category,
                    fx_exhausts=self.exhaust_markers if native_fire else (),
                    fx_smoke_exhausts=self.exhaust_markers if native_smoke else (),
                    fx_time=elapsed)
            except Exception:
                # Retain the reliable original CPU path on older/no-GL PCs.
                self._gpu_failed=True
                if self._gpu_renderer is not None:
                    try:self._gpu_renderer.release()
                    except Exception:pass
                self._gpu_renderer=None
                quality="fast" if interactive else "full"
                signature=(id(self.scene),width,height,camera,
                           str(self.texture_override),self.category,quality)
                factor=min(.72 if interactive else 1.,
                           (900 if interactive else MAX_WIDTH)/width,
                           (520 if interactive else MAX_HEIGHT)/height)
                small_w=max(100,round(width*factor))
                small_h=max(88,round(height*factor))
                renderer=render_fast if interactive else render_scene
                image=renderer(
                    self.scene,small_w,small_h,
                    yaw=self.yaw,pitch=self.pitch,zoom=self.zoom,
                    center=self.center,normalizer=self.normalizer,
                    texture_loader=self._texture,
                    texture_override=self.texture_override,
                    category=self.category,
                    **({} if interactive else {"draw_header":False}))
            if image.size!=(width,height):
                image=image.resize((width,height),Image.Resampling.BILINEAR)
            self._base_image=image
            self._base_signature=signature
        image=paint_offset_markers(
            self._base_image,self.offset_markers,yaw=self.yaw,pitch=self.pitch,
            zoom=self.zoom,center=self.center,normalizer=self.normalizer,
            hovered=self._hovered_name,draw_rotation=not bool(self.exhaust_markers))
        if self.preview_smoke and self._gpu_renderer is None:
            image=paint_retail_smoke(
                image,self.exhaust_markers,
                yaw=self.yaw,pitch=self.pitch,zoom=self.zoom,
                center=self.center,normalizer=self.normalizer,
                time_s=elapsed)
        # Only the CPU fallback draws approximate fire; OpenGL displays the
        # eight original CTR turbo meshes at their full retail max size.
        image=paint_exhaust_effects(
            image,self.exhaust_markers,yaw=self.yaw,pitch=self.pitch,
            zoom=self.zoom,center=self.center,normalizer=self.normalizer,
            time_s=elapsed,
            fire=self.preview_fire and self._gpu_renderer is None,
            smoke=False,show_arrows=self.preview_arrows)
        draw=ImageDraw.Draw(image)
        draw.text((10,8),self.category.upper()+"  /  "+
                  self.scene.kind+"  /  "+(
                      "GPU TEXTURED" if self._gpu_renderer is not None
                      else ("FAST ORBIT (CPU)" if interactive else "TEXTURED (CPU)")),
                  fill=(255,161,85))
        self._preview_photo=ImageTk.PhotoImage(image)
        self.image.configure(image=self._preview_photo,text="")


class TextureGallery(tk.Frame):
    """Thumbnail/file/name picker shared across all native mod types."""
    def __init__(self,parent,*,editable=False,on_preview=None):
        super().__init__(parent,bg="#111821")
        self.editable=editable
        self.on_preview=on_preview
        self.rows=[]
        self.photos=[]
        tk.Label(self,text="TEXTURES  /  PREVIEW",fg="#FF9B49",
                 bg="#111821",font=("Segoe UI Semibold",10),
                 anchor="w").pack(fill="x",padx=7,pady=(5,2))
        outer=tk.Frame(self,bg="#111821")
        outer.pack(fill="both",expand=True)
        self.canvas=tk.Canvas(outer,height=121,bg="#111821",highlightthickness=0)
        self.canvas.pack(side="left",fill="both",expand=True)
        scroll=tk.Scrollbar(outer,orient="vertical",command=self.canvas.yview)
        scroll.pack(side="right",fill="y")
        self.canvas.configure(yscrollcommand=scroll.set)
        self.items=tk.Frame(self.canvas,bg="#111821")
        self.frame_id=self.canvas.create_window((0,0),window=self.items,anchor="nw")
        self.items.bind("<Configure>",lambda e:self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",lambda e:self.canvas.itemconfigure(
            self.frame_id,width=e.width))
        tk.Label(self,text=("Edit each label as it should appear in game."
                           if editable else
                           "Click a thumbnail to preview that texture on the model."),
                 fg="#97A2B2",bg="#111821",anchor="w",justify="left",
                 font=("Segoe UI",8)).pack(fill="x",padx=7,pady=3)

    def load(self,paths,*,selected_default=True):
        """Accept list[Path] or list[{file,filename,suggested_name}]."""
        for row in self.items.winfo_children():row.destroy()
        self.rows.clear()
        self.photos.clear()
        for entry in list(paths)[:48]:
            if isinstance(entry,dict):
                file=Path(entry.get("file",""))
                title=str(entry.get("suggested_name") or file.stem)
            else:
                file=Path(entry)
                title=file.stem.replace("_"," ").strip()
            if not file.is_file() or file.suffix.lower() not in (".png",".bmp",".jpg",".jpeg",".tga"):
                continue
            frame=tk.Frame(self.items,bg="#18212B",highlightbackground="#2B3745",
                           highlightthickness=1)
            frame.pack(fill="x",padx=5,pady=2)
            try:
                with Image.open(file) as image:
                    width,height=image.size
                    if width*height>12_000_000:raise OSError("Oversized preview image")
                    tile=image.convert("RGBA")
                    tile.thumbnail((52,52),Image.Resampling.LANCZOS)
                    photo=ImageTk.PhotoImage(tile)
            except (OSError,ValueError):
                photo=None
                width=height=0
            if photo is not None:self.photos.append(photo)
            show=tk.Button(frame,image=photo,text="PREVIEW" if photo is None else "",
                           bg="#0B121B",fg="#FFA55E",relief="flat",
                           width=56,height=56,compound="center",
                           command=lambda p=file:self.select(p))
            show.pack(side="left",padx=3,pady=2)
            details=tk.Frame(frame,bg="#18212B")
            details.pack(side="left",fill="both",expand=True,padx=(4,6),pady=3)
            tk.Label(details,text=file.name,fg="#F4E7D9",bg="#18212B",
                     font=("Segoe UI",9),anchor="w").pack(fill="x")
            tk.Label(details,text=(str(width)+" × "+str(height)+" px"),
                     fg="#8999A7",bg="#18212B",
                     font=("Segoe UI",8),anchor="w").pack(fill="x")
            selected=tk.BooleanVar(value=selected_default)
            custom=tk.StringVar(value=title[:23] if len(title)>23 else title)
            if self.editable:
                tk.Checkbutton(frame,variable=selected,bg="#18212B",
                               activebackground="#18212B",selectcolor="#2A3644",
                               fg="#F8AB64").pack(side="right",padx=4)
                tk.Entry(details,textvariable=custom,bg="#101821",
                         fg="#F3DDCB",insertbackground="#FF892D",
                         relief="flat",font=("Segoe UI",9)).pack(fill="x",pady=(2,0))
            self.rows.append((file,selected,custom))
        if not self.rows:
            tk.Label(self.items,text="No previewable PNG/BMP/JPG textures found.",
                     fg="#9BA5AF",bg="#111821",anchor="w").pack(fill="x",padx=10,pady=8)
        self.canvas.yview_moveto(0)

    def select(self,path):
        if self.on_preview:self.on_preview(Path(path))

    def selected_names(self):
        return {p.name:name.get().strip()
                for p,selected,name in self.rows if selected.get()}