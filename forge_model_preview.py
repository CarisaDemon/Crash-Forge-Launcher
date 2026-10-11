"""Crash Forge native 3D preview for Character / Kart / Wheels / Track.

This is an isolated, read-only software viewport. No GPU hooks, game input,
file mutation or Blender installation required. OBJ shows MTL/UV material
colors, with optional replacement texture. CTR LEV uses its REAL quad blocks
and hi-detail vertex colors (VRM imagery is not decoded in this preview).
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import struct
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageDraw

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
        self.category=category
        self.detail=tk.StringVar(value="Select an OBJ model or LEV track for preview.")
        outer=tk.Frame(self,bg="#121820",highlightthickness=1,highlightbackground="#444B54")
        outer.pack(fill="both",expand=True)
        self.image=tk.Label(outer,bg="#0c141c",fg="#ffac73",text="3D PREVIEW\nSELECT FILE")
        self.image.pack(fill="both",expand=True,padx=3,pady=3)
        self.image.bind("<ButtonPress-1>",self._down)
        self.image.bind("<B1-Motion>",self._move)
        self.image.bind("<MouseWheel>",self._wheel)
        self.image.bind("<Button-4>",lambda e:self._zoom(1.12))
        self.image.bind("<Button-5>",lambda e:self._zoom(1/1.12))
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
            self.width=min(960,event.width)
            self.height=min(620,event.height)
            self._schedule()
    def load(self, path, *, category=None, texture_override=None):
        if category:self.category=category
        try:
            path=Path(path)
            parsed=load_ctr_lev(path) if path.suffix.lower()==".lev" else load_obj(path)
            self.scene=parsed
            self.texture_override=Path(texture_override) if texture_override else None
            self._texture_images.clear()
            self._fit()
            self.detail.set(parsed.kind+" • "+parsed.description)
            self._schedule()
            return True
        except (OSError,ValueError,struct.error) as exc:
            self.scene=None
            self.image.configure(image="",text=str(exc)[:170])
            self.detail.set("Preview unavailable: "+str(exc)[:140])
            return False
    def set_variant(self,texture):
        self.texture_override=Path(texture) if texture else None
        self._schedule()
    def _fit(self):
        if not self.scene:return
        vertices=self.scene.vertices
        bounds=[(min(v[k] for v in vertices),max(v[k] for v in vertices)) for k in range(3)]
        self.center=tuple((a+b)*.5 for a,b in bounds)
        self.normalizer=max((b-a for a,b in bounds),default=1) or 1.
        self.reset()
    def reset(self):
        self.yaw=.7
        self.pitch=.45
        self.zoom=1
        self._schedule()
    def _down(self,e):
        self._drag=(e.x,e.y)
    def _move(self,e):
        if self._drag is None:return
        dx=e.x-self._drag[0]
        dy=e.y-self._drag[1]
        self._drag=(e.x,e.y)
        self.yaw+=dx*.012
        self.pitch=max(-1.45,min(1.45,self.pitch+dy*.012))
        self._schedule()
    def _zoom(self,factor):
        self.zoom=max(.23,min(6,self.zoom*factor))
        self._schedule()
    def _wheel(self,e):
        self._zoom(1.1 if e.delta>0 else 1/1.1)
    def _schedule(self):
        if self._scheduled is None and self.scene:
            self._scheduled=self.after(45,self._paint)
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
        self._scheduled=None
        if not self.winfo_exists() or not self.scene:return
        w=max(120,min(self.width,960))
        h=max(95,min(self.height,620))
        scene=self.scene
        image=Image.new("RGB",(w,h),(12,20,29))
        draw=ImageDraw.Draw(image)
        for x in range(0,w,40):
            draw.line((x,h-16,x+60,h-65),fill=(21,34,43),width=1)
        draw.line((0,h-16,w,h-16),fill=(43,66,73),width=1)
        cy,sy=math.cos(self.yaw),math.sin(self.yaw)
        cp,sp=math.cos(self.pitch),math.sin(self.pitch)
        scale=2.4/self.normalizer
        transform=[]
        factor=min(w,h)*1.3*self.zoom
        for vx,vy,vz in scene.vertices:
            x=(vx-self.center[0])*scale
            y=(vy-self.center[1])*scale
            z=(vz-self.center[2])*scale
            xo=cy*x+sy*z
            zo=-sy*x+cy*z
            yo=cp*y-sp*zo
            depth=sp*y+cp*zo
            camera=max(.35,4.8-depth)
            transform.append((w/2+factor*xo/camera,
                              h/2-factor*yo/camera,
                              depth))
        rendered=[]
        faces=scene.faces
        step=max(1,math.ceil(len(faces)/MAX_RENDER_TRIANGLES))
        for index in range(0,len(faces),step):
            a,b,c,ua,ub,uc,material=faces[index]
            p0,p1,p2=transform[a],transform[b],transform[c]
            # Outside entire viewport, skip costly fill.
            if (max(p0[0],p1[0],p2[0]) < -20 or
                min(p0[0],p1[0],p2[0]) > w+20 or
                max(p0[1],p1[1],p2[1]) < -20 or
                min(p0[1],p1[1],p2[1]) > h+20):
                continue
            if scene.colors:
                base=tuple(int((scene.colors[a][i]+scene.colors[b][i]+
                               scene.colors[c][i])/3) for i in range(3))
            else:
                texture=self._texture(self._source_texture(material))
                if texture and None not in (ua,ub,uc) and scene.uvs:
                    uu=sum(scene.uvs[i][0] for i in (ua,ub,uc))/3
                    vv=sum(scene.uvs[i][1] for i in (ua,ub,uc))/3
                    sample=(int((uu%1)*max(1,texture.width-1)),
                            int(((1-vv)%1)*max(1,texture.height-1)))
                    base=texture.getpixel(sample)
                else:
                    base=(160,176,190) if scene.kind=="OBJ" else (110,140,155)
            # Simple diffuse light from upper/front left, preserve original color.
            ux,uy=p1[0]-p0[0],p1[1]-p0[1]
            vx,vy=p2[0]-p0[0],p2[1]-p0[1]
            winding=ux*vy-uy*vx
            brightness=.78 if winding<0 else .88
            mean_depth=(p0[2]+p1[2]+p2[2])/3
            color=tuple(min(255,int(channel*brightness)+12) for channel in base)
            rendered.append((mean_depth,(p0[:2],p1[:2],p2[:2]),color))
        rendered.sort(key=lambda record:record[0])
        for _depth,points,color in rendered:
            draw.polygon(points,fill=color)
        # subtle silhouette grid / bounds
        draw.text((9,8),self.category.upper()+"  •  "+scene.kind+" PREVIEW",fill=(253,153,79))
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
        outer.pack(fill="x")
        self.canvas=tk.Canvas(outer,height=166,bg="#111821",highlightthickness=0)
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
