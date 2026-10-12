"""OpenGL 3.3 GPU rasterizer for FULL textured Crash Forge model previews.

This optional backend only reads OBJ/MTL/texture assets, never game state.
It preserves per-pixel UVs, triangle occlusion and original geometry during
orbiting. The legacy CPU renderer remains the fallback without compatible GL.
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
from PIL import Image

from forge_preview_rasterizer import _background
from forge_preview_retail_fx import (
    ASSETS,TURBO_FIRE_SIZE,frame_index,load_retail_turbo_frames,rotation_matrix)
from forge_preview_ctr_particle import native_smoke_screen_vertices

# Do not force the 1200px CPU preview width on a 1700x320 resizable window.
# Independent width/height clamping stretched the kart horizontally.
MAX_GPU_WIDTH = 2560
MAX_GPU_HEIGHT = 1440

# Vendored runtime is isolated from the user's other Python installations.
_VENDOR=Path(__file__).resolve().parent/"preview_gpu_vendor"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0,str(_VENDOR))

try:
    import moderngl
except (ImportError, OSError):
    moderngl=None


_VERTEX="""
#version 330
in vec3 in_position;
in vec2 in_uv;
in vec3 in_color;
uniform vec2 u_resolution;
uniform vec3 u_center;
uniform float u_normalizer;
uniform float u_zoom;
uniform vec2 u_yaw;
uniform vec2 u_pitch;
out vec2 v_uv;
out vec3 v_color;
void main() {
    vec3 pos=(in_position-u_center)*(2.4/max(.00001,u_normalizer));
    float rx=u_yaw.x*pos.x+u_yaw.y*pos.z;
    float rz=-u_yaw.y*pos.x+u_yaw.x*pos.z;
    float ry=u_pitch.x*pos.y-u_pitch.y*rz;
    float depth=u_pitch.y*pos.y+u_pitch.x*rz;
    float camera=max(.35,4.8-depth);
    float size=min(u_resolution.x,u_resolution.y)*1.33*clamp(u_zoom,.2,6.);
    // Use clip-W for perspective-correct UV interpolation, and clip-Z
    // monotonic with camera distance so closer triangles win the depth test.
    gl_Position=vec4(2.*size*rx/u_resolution.x,
                     2.*size*ry/u_resolution.y,
                     camera*(camera/6.0-1.0),camera);
    v_uv=in_uv;
    v_color=in_color;
}
"""
_FRAGMENT="""
#version 330
uniform sampler2D u_texture;
uniform bool u_textured;
in vec2 v_uv;
in vec3 v_color;
out vec4 color;
void main() {
    vec3 rgb=u_textured ? texture(u_texture,vec2(v_uv.x,1.0-v_uv.y)).rgb
                        : v_color;
    color=vec4(clamp(rgb*.98 + vec3(2.0/255.0),0.0,1.0),1.0);
}
"""
_BG_VERTEX="""
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main(){v_uv=(in_pos+vec2(1.0))*.5;gl_Position=vec4(in_pos,0.0,1.0);}
"""
_BG_FRAGMENT="""
#version 330
uniform sampler2D u_background;
in vec2 v_uv;
out vec4 color;
void main(){color=texture(u_background,v_uv);}
"""


_FX_VERTEX = """
#version 330
in vec3 in_position;
in vec2 in_uv;
in vec3 in_color;
in vec3 in_barycentric;
noperspective out vec3 v_barycentric;
uniform vec2 u_resolution;
uniform vec3 u_center;
uniform float u_normalizer;
uniform float u_zoom;
uniform vec2 u_yaw;
uniform vec2 u_pitch;
uniform vec3 u_origin;
uniform mat3 u_rotation;
uniform float u_size;
uniform bool u_flip_x;
out vec2 v_uv;
out vec3 v_color;
void main() {
    vec3 local = in_position;
    if (u_flip_x) local.x = -local.x;
    vec3 world = u_origin + u_rotation * (local * u_size);
    vec3 pos=(world-u_center)*(2.4/max(.00001,u_normalizer));
    float rx=u_yaw.x*pos.x+u_yaw.y*pos.z;
    float rz=-u_yaw.y*pos.x+u_yaw.x*pos.z;
    float ry=u_pitch.x*pos.y-u_pitch.y*rz;
    float depth=u_pitch.y*pos.y+u_pitch.x*rz;
    float camera=max(.35,4.8-depth);
    float size=min(u_resolution.x,u_resolution.y)*1.33*clamp(u_zoom,.2,6.);
    gl_Position=vec4(2.*size*rx/u_resolution.x,
                     2.*size*ry/u_resolution.y,
                     camera*(camera/6.0-1.0),camera);
    v_uv=in_uv;
    v_color=in_color;
    v_barycentric=in_barycentric;
}
"""
_FX_FRAGMENT = """
#version 330
uniform sampler2D u_fx_texture;
uniform bool u_textured;
uniform float u_material_alpha;
uniform float u_soften_ribbon;
in vec2 v_uv;
in vec3 v_color;
noperspective in vec3 v_barycentric;
out vec4 color;
void main() {
    // CTR-tools' extracted original PS1 textures ARE RGBA: 0=transparent,
    // 127=semitransparent and 254=opaque. Earlier .convert('RGB') discarded
    // those alpha values and made enormous dark/black turbo triangles.
    vec4 src = u_textured
        ? texture(u_fx_texture,vec2(v_uv.x,1.0-v_uv.y))
        : vec4(1.0);
    vec3 shade=max(v_color,vec3(0.0));
    if (src.a < 0.02 || max(shade.r,max(shade.g,shade.b)) < 0.003) discard;
    // The extracted PS1 fire model includes almost-black translucent helper
    // polygons, which look like giant dark triangles in a modern high-res
    // viewer. PS1 additive energy from them is negligible. Prevent the
    // dark-sheet artifacts while preserving the authentic colored faces
    // and their original RGBA coverage.
    vec3 rgb=src.rgb*min(shade*2.0,vec3(1.8));
    float energy=max(rgb.r,max(rgb.g,rgb.b));
    float visible=smoothstep(0.15,0.36,energy);
    if (visible<0.01) discard;
    // Original flat opaque texture extraction exposes edges of big GT3
    // translucent sheets. The PS1 blended/dithered primitive did not have
    // hard cutouts like this. A per-polygon fringe based on barycentric
    // distance fades just these ribbons; leave the bright core unchanged.
    float fringe=smoothstep(0.0,0.25,
        min(min(v_barycentric.x,v_barycentric.y),v_barycentric.z));
    float softness=mix(1.0,fringe,u_soften_ribbon);
    color=vec4(rgb,src.a*visible*u_material_alpha*softness);
}
"""




_SMOKE_VERTEX = """
#version 330
in vec3 in_position;  // real world-space particle centre, from native CTR
in vec2 in_uv;        // original sprite UV
in vec3 in_color;     // original particle color axis
in vec2 in_corner;    // particle rotated local sprite offset in OBJ units
uniform vec2 u_resolution;
uniform vec3 u_center;
uniform float u_normalizer;
uniform float u_zoom;
uniform vec2 u_yaw;
uniform vec2 u_pitch;
out vec2 v_uv;
out vec3 v_color;
void main() {
    // Do camera-facing alignment AFTER projecting the *particle centre*.
    // The PS1 GTE builds FT4 vertices around a projected centre rather than
    // turning a 3D rectangular plane; that is why real CTR smoke never
    // becomes edge-on at any camera angle.
    float normalize_factor = 2.4/max(.00001,u_normalizer);
    vec3 pos = (in_position-u_center)*normalize_factor;
    float rx = u_yaw.x*pos.x + u_yaw.y*pos.z;
    float rz = -u_yaw.y*pos.x + u_yaw.x*pos.z;
    float ry = u_pitch.x*pos.y - u_pitch.y*rz;
    float depth = u_pitch.y*pos.y + u_pitch.x*rz;
    float camera = max(.35,4.8-depth);
    float size = min(u_resolution.x,u_resolution.y)*1.33*clamp(u_zoom,.2,6.);
    vec2 screenXY = vec2(rx,ry) + in_corner*normalize_factor;
    gl_Position = vec4(
        2.*size*screenXY.x/u_resolution.x,
        2.*size*screenXY.y/u_resolution.y,
        camera*(camera/6.0-1.0),
        camera);
    v_uv=in_uv;
    v_color=in_color;
}
"""

_SMOKE_FRAGMENT = """
#version 330
uniform sampler2D u_smoke_texture;
in vec2 v_uv;
in vec3 v_color;
out vec4 color;
void main() {
    // iconGroup[1] = 'dustpuff' from shared.mpk, icon 0 only.
    // emSet_Exhaust_High uses particle flags 0x08a3 and axis7 tint.
    vec4 icon=texture(u_smoke_texture,vec2(v_uv.x,1.0-v_uv.y));
    // Enforce fully transparent image edges, including interpolated samples
    // outside the original 32px CLUT. This is an alpha border, not a blur.
    float edge=min(min(v_uv.x,1.0-v_uv.x),min(v_uv.y,1.0-v_uv.y));
    float edge_alpha=smoothstep(0.0,0.04,edge);
    float alpha=icon.a*edge_alpha;
    if (alpha<0.001) discard;
    // CTR 0x08a3 uses additive blending (B+F); no opaque rectangle edges.
    color=vec4(icon.rgb*v_color,alpha);
}
"""

def _additive_psx_smoke_texture(source_image):
    """Interpret the original dustpuff00 PS1 additive color as coverage.

    CTR-tools preserved 1-bit PSX CLUT alpha, but many completely BLACK
    pixels are marked opaque. PS1 ABR=1 adds RGB and black contributes zero
    light, so those pixels were functionally invisible. OpenGL bilinear
    filtering of these opaque black texels otherwise produces hard, jagged
    silhouette/negative space on camera-facing particle quads.

    This is a reversible GPU upload conversion, NOT a modification to
    the extracted original resource on disk. Dustpuff RGB is grayscale,
    so using gray luminance as alpha and white as additive color gives
    the same first-order brightness (src_RGB * originalAlpha).
    """
    source=np.asarray(source_image.convert("RGBA"),dtype=np.float32)
    gray=np.max(source[:,:,:3],axis=2) / 255.
    coverage=source[:,:,3]/255.
    brightness=np.clip(gray*coverage,0.,1.)
    # Do NOT blur this 32x32 texture: earlier GaussianBlur+halo artificially
    # created alpha on 116 previously invisible border pixels. With GL
    # clamp-to-edge those lit pixels produce precisely the rectangular seams
    # between adjacent smoke sprites. Original PS1 additive luminance already
    # provides coverage without needing any blur.
    alpha=np.uint8(np.rint(brightness*255))
    alpha[0,:]=0
    alpha[-1,:]=0
    alpha[:,0]=0
    alpha[:,-1]=0
    corrected=Image.new("RGBA",source_image.size,(255,255,255,255))
    corrected.putalpha(Image.fromarray(alpha,"L"))
    return corrected


class GpuPreviewError(RuntimeError):
    pass


class GpuPreviewRenderer:
    def __init__(self):
        if moderngl is None:
            raise GpuPreviewError("ModernGL runtime is not available")
        try:
            self.ctx=moderngl.create_standalone_context(require=330)
            self.program=self.ctx.program(vertex_shader=_VERTEX,fragment_shader=_FRAGMENT)
            self.bg_program=self.ctx.program(
                vertex_shader=_BG_VERTEX,fragment_shader=_BG_FRAGMENT)
            self.fx_program=self.ctx.program(
                vertex_shader=_FX_VERTEX,fragment_shader=_FX_FRAGMENT)
            self.fx_program["u_fx_texture"].value=0
            self.smoke_program=self.ctx.program(
                vertex_shader=_SMOKE_VERTEX,fragment_shader=_SMOKE_FRAGMENT)
            self.smoke_program["u_smoke_texture"].value=0
            xy=np.asarray([-1,-1, 3,-1, -1,3],dtype=np.float32)
            self.bg_vbo=self.ctx.buffer(xy.tobytes())
            self.bg_vao=self.ctx.vertex_array(
                self.bg_program,[(self.bg_vbo,"2f","in_pos")])
            self.program["u_texture"].value=0
            self.bg_program["u_background"].value=0
        except Exception as ex:
            raise GpuPreviewError("GPU preview initialization failed") from ex
        self._size=None
        self._fbo=None
        self._bg_texture=None
        self._scene_key=None
        self._batches=[]
        self._mesh_textures={}
        self._scene_error=None
        self._fx_batches={}
        self._fx_textures={}
        self._smoke_texture=None
        self._smoke_buffer=None
        self._smoke_vao=None

    def _create_target(self,width,height,category,kind):
        key=(width,height,category,kind)
        if self._size==key:
            return
        if self._fbo is not None:
            self._fbo.release()
            self._fbo=None
            self.color.release()
            self.depth.release()
        if self._bg_texture is not None:
            self._bg_texture.release()
            self._bg_texture=None
        self.color=self.ctx.texture((width,height),components=3)
        self.depth=self.ctx.depth_renderbuffer((width,height))
        self._fbo=self.ctx.framebuffer(
            color_attachments=[self.color],depth_attachment=self.depth)
        self._size=key
        bg=_background(width,height,category,kind).transpose(
            Image.Transpose.FLIP_TOP_BOTTOM)
        self._bg_texture=self.ctx.texture((width,height),3,bg.tobytes(),
                                          alignment=1)
        self._bg_texture.filter=(moderngl.NEAREST,moderngl.NEAREST)

    def _free_scene(self):
        for vao,vbo,texture_key in self._batches:
            vao.release()
            vbo.release()
        for tex in self._mesh_textures.values():
            tex.release()
        self._batches=[]
        self._mesh_textures={}
        self._scene_key=None

    def _upload_scene(self,scene,texture_loader,texture_override):
        key=(id(scene),str(texture_override))
        if key==self._scene_key:
            return
        self._free_scene()
        if not scene.vertices or not scene.faces:
            self._scene_key=key
            return
        vertices=np.asarray(scene.vertices,dtype=np.float32)
        uvs=np.asarray(scene.uvs,dtype=np.float32) if scene.uvs else np.empty((0,2),dtype=np.float32)
        colors=np.asarray(scene.colors,dtype=np.float32)/255.0 if scene.colors else None
        groups={}
        count=min(len(scene.faces),8000)
        stride=max(1,(len(scene.faces)+count-1)//count)
        for face in scene.faces[::stride]:
            a,b,c,ta,tb,tc,material=face
            source=texture_override or scene.textures.get(material)
            textured=(colors is None and source is not None and
                      ta is not None and tb is not None and tc is not None and
                      all(0<=j<len(uvs) for j in (ta,tb,tc)))
            texture_key=str(source) if textured else ""
            if texture_key and texture_key not in self._mesh_textures:
                try:
                    image=texture_loader(source) if texture_loader else None
                    if image is not None:
                        image=image.convert("RGB")
                        if 0<image.width*image.height<=12_000_000:
                            tex=self.ctx.texture(image.size,3,image.tobytes(),alignment=1)
                            tex.filter=(moderngl.LINEAR,moderngl.LINEAR)
                            tex.repeat_x=True
                            tex.repeat_y=True
                            self._mesh_textures[texture_key]=tex
                        else:
                            texture_key=""
                    else:
                        texture_key=""
                except (OSError,ValueError,TypeError):
                    texture_key=""
            if texture_key not in groups:
                groups[texture_key]=[]
            face_indices=(a,b,c)
            face_uv=(ta,tb,tc)
            for idx,uv_idx in zip(face_indices,face_uv):
                point=vertices[idx]
                uv=uvs[uv_idx] if texture_key else (0.,0.)
                rgb=colors[idx] if colors is not None else (
                    (163/255.,176/255.,189/255.) if scene.kind=="OBJ" else
                    (116/255.,146/255.,164/255.))
                groups[texture_key].append(
                    (point[0],point[1],point[2],uv[0],uv[1],rgb[0],rgb[1],rgb[2]))

        for texture_key,records in groups.items():
            vertex_data=np.asarray(records,dtype=np.float32)
            vbo=self.ctx.buffer(vertex_data.tobytes())
            vao=self.ctx.vertex_array(self.program,[
                (vbo,"3f 2f 3f","in_position","in_uv","in_color")])
            self._batches.append((vao,vbo,texture_key))
        self._scene_key=key

    def original_fire_available(self):
        return len(load_retail_turbo_frames())==8

    def _fx_batches_for(self,frame):
        if frame in self._fx_batches:
            return self._fx_batches[frame]
        frames=load_retail_turbo_frames()
        if len(frames)!=8:
            return ()
        prepared=[]
        for source,records in frames[frame]:
            # The CTR-tools OBJ/MTL converter loses the PS1 GPU primitive
            # alpha/blend flags on 956_* and 245_* helper ribbons. Drawing
            # those extracted fully opaque panels creates the enormous dark
            # triangular fans reported by users. Keep the actual 8-frame
            # flame CORE material 976_* in the preview until the original
            # blend packets can be reconstructed; no original source assets
            # are edited or deleted.
            if source is not None and source.name.startswith(("956_","245_")):
                continue
            name=str(source) if source is not None else ""
            if name and name not in self._fx_textures:
                try:
                    with Image.open(source) as src:
                        image=src.convert("RGBA")
                    tex=self.ctx.texture(image.size,4,image.tobytes(),alignment=1)
                    tex.filter=(moderngl.LINEAR,moderngl.LINEAR)
                    tex.repeat_x=True
                    tex.repeat_y=True
                    self._fx_textures[name]=tex
                except (OSError,ValueError):
                    name=""
            # One barycentric basis per original GT3 triangle, to soften
            # edges of the extracted translucent sheet polygons on GPU.
            barycentric=np.tile(np.eye(3,dtype=np.float32),
                               (len(records)//3,1))
            gpu_records=np.column_stack((records,barycentric))
            vbo=self.ctx.buffer(np.ascontiguousarray(gpu_records).tobytes())
            vao=self.ctx.vertex_array(self.fx_program,[
                (vbo,"3f 2f 3f 3f","in_position","in_uv",
                 "in_color","in_barycentric")])
            prepared.append((vao,vbo,name))
        self._fx_batches[frame]=prepared
        return prepared

    def _draw_retail_fire(self,exhausts,time_s,*,width,height,yaw,pitch,
                          zoom,center,normalizer):
        if not exhausts or not self.original_fire_available():
            return
        import math
        program=self.fx_program
        program["u_resolution"].value=(float(width),float(height))
        program["u_center"].value=tuple(float(x) for x in center)
        program["u_normalizer"].value=float(normalizer)
        program["u_zoom"].value=float(zoom)
        program["u_yaw"].value=(math.cos(yaw),math.sin(yaw))
        program["u_pitch"].value=(math.cos(pitch),math.sin(pitch))
        # Render both front/back triangle winding even on mirrored exhausts;
        # PS1 turbo effect faces have no closed shell and must remain visible
        # when the preview camera rotates behind them.
        self.ctx.disable(moderngl.CULL_FACE)
        # Retail turbo has only two instances. The second is 3 frames ahead,
        # with a mirrored X basis; size 8 is its unscaled maximum.
        self.ctx.enable(moderngl.BLEND)
        # PSX turbo polygons are light-emitting/additive. Read original
        # extracted RGBA coverage without darkening the background.
        self.ctx.blend_func=(moderngl.SRC_ALPHA,moderngl.ONE)
        self.ctx.depth_mask=False
        try:
            for nozzle,mark in enumerate(exhausts[:2]):
                if mark.get("rotation") is None:
                    continue
                # Center the visible retail effect on the SAME editor mount
                # used by the native emitter/smoke. The native runtime uses a
                # separate quarter-mount model transform for its legacy fire
                # instance, but that offset assumes retail model space and
                # visibly misaligns the recovered OBJ on an arbitrary kart.
                # No game or kart.ini coordinates are modified here.
                flame_origin=mark["position"]
                program["u_origin"].value=tuple(float(v) for v in flame_origin)
                rotation=rotation_matrix(mark["rotation"])
                program["u_rotation"].write(rotation.T.tobytes())
                program["u_size"].value=float(TURBO_FIRE_SIZE)/8.
                program["u_flip_x"].value=(nozzle==1)
                for vao,vbo,texkey in self._fx_batches_for(frame_index(time_s,nozzle)):
                    program["u_textured"].value=bool(texkey)
                    if texkey:
                        # CTR-tools exports the PS1 fire's semi-transparent
                        # 956* ribbons as RGBA alpha=254, losing the original
                        # per-primitive semi-transparency bit. Keep the real
                        # animation mesh/UVs but restore soft half-lit energy
                        # rather than drawing hard opaque orange triangles.
                        material=Path(texkey).name
                        program["u_material_alpha"].value=(
                            0.10 if material.startswith("956_") else
                            0.0 if material.startswith("245_") else 1.0)
                        program["u_soften_ribbon"].value=(
                            1.0 if material.startswith(("956_","245_"))
                            else 0.0)
                        self._fx_textures[texkey].use(0)
                    else:
                        program["u_material_alpha"].value=1.0
                        program["u_soften_ribbon"].value=0.0
                    vao.render(mode=moderngl.TRIANGLES)
        finally:
            self.ctx.depth_mask=True
            self.ctx.disable(moderngl.BLEND)

    def _draw_original_smoke(self,exhausts,time_s,*,width,height,yaw,pitch,
                             zoom,center,normalizer):
        # Native Particle_Init -> Particle_UpdateList -> Particle_RenderList,
        # ported from C into forge_preview_ctr_particle.py; this only converts
        # PSX textured quad vertices into OpenGL 3.3 instead of PS1 GTE/OT.
        vertex_data=native_smoke_screen_vertices(exhausts,time_s)
        if vertex_data.size==0:
            return
        if self._smoke_texture is None:
            with Image.open(ASSETS/"dustpuff00.png") as src:
                texture=_additive_psx_smoke_texture(src)
            self._smoke_texture=self.ctx.texture(texture.size,4,
                texture.tobytes(),alignment=1)
            self._smoke_texture.filter=(moderngl.LINEAR,moderngl.LINEAR)
            self._smoke_texture.repeat_x=False
            self._smoke_texture.repeat_y=False
        if self._smoke_buffer is None:
            # 4 exhausts, 5 native particles each, 2 tris/particle,
            # 3 vertices/triangle, 10 floats: world centre, uv, tint and
            # screen-space offset. No perspective-skewed 3D smoke polygons.
            reserve=4*5*6*10*4
            self._smoke_buffer=self.ctx.buffer(reserve=reserve,dynamic=True)
            self._smoke_vao=self.ctx.vertex_array(self.smoke_program,[
                (self._smoke_buffer,"3f 2f 3f 2f",
                 "in_position","in_uv","in_color","in_corner")])
        blob=vertex_data.tobytes()
        if len(blob)>self._smoke_buffer.size:
            self._smoke_buffer.orphan(size=len(blob))
        self._smoke_buffer.write(blob)
        program=self.smoke_program
        import math
        program["u_resolution"].value=(float(width),float(height))
        program["u_center"].value=tuple(float(x) for x in center)
        program["u_normalizer"].value=float(normalizer)
        program["u_zoom"].value=float(zoom)
        program["u_yaw"].value=(math.cos(yaw),math.sin(yaw))
        program["u_pitch"].value=(math.cos(pitch),math.sin(pitch))
        # Smoke shader needs only the projected emitter centre + offsets;
        # no local model transform/rotation unlike the fire program.
        self.ctx.disable(moderngl.CULL_FACE)
        self.ctx.enable(moderngl.BLEND)
        # emSet_Exhaust_High flags 0x08a3 -> tpage abr=1: B+F.
        self.ctx.blend_func=(moderngl.SRC_ALPHA,moderngl.ONE)
        self.ctx.depth_mask=False
        try:
            self._smoke_texture.use(0)
            self._smoke_vao.render(mode=moderngl.TRIANGLES,
                                   vertices=len(vertex_data))
        finally:
            self.ctx.depth_mask=True
            self.ctx.disable(moderngl.BLEND)

    def render(self,scene,width,height,*,yaw=.7,pitch=.45,zoom=1.,
               center=(0.,0.,0.),normalizer=1.,texture_loader=None,
               texture_override=None,category="Kart",
               fx_exhausts=(),fx_smoke_exhausts=(),fx_time=0.):
        width=max(100,min(int(width),MAX_GPU_WIDTH))
        height=max(88,min(int(height),MAX_GPU_HEIGHT))
        self._create_target(width,height,category,scene.kind)
        self._upload_scene(scene,texture_loader,texture_override)
        self._fbo.use()
        self.ctx.viewport=(0,0,width,height)
        # ModernGL ctx.clear() clears color as well as depth. It must happen
        # BEFORE the background pass, never after it.
        self.ctx.clear(0.0,0.0,0.0,1.0,depth=1.0)
        self.ctx.disable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.CULL_FACE)
        self._bg_texture.use(0)
        self.bg_vao.render(mode=moderngl.TRIANGLES,vertices=3)
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.depth_func="<"
        self.ctx.depth_mask=True
        self.program["u_resolution"].value=(float(width),float(height))
        self.program["u_center"].value=tuple(float(x) for x in center)
        self.program["u_normalizer"].value=float(normalizer)
        self.program["u_zoom"].value=float(zoom)
        import math
        self.program["u_yaw"].value=(math.cos(yaw),math.sin(yaw))
        self.program["u_pitch"].value=(math.cos(pitch),math.sin(pitch))
        for vao,vbo,key in self._batches:
            self.program["u_textured"].value=bool(key)
            if key:
                self._mesh_textures[key].use(0)
            vao.render(mode=moderngl.TRIANGLES)
        if fx_exhausts:
            self._draw_retail_fire(
                fx_exhausts,fx_time,width=width,height=height,
                yaw=yaw,pitch=pitch,zoom=zoom,center=center,
                normalizer=normalizer)
        if fx_smoke_exhausts:
            self._draw_original_smoke(
                fx_smoke_exhausts,fx_time,width=width,height=height,
                yaw=yaw,pitch=pitch,zoom=zoom,center=center,
                normalizer=normalizer)
        data=self._fbo.read(components=3,alignment=1)
        return Image.frombytes("RGB",(width,height),data).transpose(
            Image.Transpose.FLIP_TOP_BOTTOM)

    def release(self):
        if self._smoke_vao is not None:
            self._smoke_vao.release()
            self._smoke_vao=None
        if self._smoke_buffer is not None:
            self._smoke_buffer.release()
            self._smoke_buffer=None
        if self._smoke_texture is not None:
            self._smoke_texture.release()
            self._smoke_texture=None
        self.smoke_program.release()
        for batches in self._fx_batches.values():
            for vao,vbo,_ in batches:
                vao.release()
                vbo.release()
        self._fx_batches.clear()
        for tex in self._fx_textures.values():
            tex.release()
        self._fx_textures.clear()
        self.fx_program.release()
        self.bg_vao.release()
        self.bg_vbo.release()
        self.bg_program.release()
        self.program.release()
        self._free_scene()
        if self._fbo is not None:
            self._fbo.release()
            self._fbo=None
            self.color.release()
            self.depth.release()
        if self._bg_texture is not None:
            self._bg_texture.release()
            self._bg_texture=None
        self.ctx.release()