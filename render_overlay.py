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
    imported = [bpy.data.objects[n] for n in after - before]

    # Delete stray meshes not parented to an armature (e.g. Icosphere artifacts)
    stray_names = set()
    for o in imported:
        if o.type == 'MESH' and (o.parent is None or o.parent.type != 'ARMATURE'):
            stray_names.add(o.name)
            print(f"  Deleting stray mesh: {o.name} ({len(o.data.vertices)} verts)")
            bpy.data.objects.remove(o, do_unlink=True)
    imported = [bpy.data.objects[n] for n in (after - before) - stray_names
                if n in bpy.data.objects]

    return imported


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
    """Get scene bounds from DEFORMED mesh via depsgraph (not rest-pose bound_box).

    bound_box returns rest-pose coordinates which can be wildly different from
    the animated pose (e.g. SMPL rest-pose center Z = -0.5 vs frame-0 = +0.9).
    """
    # Evaluate depsgraph to get actual deformed vertex positions
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()

    mins = [float('inf')] * 3
    maxs = [float('-inf')] * 3
    for obj in objects:
        if obj.type != 'MESH':
            continue
        if obj.parent is None or obj.parent.type != 'ARMATURE':
            continue
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        for v in mesh.vertices:
            world_co = eval_obj.matrix_world @ v.co
            for i in range(3):
                mins[i] = min(mins[i], world_co[i])
                maxs[i] = max(maxs[i], world_co[i])
        eval_obj.to_mesh_clear()

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

        # Rest-pose mesh height in Blender units (vertices Y extent in Y-up = Z extent in Blender)
        # Use vertices, not joints — vertices include skin/hair/feet beyond joint positions
        verts = d['vertices']  # (V, 3) rest-pose in Y-up
        mesh_h = verts[:, 1].max() - verts[:, 1].min()  # Y extent = Blender Z height

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


def get_mesh_center_at_frame(objects, frame):
    """Evaluate depsgraph at a specific frame and return the mesh bbox center."""
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()

    mins = [float('inf')] * 3
    maxs = [float('-inf')] * 3
    for obj in objects:
        if obj.type != 'MESH':
            continue
        if obj.parent is None or obj.parent.type != 'ARMATURE':
            continue
        eval_obj = obj.evaluated_get(depsgraph)
        mesh = eval_obj.to_mesh()
        for v in mesh.vertices:
            world_co = eval_obj.matrix_world @ v.co
            for i in range(3):
                mins[i] = min(mins[i], world_co[i])
                maxs[i] = max(maxs[i], world_co[i])
        eval_obj.to_mesh_clear()

    if mins[0] == float('inf'):
        return None
    return tuple((mins[i] + maxs[i]) / 2 for i in range(3))


def find_vertex_bbox_npz(npz_path):
    """Find vertex_bbox_img data. Checks the given NPZ first, then sibling NPZs."""
    d = np.load(npz_path, allow_pickle=True)
    if 'vertex_bbox_img' in d:
        return d['vertex_bbox_img'], d

    # Search sibling NPZ files (e.g. animation.npz may have it)
    npz_dir = os.path.dirname(npz_path)
    for name in ['animation.npz', 'animation_v4.npz', 'animation_v3.npz']:
        candidate = os.path.join(npz_dir, name)
        if candidate != npz_path and os.path.exists(candidate):
            cd = np.load(candidate, allow_pickle=True)
            if 'vertex_bbox_img' in cd:
                print(f"  Found vertex_bbox_img in sibling: {name}")
                return cd['vertex_bbox_img'], cd
    return None, d


