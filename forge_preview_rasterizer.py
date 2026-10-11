"""UV-correct and depth-tested software preview for native Crash Forge models.

Unlike the older renderer, this rasterizes texture pixels across every OBJ
triangle using its 3 UV coordinates. Shared by Model Importer and Mod Packager.
Only decodes mesh/atlas files for viewing; it never modifies mod assets.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

MAX_WIDTH = 1200
MAX_HEIGHT = 780
MAX_PREVIEW_TRIANGLES = 8000

BACKGROUND = (12, 20, 29)


def _background(w, h, category, kind):
    image = Image.new("RGB", (w, h), BACKGROUND)
    draw = ImageDraw.Draw(image)
    for x in range(0, w, 37):
        draw.line((x, h - 13, x + 48, h - 53), fill=(28, 43, 54), width=1)
    draw.line((0, h - 13, w, h - 13), fill=(39, 60, 69))
    return image


def _project(scene, width, height, yaw, pitch, zoom, center, normalizer):
    points = np.asarray(scene.vertices, dtype=np.float64)
    points -= np.asarray(center, dtype=np.float64)
    points *= (2.4 / max(1e-5, normalizer))
    c, s = math.cos(yaw), math.sin(yaw)
    cp, sp = math.cos(pitch), math.sin(pitch)
    rotated_x = c * points[:, 0] + s * points[:, 2]
    rotated_z = -s * points[:, 0] + c * points[:, 2]
    rotated_y = cp * points[:, 1] - sp * rotated_z
    depth = sp * points[:, 1] + cp * rotated_z
    camera = np.maximum(0.35, 4.8 - depth)
    reciprocal = 1.0 / camera
    # Fit the model with a little breathing room in small fixed-height panels.
    size = min(width, height) * 1.33 * max(0.2, min(6.0, zoom))
    projected = np.column_stack((
        width / 2.0 + size * rotated_x * reciprocal,
        height / 2.0 - size * rotated_y * reciprocal,
        reciprocal))
    return projected


def render_scene(scene, width, height, *, yaw=.7, pitch=.45, zoom=1.0,
                 center=(0.0, 0.0, 0.0), normalizer=1.0,
                 texture_loader=None, texture_override=None, category="Character"):
    """Return a PIL RGB preview. Texture loader: callable(Path) -> PIL Image | None.

    The depth buffer prevents overlapping faces from painting over nearer skin.
    Perspective-correct UV interpolation avoids face-sized blotches.
    """
    width = max(100, min(int(width), MAX_WIDTH))
    height = max(88, min(int(height), MAX_HEIGHT))
    base = np.asarray(_background(width, height, category, scene.kind)).copy()
    if not scene.vertices or not scene.faces:
        return Image.fromarray(base, mode="RGB")
    vertices = _project(scene, width, height, yaw, pitch, zoom, center, normalizer)
    zbuffer = np.zeros((height, width), dtype=np.float32)
    images = {}
    uvs = scene.uvs
    colors = scene.colors
    faces = scene.faces
    stride = max(1, math.ceil(len(faces) / MAX_PREVIEW_TRIANGLES))

    def get_tex(material):
        source = texture_override or scene.textures.get(material)
        if not source or texture_loader is None:
            return None
        key = str(source)
        if key not in images:
            try:
                pil = texture_loader(source)
                images[key] = (np.asarray(pil.convert("RGB")) if pil else None)
            except (OSError, ValueError, TypeError):
                images[key] = None
        return images[key]

    for face in faces[::stride]:
        ia, ib, ic, ua, ub, uc, material = face
        xyz = vertices[[ia, ib, ic]]
        px, py, perspective = xyz[:, 0], xyz[:, 1], xyz[:, 2]
        min_x = max(0, int(math.floor(float(np.min(px)))))
        max_x = min(width - 1, int(math.ceil(float(np.max(px)))))
        min_y = max(0, int(math.floor(float(np.min(py)))))
        max_y = min(height - 1, int(math.ceil(float(np.max(py)))))
        if min_x > max_x or min_y > max_y:
            continue
        denom = (py[1] - py[2]) * (px[0] - px[2]) + (
            px[2] - px[1]) * (py[0] - py[2])
        if not math.isfinite(float(denom)) or abs(denom) < 1e-7:
            continue
        xx = np.arange(min_x, max_x + 1, dtype=np.float32)[None, :] + .5
        yy = np.arange(min_y, max_y + 1, dtype=np.float32)[:, None] + .5
        w0 = ((py[1]-py[2])*(xx-px[2])+(px[2]-px[1])*(yy-py[2]))/denom
        w1 = ((py[2]-py[0])*(xx-px[2])+(px[0]-px[2])*(yy-py[2]))/denom
        w2 = 1 - w0 - w1
        mask = ((w0 >= -1e-5) & (w1 >= -1e-5) & (w2 >= -1e-5))
        if not mask.any():
            continue
        inv_depth = (w0*perspective[0] + w1*perspective[1] +
                     w2*perspective[2])
        local_depth = zbuffer[min_y:max_y+1, min_x:max_x+1]
        mask &= inv_depth > local_depth + 1e-7
        if not mask.any():
            continue
        ys, xs = np.nonzero(mask)
        # Work only on visible pixels. This matters on crowded tracks.
        b0, b1, b2 = w0[ys,xs], w1[ys,xs], w2[ys,xs]
        depth = inv_depth[ys,xs]

        tex = get_tex(material) if not colors else None
        valid_uv = (tex is not None and
                    ua is not None and ub is not None and uc is not None and
                    0 <= ua < len(uvs) and 0 <= ub < len(uvs) and
                    0 <= uc < len(uvs))
        if valid_uv:
            th, tw = tex.shape[:2]
            uv0, uv1, uv2 = uvs[ua], uvs[ub], uvs[uc]
            q0, q1, q2 = b0*perspective[0], b1*perspective[1], b2*perspective[2]
            uv_x = (q0*uv0[0] + q1*uv1[0] + q2*uv2[0]) / depth
            uv_y = (q0*uv0[1] + q1*uv1[1] + q2*uv2[1]) / depth
            # Wavefront V origin is bottom-left; Pillow PNG origin is top-left.
            # Repeat when a model deliberately uses UV outside [0,1].
            tx = np.minimum(tw-1, (np.mod(uv_x, 1.0) * tw).astype(np.int32))
            ty = np.minimum(th-1, (np.mod(1.0-uv_y, 1.0) * th).astype(np.int32))
            rgb = tex[ty, tx]
        elif colors:
            vertex_colors = np.asarray(
                [colors[ia], colors[ib], colors[ic]], dtype=np.float32)
            rgb = (b0[:, None] * vertex_colors[0] +
                   b1[:, None] * vertex_colors[1] +
                   b2[:, None] * vertex_colors[2])
        else:
            rgb = np.broadcast_to(np.asarray(
                [163, 176, 189] if scene.kind == "OBJ" else [116, 146, 164],
                dtype=np.float32), (len(xs), 3))

        base[min_y + ys, min_x + xs] = np.clip(
            np.asarray(rgb, dtype=np.float32)*.98 + 2, 0, 255).astype(np.uint8)
        local_depth[ys, xs] = depth.astype(np.float32)

    result = Image.fromarray(base, mode="RGB")
    draw = ImageDraw.Draw(result)
    draw.text((9, 8), str(category).upper()+"  /  "+scene.kind+"  /  TEXTURED PREVIEW",
              fill=(255, 161, 85))
    return result
