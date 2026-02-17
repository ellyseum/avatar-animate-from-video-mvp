"""
Batch render all animation frames from a GLB file.
Uses Blender's animation render for speed (reuses render engine across frames).

Usage:
    blender -b --python render_animation.py -- \
        --input result.glb \
        --output_dir frames/ \
        --resolution 720x640 \
        --camera 3quarter
"""

import argparse
import math
import os
import sys

import bpy
from mathutils import Vector


CAMERA_PRESETS = {
    "front":    (3.0,  10,   0),
    "side":     (3.0,  10,  90),
    "3quarter": (3.5,  15,  35),
    "top":      (4.0,  75,   0),
}


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


def setup_camera(preset_name, target_center, scene_size):
    distance, elev_deg, azim_deg = CAMERA_PRESETS.get(preset_name, CAMERA_PRESETS["front"])
    distance *= max(scene_size / 1.7, 1.0)
    elev = math.radians(elev_deg)
    azim = math.radians(azim_deg)
    x = distance * math.cos(elev) * math.sin(azim) + target_center[0]
    y = -distance * math.cos(elev) * math.cos(azim) + target_center[1]
    z = distance * math.sin(elev) + target_center[2]

    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 50
    cam_data.clip_start = 0.1
    cam_data.clip_end = 100
    cam_obj = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    cam_obj.location = (x, y, z)
    direction = Vector(target_center) - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = cam_obj


def setup_lighting():
    for name, loc, energy, ltype, color in [
        ("Key",  (2, -2, 3), 300, 'AREA',  (1, 0.95, 0.9)),
        ("Fill", (-2, -1, 2), 100, 'AREA',  (0.85, 0.9, 1)),
        ("Rim",  (0, 2.5, 2.5), 200, 'POINT', (1, 1, 1)),
    ]:
        ld = bpy.data.lights.new(name=name, type=ltype)
        ld.energy = energy
        ld.color = color
        if ltype == 'AREA':
            ld.size = 2.0
        lo = bpy.data.objects.new(name, ld)
        lo.location = loc
        bpy.context.collection.objects.link(lo)


def setup_render(width, height):
    scene = bpy.context.scene
    # Workbench is ~20x faster than EEVEE for simple solid previews
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'JPEG'
    scene.render.image_settings.quality = 90

    # Workbench shading settings
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'SINGLE'
    scene.display.shading.single_color = (0.7, 0.7, 0.72)
    scene.display.shading.background_type = 'THEME'
    scene.display.shading.background_color = (0.12, 0.12, 0.15)

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
    parser.add_argument("--resolution", default="720x640")
    parser.add_argument("--camera", default="3quarter")
    return parser.parse_args(argv)


def main():
    args = parse_args()
    w, h = [int(x) for x in args.resolution.split("x")]

    print(f"Batch render: {args.input} → {args.output_dir} @ {w}x{h}")

    clear_scene()
    imported = import_glb(args.input)

    # Find animation
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

    center, size = get_scene_bounds(imported)
    setup_render(w, h)
    setup_lighting()
    setup_camera(args.camera, center, size)

    os.makedirs(args.output_dir, exist_ok=True)
    bpy.context.scene.render.filepath = os.path.join(args.output_dir, "frame_")

    # Render full animation in one shot (MUCH faster than per-frame)
    bpy.ops.render.render(animation=True)

    print("Batch render complete")


if __name__ == "__main__":
    main()
