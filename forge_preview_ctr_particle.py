"""PS1 CTR native exhaust particle equations, transcribed for 3D model preview.

Sources from the local native-port tree (never edited by this module):
  game/Vehicle/VehEmitter.c   VehEmitter_Exhaust, VehEmitter_ExhaustCustom
  game/zGlobal_DATA.c        emSet_Exhaust_High (axis init arrays)
  game/Particle.c            Particle_InitAxis, Particle_UpdateList,
                             Particle_RenderList_BuildNormalMatrix,
                             Particle_RenderList_WriteNormalPrimitive
  include/namespace_Particle.h (fixed point axis flags)

The original iconGroup[1] is named 'dustpuff': shared.mpk group header
at 0x47ddc has ID=1 and 5 icons. ExhaustHigh has no axis 10 (icon
animation), so the sprite is always icon 0 (dustpuff00). Particles
spawn/die each 30Hz tick; this module never cycles texture frames.

The preview has no game-wide RngDeadCoed state. For axis4 sprite-rotation
randomization only, reproduce MixRNG_Particles' exact negative-512 range
with a stable per-spawn seed. Physics, acceleration, dimensions, color and
lifespan are lifted directly from native source.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

NATIVE_TICKS_PER_SECOND=30
NATIVE_PARTICLE_LIFE=5
PARTICLE_WORLD_SHIFT=6
PARTICLE_WORLD_UNIT=1 << PARTICLE_WORLD_SHIFT
CTR_UNITS_PER_OBJ=(1016.0*1000.0)/4096.0

# game/Vehicle/VehEmitter.c (local exhaust velocity)
EXHAUST_VEL_X=0
EXHAUST_VEL_Y=0x400
EXHAUST_VEL_Z=-0x400

# game/zGlobal_DATA.c emSet_Exhaust_High
PARTICLE_Y_ACCEL=-256
SCALE_X_START=1536
SCALE_X_VELOCITY=400
COLOR_R_START=16384
COLOR_R_VELOCITY=-2560
RANDOM_ROT_Y_START=-512
RANDOM_ROT_Y_VELOCITY=-512
ROT_Y_VELOCITY=256
PSX_ANGLE_PERIOD=4096
DUSTPUFF_ICON=0
DUSTPUFF_ICON_PIXELS=(32,32)

@dataclass(frozen=True)
class NativeExhaustParticle:
    nozzle:int
    birth_tick:int
    age_ticks:int
    center:tuple[float,float,float]
    scale_fixed:int
    shade_byte:int
    rotation_angle:int
    sprite_index:int=DUSTPUFF_ICON


def _signed_random(seed:int, amplitude:int) -> int:
    """MixRNG_Particles's signed mul >>16 with stable local random seed.

    The actual game seeds from global deadcoed_struct; that state is not
    available in an isolated editor. Amplitude and signed conversion match.
    """
    u16=(seed*0x6255+0x3619)&0xffff
    return (u16 * amplitude) >> 16


def native_emitter_particles(exhausts, time_s):
    """Return particles alive for the exact five 30 Hz lifetime ticks.

    Inst local-space mount positions are already corrected by
    forge_offset_guides.build_offset_markers. Nothing mutates kart offsets.
    """
    from forge_preview_retail_fx import rotation_matrix
    tick=max(0,math.floor(float(time_s)*NATIVE_TICKS_PER_SECOND))
    particles=[]
    for nozzle,mark in enumerate(tuple(exhausts or ())[:4]):
        rot=mark.get("rotation")
        if rot is None:
            continue
        origin=tuple(float(v) for v in mark["position"])
        # VehEmitter_RotateLocalExhaustVector rotates the original fixed
        # (0,+0x400,-0x400) by the kart mount's Rz*Ry*Rx local matrix.
        direction=rotation_matrix(rot) @ np.asarray(
            [EXHAUST_VEL_X,EXHAUST_VEL_Y,EXHAUST_VEL_Z],dtype=np.float64)
        velocity=tuple(int(round(v)) for v in direction)
        divisor=float(mark.get("native_units_per_obj",CTR_UNITS_PER_OBJ))
        model_scale=float(mark.get("native_model_scale",1.0))
        denom=divisor*model_scale
        if denom<=0 or not math.isfinite(denom):
            continue
        for age in range(NATIVE_PARTICLE_LIFE):
            birth=tick-age
            if birth<0:
                continue
            # VehEmitter_Exhaust initializes startVal=exhaustPos-exhaustVel.
            # Particle_UpdateList runs once on the creation tick:
            #   pos += vel; vel += accel; scale += 400; color -= 2560.
            # This compensates the -vel spawn offset, so the first visible
            # center is EXACTLY the configured mount. Following positions
            # use the updated velocity (including Y acceleration).
            steps=age+1
            dx=(velocity[0]*age)/PARTICLE_WORLD_UNIT
            dy=(velocity[1]*age+
                PARTICLE_Y_ACCEL*age*(age+1)//2)/PARTICLE_WORLD_UNIT
            dz=(velocity[2]*age)/PARTICLE_WORLD_UNIT
            center=(origin[0]+dx/denom,
                    origin[1]+dy/denom,
                    origin[2]+dz/denom)
            # Exactly emSet_Exhaust_High axis[5] and axis[7] per frame.
            scale=SCALE_X_START+SCALE_X_VELOCITY*steps
            shade=(COLOR_R_START+COLOR_R_VELOCITY*steps)>>8
            # Axis[4] flags=0x1a, base velocity=256; two signed -512
            # random seeds from MixRNG_Particles at creation.
            seed=(birth*7117+(nozzle+1)*3119)&0xffff
            start_rot=_signed_random(seed,RANDOM_ROT_Y_START)
            rot_velocity=ROT_Y_VELOCITY+_signed_random(seed^0xa972,
                                                    RANDOM_ROT_Y_VELOCITY)
            angle=(start_rot+steps*rot_velocity)&(PSX_ANGLE_PERIOD-1)
            particles.append(NativeExhaustParticle(
                nozzle,birth,age,center,scale,shade,angle))
    return particles


def native_smoke_vertex_data(exhausts,time_s,*,yaw=0.0,pitch=0.0,
                             center=(0.0,0.0,0.0),normalizer=2.3):
    """Build PSX FT4 triangles as camera-facing billboards.

    Particle_RenderList_WriteNormalPrimitive:
      halfWidth = icon.width <<1 ; halfHeight=icon.height<<1
    Particle_RenderList_BuildNormalMatrix when axis4+axis5 active:
      R11=2*cos*scale, R12=2*sin*scale,
      R21=-sin*scale, R22=cos*scale
    Color: emSet axis7 color byte (64->54->44->34->24), modulates
      source 'dustpuff00' RGB by color/128, semi-transparent.
    """
    # The GPU uses a PERSPECTIVE projection. Previously ALL particles used
    # the same world-facing normal, which made off-centre quads appear
    # edge-on from oblique angles even though the kart-centre smoke looked OK.
    # Recover the exact camera eye from forge_preview_gpu._FX_VERTEX:
    # worldDepth=(4.8 * normalizer / 2.4) = 2 * normalizer.
    cy,sy=math.cos(yaw),math.sin(yaw)
    cp,sp=math.cos(pitch),math.sin(pitch)
    depth_axis=(-sy*cp,sp,cy*cp)
    camera_right=(cy,0.0,sy)
    records=[]
    for p in native_emitter_particles(exhausts,time_s):
        # Each sprite faces the actual eye position, not a fixed world plane.
        # The centre passed below is supplied in the same OBJ coordinates.
        eye=(float(center[0])+2.0*float(normalizer)*depth_axis[0],
             float(center[1])+2.0*float(normalizer)*depth_axis[1],
             float(center[2])+2.0*float(normalizer)*depth_axis[2])
        look=np.asarray([eye[i]-p.center[i] for i in range(3)],
                        dtype=np.float64)
        norm=np.linalg.norm(look)
        if norm<1e-8:
            look=np.asarray(depth_axis,dtype=np.float64)
        else:
            look/=norm
        # Project the camera's screen-right vector onto the facing plane,
        # keeping particle spin and roll coherent during orbital rotation.
        right=np.asarray(camera_right,dtype=np.float64)
        right-=look*np.dot(right,look)
        right_norm=np.linalg.norm(right)
        if right_norm<1e-8:
            right=np.cross((0.0,1.0,0.0),look)
            right_norm=np.linalg.norm(right)
        right/=max(right_norm,1e-8)
        up=np.cross(look,right)
        mark=exhausts[p.nozzle]
        divisor=float(mark.get("native_units_per_obj",CTR_UNITS_PER_OBJ))
        model_scale=float(mark.get("native_model_scale",1.0))
        unit=divisor*model_scale
        scale=p.scale_fixed/4096.0
        theta=p.rotation_angle*2.0*math.pi/PSX_ANGLE_PERIOD
        c,s=math.cos(theta),math.sin(theta)
        half_w=DUSTPUFF_ICON_PIXELS[0]<<1
        half_h=DUSTPUFF_ICON_PIXELS[1]<<1
        shade=min(1.0,max(0.0,p.shade_byte/128.0))
        corners=[]
        # X is twice as wide in PS1's original particle transform.
        for x,y,u,v in ((-half_w,-half_h,0.,0.),
                        (half_w,-half_h,1.,0.),
                        (-half_w,half_h,0.,1.),
                        (half_w,half_h,1.,1.)):
            x_world=(2*c*x+2*s*y)*scale/unit
            y_world=(-s*x+c*y)*scale/unit
            corners.append((
                p.center[0]+right[0]*x_world+up[0]*y_world,
                p.center[1]+right[1]*x_world+up[1]*y_world,
                p.center[2]+right[2]*x_world+up[2]*y_world,
                u,v,shade,shade,shade))
        for i in (0,1,2, 1,3,2):
            records.append(corners[i])
    return np.asarray(records,dtype=np.float32).reshape((-1,8))


def native_smoke_quad_span(exhausts,time_s):
    """Viewport-independent quad width in OBJ units, used by regression tests."""
    p=native_emitter_particles(exhausts,time_s)
    return tuple(8*DUSTPUFF_ICON_PIXELS[0]*
                 (x.scale_fixed/4096.0)/
                 (float(exhausts[x.nozzle].get("native_units_per_obj",CTR_UNITS_PER_OBJ))*
                  float(exhausts[x.nozzle].get("native_model_scale",1.0)))
                 for x in p)


def native_smoke_screen_vertices(exhausts, time_s):
    """Prepare native CTR smoke as 2D GTE-like camera-facing FT4 quads.

    Each vertex carries the SAME 3D emitter centre and a small rotated local
    offset in units of the original OBJ. The smoke-specific GPU vertex shader
    applies that offset AFTER projection. Thus every native sprite always
    faces the screen: no skew/polygon angle as the user rotates the camera,
    even at extreme off-axis positions or wide-angle viewpoints.

    Only geometry presentation is changed; native_emitter_particles retains
    its source-authentic 30Hz age, motion, acceleration, growth and tint.
    """
    records=[]
    for p in native_emitter_particles(exhausts, time_s):
        mark=exhausts[p.nozzle]
        unit=float(mark.get("native_units_per_obj",CTR_UNITS_PER_OBJ))*(
            float(mark.get("native_model_scale",1.0)))
        if unit<=0 or not math.isfinite(unit):
            continue
        scale=p.scale_fixed/4096.0
        theta=p.rotation_angle*2*math.pi/PSX_ANGLE_PERIOD
        c,s=math.cos(theta),math.sin(theta)
        half_x=DUSTPUFF_ICON_PIXELS[0]<<1
        half_y=DUSTPUFF_ICON_PIXELS[1]<<1
        shade=min(1.,max(0.,p.shade_byte/128.))
        corners=[]
        for x,y,u,v in ((-half_x,-half_y,0.,0.),
                        (half_x,-half_y,1.,0.),
                        (-half_x,half_y,0.,1.),
                        (half_x,half_y,1.,1.)):
            dx=(2*c*x+2*s*y)*scale/unit
            dy=(-s*x+c*y)*scale/unit
            corners.append((*p.center,u,v,shade,shade,shade,dx,dy))
        for index in (0,1,2, 1,3,2):
            records.append(corners[index])
    return np.asarray(records,dtype=np.float32).reshape((-1,10))