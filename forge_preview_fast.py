"""Fast interactive OBJ/LEV orbit preview, with a full UV redraw when idle.

CPU-only fast painter: precomputes per-face atlas samples once, projects the
vertices as a vectorized array and draws triangles in approximate depth order.
It is intentionally used only during mouse movement; final static images use
the original perspective-correct, z-buffered textured rasterizer.
"""
from __future__ import annotations

import math
import numpy as np
from PIL import ImageDraw

from forge_preview_rasterizer import _background, _project, MAX_HEIGHT, MAX_WIDTH


def _face_data(scene, texture_loader, texture_override):
    indices = np.asarray([(f[0], f[1], f[2]) for f in scene.faces],
                         dtype=np.int32)
    colors = []
    material_cache = {}
    uv = scene.uvs
    for face in scene.faces:
        ia, ib, ic, ta, tb, tc, material = face
        if scene.colors:
            rgb = tuple(int(sum(scene.colors[j][axis] for j in (ia, ib, ic)) / 3)
                        for axis in range(3))
            colors.append(rgb)
            continue
        source = texture_override or scene.textures.get(material)
        key = str(source)
        if key not in material_cache:
            if source and texture_loader is not None:
                try:
                    image = texture_loader(source)
                    material_cache[key] = image.convert("RGB") if image else None
                except (OSError, ValueError, TypeError):
                    material_cache[key] = None
            else:
                material_cache[key] = None
        image = material_cache[key]
        if (image is not None and
                all(x is not None and 0 <= x < len(uv) for x in (ta, tb, tc))):
            u = sum(uv[j][0] for j in (ta, tb, tc))/3.
            v = sum(uv[j][1] for j in (ta, tb, tc))/3.
            pixel = (int((u % 1.0) * image.width) % image.width,
                     int(((1. - v) % 1.0) * image.height) % image.height)
            rgb = image.getpixel(pixel)
        else:
            rgb = (160, 174, 188)
        colors.append(rgb)
    vertices = np.asarray(scene.vertices, dtype=np.float64)
    e1 = vertices[indices[:, 1]] - vertices[indices[:, 0]]
    e2 = vertices[indices[:, 2]] - vertices[indices[:, 0]]
    normals = np.cross(e1, e2)
    norms = np.linalg.norm(normals, axis=1)
    normals /= np.maximum(norms[:, None], 1e-8)
    return (indices, np.asarray(colors, dtype=np.float64), normals)


def render_fast(scene, width, height, *, yaw=.7, pitch=.45, zoom=1.,
                center=(0, 0, 0), normalizer=1., texture_loader=None,
                texture_override=None, category="Character"):
    width=max(100,min(int(width),MAX_WIDTH))
    height=max(88,min(int(height),MAX_HEIGHT))
    key=str(texture_override) if texture_override else ""
    if getattr(scene,"_fast_key",None)!=key:
        scene._fast_data=_face_data(scene,texture_loader,texture_override)
        scene._fast_key=key
    ids, material_colors, normals=scene._fast_data
    base=_background(width,height,category,scene.kind)
    if not scene.faces:
        return base
    projected=_project(scene,width,height,yaw,pitch,zoom,center,normalizer)
    triangle_pixels=projected[ids][:,:,:2]
    inverse_depth=projected[ids,2].mean(axis=1)
    order=np.argsort(inverse_depth,kind="stable")
    # Light follows camera in the sketch pass, so the silhouette remains
    # readable while spinning and backfacing triangles are still present.
    light=np.array((math.sin(yaw)*.35-.2,.65,math.cos(yaw)*.35+.4))
    light/=np.linalg.norm(light)
    intensity=np.clip(.70+.24*(normals@light),.40,.98)
    rgb=np.clip(material_colors*intensity[:,None],0,255).astype(np.uint8)
    finite=np.isfinite(triangle_pixels).all(axis=(1,2))
    safe=np.nan_to_num(triangle_pixels,nan=0.0,posinf=0.0,neginf=0.0)
    within=(safe[:,:,0].max(axis=1)>=0)&(safe[:,:,0].min(axis=1)<=width)&(
            safe[:,:,1].max(axis=1)>=0)&(safe[:,:,1].min(axis=1)<=height)
    pixels=np.clip(np.rint(safe),-1_000_000,1_000_000).astype(np.int32).reshape(-1,6)
    palette=[tuple(int(x) for x in item) for item in rgb]
    draw=ImageDraw.Draw(base)
    for i in order:
        if finite[i] and within[i]:
            draw.polygon(pixels[i].tolist(),fill=palette[i])
    return base