def setup_camera_from_npz(npz_path, objects, img_w, img_h, scale_x=1.0):
    """Create orthographic camera matched to FrankMocap's weak perspective.

    Uses per-frame depsgraph evaluation to compute actual mesh center positions,
    combined with vertex_bbox_img targets for pixel-accurate camera tracking.
    Works correctly for any mesh (SMPL, Mixamo, etc.) since it measures the
    actual deformed mesh rather than approximating from root translation.
    """
    d = np.load(npz_path, allow_pickle=True)
    vbbox, vbbox_src = find_vertex_bbox_npz(npz_path)

    # Compute base camera params (used as initial values and fallback)
    ortho_scale, cam_x_offset, cam_z_offset = compute_camera_from_npz(
        npz_path, img_w, img_h
    )

    # Get frame 0 center for initial camera position
    center, _ = get_scene_bounds(objects)

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = ortho_scale
    cam_data.sensor_fit = 'HORIZONTAL'
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

    if vbbox is None:
        print("  WARNING: No vertex_bbox_img found — using static camera")
        return cam_obj

    n_frames = vbbox.shape[0]

    # SMPL rest-pose mesh height (from NPZ vertices) — used for scale computation.
    # This is always SMPL height regardless of which mesh we're rendering, because
    # vertex_bbox_img was computed from SMPL vertices.
    verts_src = vbbox_src['vertices'] if 'vertices' in vbbox_src else d['vertices']
    mesh_h = verts_src[:, 1].max() - verts_src[:, 1].min()

    # Pre-compute actual mesh centers at each frame via depsgraph evaluation.
    # This replaces the broken approximation (center_f0 + root_trans_delta)
    # which can be off by 36+ pixels because root_translation doesn't capture
    # pose-induced center shifts (leaning, arm extension, jumping).
    print(f"  Computing per-frame mesh centers ({n_frames} frames)...")
    mesh_centers = []
    frame_start = bpy.context.scene.frame_start
    for i in range(n_frames):
        frame = frame_start + i
        mc = get_mesh_center_at_frame(objects, frame)
        mesh_centers.append(mc)
        if i % 100 == 0:
            print(f"    Frame {i}/{n_frames}: center=({mc[0]:.4f}, {mc[2]:.4f})")

    # Keyframe camera per frame
    for i in range(n_frames):
        frame = frame_start + i
        mc = mesh_centers[i]
        if mc is None:
            continue

        vb_cx = (vbbox[i, 0] + vbbox[i, 2]) / 2.0
        vb_cy = (vbbox[i, 1] + vbbox[i, 3]) / 2.0
        vb_h = vbbox[i, 3] - vbbox[i, 1]

        if vb_h < 10:
            continue

        # Per-frame ortho_scale from vertex_bbox height
        visible_h = (img_h / vb_h) * mesh_h
        frame_ortho = visible_h * img_w / img_h
        cam_data.ortho_scale = frame_ortho
        cam_data.keyframe_insert(data_path="ortho_scale", frame=frame)

        visible_w = frame_ortho

        # Camera position: project actual mesh center to vertex_bbox pixel target.
        # Ortho: pixel_x = img_w/2 + (world_x - cam_x) * img_w / visible_w
        # Solve for cam_x: cam_x = world_x - (target_px - img_w/2) * visible_w / img_w
        cam_x = mc[0] - (vb_cx - img_w / 2.0) * visible_w / img_w
        cam_z = mc[2] + (vb_cy - img_h / 2.0) * visible_h / img_h

        cam_obj.location.x = cam_x
        cam_obj.keyframe_insert(data_path="location", index=0, frame=frame)
        cam_obj.location.z = cam_z
        cam_obj.keyframe_insert(data_path="location", index=2, frame=frame)

    # Set keyframe interpolation to LINEAR for all animation data
    for ad in [cam_obj.animation_data, cam_data.animation_data]:
        if ad and ad.action:
            try:
                fcs = ad.action.fcurves
            except AttributeError:
                # Blender 5.0 layered actions
                fcs = []
                for layer in ad.action.layers:
                    for strip in layer.strips:
                        for cb in strip.channelbags:
                            fcs.extend(cb.fcurves)
            for fc in fcs:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'

    print(f"  Per-frame camera tracking: {n_frames} frames "
          f"(depsgraph mesh center + vertex_bbox_img target)")

    return cam_obj


def setup_camera_fallback(center, scene_size, w, h):
    """Fallback: static ortho camera when no NPZ is available."""
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.type = 'ORTHO'
    aspect_ratio = h / w
    cam_data.ortho_scale = scene_size / (0.65 * aspect_ratio)
    cam_data.sensor_fit = 'HORIZONTAL'  # ortho_scale = visible width (not height)
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


def setup_render(w, h, use_eevee=False):
    scene = bpy.context.scene
    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    if use_eevee:
        # EEVEE for textured Mixamo models (Workbench can't do PBR textures)
        try:
            scene.render.engine = 'BLENDER_EEVEE_NEXT'
        except TypeError:
            scene.render.engine = 'BLENDER_EEVEE'
        try:
            scene.eevee.taa_render_samples = 16
        except AttributeError:
            pass

        # Add key + fill lights so Mixamo characters aren't silhouettes
        key = bpy.data.lights.new("KeyLight", 'SUN')
        key.energy = 3.0
        key_obj = bpy.data.objects.new("KeyLight", key)
        bpy.context.collection.objects.link(key_obj)
        key_obj.rotation_euler = (0.8, 0.2, -0.5)  # ~45° from above-front-left

        fill = bpy.data.lights.new("FillLight", 'SUN')
        fill.energy = 1.5
        fill_obj = bpy.data.objects.new("FillLight", fill)
        bpy.context.collection.objects.link(fill_obj)
        fill_obj.rotation_euler = (1.0, -0.3, 0.8)  # from above-front-right
    else:
        # Workbench for fast SMPL overlay rendering
        scene.render.engine = 'BLENDER_WORKBENCH'
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
    parser.add_argument("--preserve-materials", action="store_true",
                        help="Keep imported GLB materials (for Mixamo characters)")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    w, h = [int(x) for x in args.resolution.split("x")]

    print(f"Overlay render: {args.input} → {args.output_dir} @ {w}x{h}")
    if args.npz:
        print(f"Camera source: {args.npz}")

    clear_scene()

    # Set FPS before import — GLB stores time in seconds, so Blender converts
    # to frames using scene FPS. Must match the animation's original FPS.
    if args.npz:
        npz_data = np.load(args.npz, allow_pickle=True)
        fps = int(npz_data['fps']) if 'fps' in npz_data else 30
        bpy.context.scene.render.fps = fps
        bpy.context.scene.render.fps_base = 1.0
        print(f"Scene FPS set to {fps} (from NPZ)")

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

    if not args.preserve_materials:
        setup_material(imported)
    else:
        # Still apply smooth shading to meshes, but keep their materials
        for obj in imported:
            if obj.type == 'MESH':
                bpy.context.view_layer.objects.active = obj
                obj.select_set(True)
                bpy.ops.object.shade_smooth()
                obj.select_set(False)
        print("  Preserving original materials")

    center, size = get_scene_bounds(imported)
    print(f"Scene center: {center}, size: {size:.2f}")

    setup_render(w, h, use_eevee=args.preserve_materials)

    if args.npz and os.path.exists(args.npz):
        setup_camera_from_npz(args.npz, imported, w, h,
                              scale_x=args.translation_scale_x)
    else:
        setup_camera_fallback(center, size, w, h)

    os.makedirs(args.output_dir, exist_ok=True)
    bpy.context.scene.render.filepath = os.path.join(args.output_dir, "frame_")

    bpy.ops.render.render(animation=True)
    print("Overlay render complete")


if __name__ == "__main__":
    main()
