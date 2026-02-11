"""
Render animated GLB as overlay frames (RGBA with transparent background).
Blue mesh matching FrankMocap overlay style, for compositing onto source video.

When --npz is provided, computes camera scale and position from FrankMocap's
weak perspective camera params + bbox, matching the original overlay framing.

Usage:
    blender -b --python render_overlay.py -- \
        --input result.glb \
        --output_dir overlay_frames/ \
        --resolution 360x640 \
        --npz animation_v3.npz
"""

import argparse
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for block in bpy.data.meshes:
        if not block.users:
            bpy.data.meshes.remove(block)


def import_glb(filepath):
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=filepath)
    after = set(bpy.data.objects.keys())
    return [bpy.data.objects[n] for n in after - before]


def setup_material(objects):
    """Apply blue material matching FrankMocap overlay style + smooth shading."""
    mat = bpy.data.materials.new("SMPL_Blue")
    mat.diffuse_color = (0.35, 0.35, 0.85, 1.0)

    for obj in objects:
        if obj.type == 'MESH':
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.shade_smooth()
            obj.select_set(False)
            obj.data.materials.clear()
            obj.data.materials.append(mat)


def get_scene_bounds(objects):
    mins = [float('inf')] * 3
    maxs = [float('-inf')] * 3
    for obj in objects:
        if obj.type != 'MESH':
            continue
        for corner in obj.bound_box:
            world_co = obj.matrix_world @ Vector(corner)
            for i in range(3):
                mins[i] = min(mins[i], world_co[i])
                maxs[i] = max(maxs[i], world_co[i])
    if mins[0] == float('inf'):
        return (0, 0, 0.85), 2.0
    center = tuple((mins[i] + maxs[i]) / 2 for i in range(3))
    size = max(maxs[i] - mins[i] for i in range(3))
    return center, size


def compute_camera_from_npz(npz_path, img_w, img_h):
    """Compute ortho camera settings from FrankMocap's projection data.

    Uses vertex bounding box in image space (if available) for auto-calibration,
    eliminating the need for hardcoded magic numbers. Falls back to weak
    perspective params with empirical corrections when vertex bbox is absent.

    Returns (ortho_scale, cam_x, cam_z) for Blender ortho camera.
    """
    d = np.load(npz_path, allow_pickle=True)
    cameras = d['cameras']            # (N, 3) [s, tx, ty]
    bbox_tl = d['bbox_top_left']      # (N, 2) [x, y]
    bbox_sr = d['bbox_scale_ratio']   # (N,)

    # Common values
    s_avg = cameras[:, 0].mean()
    sr_avg = bbox_sr.mean()
    tl_avg = bbox_tl.mean(axis=0)
    crop_px = 224.0 / sr_avg
    pix_per_unit = s_avg * crop_px / 2.0

    # --- Auto-calibration via vertex bounding box ---
    if 'vertex_bbox_img' in d:
        vbbox = d['vertex_bbox_img']  # (N, 4) [x_min, y_min, x_max, y_max]
        # Average across frames for stable camera
        vb_avg = vbbox.mean(axis=0)
        vb_cx = (vb_avg[0] + vb_avg[2]) / 2.0
        vb_cy = (vb_avg[1] + vb_avg[3]) / 2.0
        vb_h = vb_avg[3] - vb_avg[1]  # height in image pixels

        # Rest-pose mesh height in body units (from NPZ joints)
        joints = d['joints']  # (55, 3) rest-pose
        mesh_h = joints[:, 1].max() - joints[:, 1].min()  # Y extent in body units

        # Ortho scale: how many body units are visible vertically
        # vb_h pixels = mesh_h body units, full image = img_h pixels
        # So: img_h / vb_h * mesh_h = visible body units height
        # ortho_scale = visible width = visible_h * img_w / img_h
        visible_h = (img_h / vb_h) * mesh_h
        ortho_scale = visible_h * img_w / img_h

        # Camera position: mesh center should project to (vb_cx, vb_cy)
        visible_w = ortho_scale
        cam_x = -(vb_cx - img_w / 2) * visible_w / img_w
        cam_z = (vb_cy - img_h / 2) * visible_h / img_h

        print(f"Camera from NPZ (auto-calibrated via vertex bbox):")
        print(f"  vertex bbox avg: ({vb_avg[0]:.1f}, {vb_avg[1]:.1f})-({vb_avg[2]:.1f}, {vb_avg[3]:.1f})")
        print(f"  vertex bbox center: ({vb_cx:.1f}, {vb_cy:.1f}), height: {vb_h:.1f}px")
        print(f"  rest mesh height: {mesh_h:.3f} body units")
        print(f"  ortho_scale={ortho_scale:.3f}, visible_h={visible_h:.3f}")
        print(f"  cam offset: x={cam_x:.3f}, z={cam_z:.3f}")

        return ortho_scale, cam_x, cam_z

    # --- Fallback: weak perspective params + empirical corrections ---
    print("  vertex_bbox_img not in NPZ, using weak perspective fallback")

    tx_avg = cameras[:, 1].mean()
    ty_avg = cameras[:, 2].mean()

    ortho_scale_raw = img_w / pix_per_unit
    SCALE_CORRECTION = 1.45
    ortho_scale = ortho_scale_raw * SCALE_CORRECTION

    x_crop = (tx_avg + 1) / 2 * 224
    y_crop = (1 - ty_avg) / 2 * 224
    x_img = x_crop / sr_avg + tl_avg[0]
    y_img = y_crop / sr_avg + tl_avg[1]

    visible_w = ortho_scale
    visible_h = ortho_scale * img_h / img_w

    cam_x = -(x_img - img_w / 2) * visible_w / img_w
    cam_z = (y_img - img_h / 2) * visible_h / img_h

    CAM_Z_ADJUST = 0.49
    CAM_X_ADJUST = -0.06
    cam_z += CAM_Z_ADJUST
    cam_x += CAM_X_ADJUST

    print(f"Camera from NPZ (fallback with empirical corrections):")
    print(f"  avg s={s_avg:.4f}, tx={tx_avg:.4f}, ty={ty_avg:.4f}")
    print(f"  ortho_scale={ortho_scale:.3f} (raw {ortho_scale_raw:.3f} * {SCALE_CORRECTION})")
    print(f"  cam offset: x={cam_x:.3f}, z={cam_z:.3f}")

    return ortho_scale, cam_x, cam_z


