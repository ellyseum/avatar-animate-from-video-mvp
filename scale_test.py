"""Render frame 200 at multiple ortho_scale values for quick comparison."""
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

def compute_camera_params(npz_path, img_w, img_h):
    d = np.load(npz_path, allow_pickle=True)
    cameras = d['cameras']
    bbox_tl = d['bbox_top_left']
    bbox_sr = d['bbox_scale_ratio']
    s_avg = cameras[:, 0].mean()
    tx_avg = cameras[:, 1].mean()
    ty_avg = cameras[:, 2].mean()
    sr_avg = bbox_sr.mean()
    tl_avg = bbox_tl.mean(axis=0)
    crop_px = 224.0 / sr_avg
    pix_per_unit = s_avg * crop_px / 2.0
    ortho_scale = img_w / pix_per_unit
    x_crop = (tx_avg + 1) / 2 * 224
    y_crop = (1 - ty_avg) / 2 * 224
    x_img = x_crop / sr_avg + tl_avg[0]
    y_img = y_crop / sr_avg + tl_avg[1]
    visible_w = ortho_scale
    visible_h = ortho_scale * img_h / img_w
    cam_x = -(x_img - img_w / 2) * visible_w / img_w
    cam_z = (y_img - img_h / 2) * visible_h / img_h
    return ortho_scale, cam_x, cam_z

def main():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--npz", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--frame", type=int, default=200)
    parser.add_argument("--scales", default="1.0,1.1,1.15,1.2,1.25,1.3")
    parser.add_argument("--cam_z_adjust", type=float, default=0.0,
                        help="Additional cam_z offset in world units (positive=up)")
    parser.add_argument("--cam_x_adjust", type=float, default=0.0,
                        help="Additional cam_x offset in world units (positive=right)")
    args = parser.parse_args(argv)

    w, h = 360, 640
    scale_factors = [float(x) for x in args.scales.split(",")]

    clear_scene()
    imported = import_glb(args.input)

    armature = None
    for obj in imported:
        if obj.type == 'ARMATURE' and obj.animation_data and obj.animation_data.action:
            armature = obj
            break

    setup_material(imported)
    setup_render(w, h)

    base_ortho, cam_x, cam_z = compute_camera_params(args.npz, w, h)
    print(f"Base ortho_scale: {base_ortho:.4f}, cam_x: {cam_x:.4f}, cam_z: {cam_z:.4f}")

    center = (0, 0, -0.093)

    os.makedirs(args.output_dir, exist_ok=True)
    bpy.context.scene.frame_set(args.frame)

    for sf in scale_factors:
        ortho = base_ortho * sf
        # Recompute cam offsets proportionally + adjustments
        cx = cam_x * sf + args.cam_x_adjust
        cz = cam_z * sf + args.cam_z_adjust

        # Remove old camera
        for obj in bpy.data.objects:
            if obj.type == 'CAMERA':
                bpy.data.objects.remove(obj, do_unlink=True)

        cam_data = bpy.data.cameras.new("Camera")
        cam_data.type = 'ORTHO'
        cam_data.ortho_scale = ortho
        cam_data.clip_start = 0.1
        cam_data.clip_end = 100

        cam_obj = bpy.data.objects.new("Camera", cam_data)
        bpy.context.collection.objects.link(cam_obj)
        cam_obj.location = (center[0] + cx, center[1] - 10, center[2] + cz)
        target = Vector((center[0] + cx, center[1], center[2] + cz))
        direction = target - cam_obj.location
        cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
        bpy.context.scene.camera = cam_obj

        outpath = os.path.join(args.output_dir, f"scale_{sf:.2f}.png")
        bpy.context.scene.render.filepath = outpath
        bpy.ops.render.render(write_still=True)
        print(f"Rendered scale={sf:.2f} (ortho={ortho:.3f}) → {outpath}")

    print("Done")

if __name__ == "__main__":
    main()