def setup_camera_from_npz(npz_path, center, img_w, img_h, scale_x=1.0):
    """Create orthographic camera matched to FrankMocap's projection.

    When scale_x > 1.0, the GLB has amplified horizontal root translation.
    This adds per-frame camera X keyframes to compensate, so the overlay
    mesh appears at the original (non-amplified) video position.
    """
    ortho_scale, cam_x_offset, cam_z_offset = compute_camera_from_npz(
        npz_path, img_w, img_h
    )

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = ortho_scale
    cam_data.clip_start = 0.1
    cam_data.clip_end = 100

    cam_obj = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam_obj)

    base_x = center[0] + cam_x_offset
    base_y = center[1] - 10
    base_z = center[2] + cam_z_offset

    cam_obj.location = (base_x, base_y, base_z)
    target = Vector((base_x, center[1], base_z))
    direction = target - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    bpy.context.scene.camera = cam_obj

    # Per-frame camera tracking to compensate for root translation amplification.
    # The GLB root moves by root_x * scale_x, but we want overlay to show
    # the mesh at root_x * 1.0. Camera X shifts by root_x * (scale_x - 1.0).
    if scale_x != 1.0:
        d = np.load(npz_path, allow_pickle=True)
        root_trans = d['root_translation']  # (N, 3) in Y-up: (x, y, z=0)
        n_frames = root_trans.shape[0]
        excess_factor = scale_x - 1.0

        # Root X in NPZ Y-up = X in Blender Z-up (unchanged by Y→Z conversion)
        # The GLB amplifies X by scale_x, so excess motion = root_x * (scale_x - 1)
        for i in range(n_frames):
            frame = bpy.context.scene.frame_start + i
            root_x = root_trans[i, 0]
            cam_obj.location.x = base_x + root_x * excess_factor
            cam_obj.keyframe_insert(data_path="location", index=0, frame=frame)

        print(f"  Per-frame camera tracking: {n_frames} keyframes (scale_x={scale_x})")

    return cam_obj


def setup_camera_fallback(center, scene_size, w, h):
    """Fallback: static ortho camera when no NPZ is available."""
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.type = 'ORTHO'
    aspect_ratio = h / w
    cam_data.ortho_scale = scene_size / (0.65 * aspect_ratio)
    cam_data.clip_start = 0.1
    cam_data.clip_end = 100

    cam_obj = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam_obj)

    cam_obj.location = (center[0], center[1] - 10, center[2])
    target = Vector((center[0], center[1], center[2]))
    direction = target - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

    bpy.context.scene.camera = cam_obj
    return cam_obj


def setup_render(w, h):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'MATERIAL'
    scene.display.shading.show_shadows = True
    scene.display.shading.shadow_intensity = 0.3

    world = bpy.data.worlds.new("World")
    scene.world = world


def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--resolution", default="360x640")
    parser.add_argument("--npz", default=None,
                        help="NPZ with cameras/bbox data for matched framing")
    parser.add_argument("--translation_scale_x", type=float, default=1.0,
                        help="GLB root translation X amplification (for camera compensation)")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    w, h = [int(x) for x in args.resolution.split("x")]

    print(f"Overlay render: {args.input} → {args.output_dir} @ {w}x{h}")
    if args.npz:
        print(f"Camera source: {args.npz}")

    clear_scene()
    imported = import_glb(args.input)

    armature = None
    for obj in imported:
        if obj.type == 'ARMATURE' and obj.animation_data and obj.animation_data.action:
            armature = obj
            break

    if armature:
        action = armature.animation_data.action
        start = int(action.frame_range[0])
        end = int(action.frame_range[1])
        bpy.context.scene.frame_start = start
        bpy.context.scene.frame_end = end
        print(f"Animation: frames {start}-{end}")

    setup_material(imported)
    center, size = get_scene_bounds(imported)
    print(f"Scene center: {center}, size: {size:.2f}")

    setup_render(w, h)

    if args.npz and os.path.exists(args.npz):
        setup_camera_from_npz(args.npz, center, w, h,
                              scale_x=args.translation_scale_x)
    else:
        setup_camera_fallback(center, size, w, h)

    os.makedirs(args.output_dir, exist_ok=True)
    bpy.context.scene.render.filepath = os.path.join(args.output_dir, "frame_")

    bpy.ops.render.render(animation=True)
    print("Overlay render complete")


if __name__ == "__main__":
    main()
