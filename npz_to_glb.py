"""
NPZ-to-GLB Converter — Skinned Animated Avatar

Builds a complete animated GLB from SMPL/SMPL-X data exported by pkl_to_npz.py:
  - Creates mesh from vertices/faces (6890 SMPL or 10475 SMPL-X)
  - Creates armature with actual joint positions (24 or 55 bones)
  - Applies LBS skinning weights as vertex groups
  - Keyframes quaternion rotations (identity rest = direct application)
  - Exports GLB with animation

Supports both SMPL (24 joints, body only) and SMPL-X (55 joints, body + hands).
Joint count is auto-detected from the NPZ data.

Runs inside the blender-headless Docker container.

Usage:
    blender -b --python npz_to_glb.py -- \
        --input /workspace/animation.npz \
        --output /workspace/result.glb
"""

import argparse
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector


# ============================================================================
# Y-up → Blender Z-up Coordinate Conversion
# ============================================================================
# SMPL data is Y-up. Blender is Z-up. Convert before building the scene,
# then export_yup=True in the glTF exporter converts Z-up back to Y-up.
#
# Position transform: (x, y, z)_yup → (x, -z, y)_zup
# Quaternion transform (derived from conjugation by -90° X rotation):
#   (w, x, y, z)_yup → (w, x, z, -y)_zup

def yup_to_zup_positions(arr):
    """Convert (N, 3) positions from Y-up to Blender Z-up."""
    out = np.empty_like(arr)
    out[:, 0] = arr[:, 0]
    out[:, 1] = -arr[:, 2]
    out[:, 2] = arr[:, 1]
    return out


def yup_to_zup_quaternions(quats):
    """Convert (N, J, 4) quaternions [w,x,y,z] from Y-up to Blender Z-up.

    Derived from q_new = q_M^{-1} @ q_old @ q_M where q_M is -90° around X.
    Result: (w, x, y, z) → (w, x, -z, y)
    """
    out = np.empty_like(quats)
    out[..., 0] = quats[..., 0]    # w
    out[..., 1] = quats[..., 1]    # x
    out[..., 2] = -quats[..., 3]   # -z → new y
    out[..., 3] = quats[..., 2]    # y → new z
    return out


# ============================================================================
# Mesh Creation
# ============================================================================

def create_mesh(vertices, faces, name="SMPL_Body"):
    """Create a Blender mesh from vertices and faces.

    Args:
        vertices: (V, 3) float array
        faces: (F, 3) int array (triangle indices)
        name: Object name

    Returns:
        bpy.types.Object — the mesh object
    """
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(
        vertices.tolist(),
        [],  # edges (auto-generated)
        faces.tolist(),
    )
    mesh.update()

    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    # Smooth shading — kills the faceted look
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.shade_smooth()
    obj.select_set(False)

    # Subdivision surface (level 1) — doubles poly count but much smoother silhouette.
    # Applied as modifier so it exports into the GLB geometry.
    mod = obj.modifiers.new(name="Subsurf", type='SUBSURF')
    mod.levels = 1
    mod.render_levels = 1

    return obj


# ============================================================================
# Armature Creation
# ============================================================================

def create_armature(joints, parent_indices, joint_names, name="SMPL_Armature"):
    """Create a Blender armature matching joint positions.

    All bones point along +Y with a small offset so their rest frame aligns
    with the global frame (identity rotation). This matches SMPL/SMPL-X's
    convention where all joints share the parent's orientation in rest pose,
    so rotations can be applied directly without rest-pose compensation.

    Works for both SMPL (24 joints) and SMPL-X (55 joints).

    Args:
        joints: (J, 3) rest-pose joint positions (already in Z-up)
        parent_indices: (J,) parent index per joint (-1 = root)
        joint_names: (J,) joint name strings

    Returns:
        bpy.types.Object — the armature object
    """
    n_joints = len(joint_names)

    armature = bpy.data.armatures.new(name)
    arm_obj = bpy.data.objects.new(name, armature)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj

    # Must be in edit mode to create bones
    bpy.ops.object.mode_set(mode='EDIT')

    bones = {}
    for i in range(n_joints):
        bone = armature.edit_bones.new(str(joint_names[i]))
        head = Vector(joints[i].tolist())
        bone.head = head
        # Smaller offset for finger bones (index 25+) to avoid overlap
        offset = 0.005 if i >= 25 else 0.02
        bone.tail = head + Vector((0, offset, 0))
        bone.roll = 0.0
        bones[i] = bone

    # Set parents
    for i in range(n_joints):
        if parent_indices[i] >= 0:
            bones[i].parent = bones[parent_indices[i]]

    bpy.ops.object.mode_set(mode='OBJECT')
    return arm_obj


# ============================================================================
# Skinning (Vertex Groups)
# ============================================================================

def apply_skinning(mesh_obj, arm_obj, weights, joint_names):
    """Apply LBS weights as vertex groups and set armature modifier.

    Args:
        mesh_obj: The mesh object
        arm_obj: The armature object
        weights: (V, J) skinning weights
        joint_names: (J,) joint name strings
    """
    n_verts, n_joints = weights.shape

    # Create vertex groups matching bone names
    for j in range(n_joints):
        name = str(joint_names[j])
        mesh_obj.vertex_groups.new(name=name)

    # Assign weights — only add non-zero weights for efficiency
    for j in range(n_joints):
        vg = mesh_obj.vertex_groups[j]
        joint_weights = weights[:, j]
        nonzero = np.nonzero(joint_weights > 1e-6)[0]
        for vi in nonzero:
            vg.add([int(vi)], float(joint_weights[vi]), 'REPLACE')

    # Add armature modifier
    mod = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')
    mod.object = arm_obj

    # Parent mesh to armature (without auto-weights!)
    mesh_obj.parent = arm_obj


# ============================================================================
# Keyframing
# ============================================================================

def keyframe_animation(arm_obj, rotations, joint_names, fps, root_translation=None):
    """Apply quaternion keyframes directly to pose bones.

    Because all bones have identity rest orientation (+Y forward), rotations
    apply directly as pose_bone.rotation_quaternion — no rest-pose compensation.

    Args:
        arm_obj: The armature object
        rotations: (N, J, 4) quaternions [w, x, y, z] (already Z-up converted)
        joint_names: (J,) joint name strings
        fps: Frame rate
        root_translation: (N, 3) optional root translation (already Z-up converted)
    """
    n_frames, n_joints, _ = rotations.shape

    # Set up animation
    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = n_frames - 1
    bpy.context.scene.render.fps = int(fps)

    # Create action
    action = bpy.data.actions.new(name="SMPL_Animation")
    arm_obj.animation_data_create()
    arm_obj.animation_data.action = action

    # Switch all pose bones to quaternion rotation mode
    for bone_name in joint_names:
        pb = arm_obj.pose.bones.get(str(bone_name))
        if pb:
            pb.rotation_mode = 'QUATERNION'

    print(f"Keyframing {n_frames} frames × {n_joints} joints...")

    # Batch keyframe insertion using fcurves for performance
    fcurves = {}
    for j in range(n_joints):
        bone_name = str(joint_names[j])
        pb = arm_obj.pose.bones.get(bone_name)
        if not pb:
            continue
        data_path = f'pose.bones["{bone_name}"].rotation_quaternion'
        bone_fcurves = []
        for ch in range(4):  # w, x, y, z
            fc = action.fcurves.new(data_path=data_path, index=ch)
            fc.keyframe_points.add(n_frames)
            bone_fcurves.append(fc)
        fcurves[j] = bone_fcurves

    # Root translation fcurves (location keyframes on Hips bone)
    loc_fcurves = None
    if root_translation is not None:
        root_name = str(joint_names[0])  # "Hips"
        pb = arm_obj.pose.bones.get(root_name)
        if pb:
            data_path = f'pose.bones["{root_name}"].location'
            loc_fcurves = []
            for ch in range(3):  # x, y, z
                fc = action.fcurves.new(data_path=data_path, index=ch)
                fc.keyframe_points.add(n_frames)
                loc_fcurves.append(fc)
            print(f"  Adding root translation keyframes to {root_name}")

    # Fill keyframe data — direct SMPL quaternions, no compensation
    for j in range(n_joints):
        if j not in fcurves:
            continue
        for frame in range(n_frames):
            w, x, y, z = rotations[frame, j]
            for ch, val in enumerate([w, x, y, z]):
                kf = fcurves[j][ch].keyframe_points[frame]
                kf.co = (frame, val)
                kf.interpolation = 'LINEAR'

    # Fill root translation keyframes
    if loc_fcurves is not None:
        for frame in range(n_frames):
            for ch in range(3):
                kf = loc_fcurves[ch].keyframe_points[frame]
                kf.co = (frame, float(root_translation[frame, ch]))
                kf.interpolation = 'LINEAR'

    # Update fcurves
    for j in fcurves:
        for fc in fcurves[j]:
            fc.update()
    if loc_fcurves is not None:
        for fc in loc_fcurves:
            fc.update()

    print(f"Animation: {n_frames} frames at {fps} fps "
          f"({n_frames / fps:.1f}s)")


# ============================================================================
# Export
# ============================================================================

def apply_subdivision(mesh_obj):
    """Apply the Subsurf modifier so it bakes into exported geometry."""
    bpy.context.view_layer.objects.active = mesh_obj
    mesh_obj.select_set(True)
    for mod in mesh_obj.modifiers:
        if mod.type == 'SUBSURF':
            bpy.ops.object.modifier_apply(modifier=mod.name)
            break
    mesh_obj.select_set(False)


def export_glb(output_path):
    """Export scene as GLB with animations and skinning."""
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format='GLB',
        export_yup=True,
        export_animations=True,
        export_skins=True,
        export_all_influences=True,
        export_morph=False,
        export_lights=False,
        export_cameras=False,
    )
    file_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Exported: {output_path} ({file_size:.1f} MB)")


# ============================================================================
# Main
# ============================================================================

def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        description="Build animated skinned GLB from SMPL NPZ data"
    )
    parser.add_argument(
        "--input", required=True,
        help="Input .npz file from pkl_to_npz.py"
    )
    parser.add_argument(
        "--output", required=True,
        help="Output .glb file path"
    )
    parser.add_argument(
        "--translation_scale_x", type=float, default=1.4,
        help="Multiplier for root X translation (default: 1.4)"
    )
    parser.add_argument(
        "--translation_scale_y", type=float, default=1.0,
        help="Multiplier for root Y translation (default: 1.0)"
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()

    print("=" * 60)
    print("NPZ-to-GLB Converter")
    print("=" * 60)
    print(f"Input:  {args.input}")
    print(f"Output: {args.output}")
    print("=" * 60)

    # Load NPZ
    data = np.load(args.input, allow_pickle=True)
    vertices = data["vertices"]       # (V, 3)
    faces = data["faces"]             # (F, 3)
    joints = data["joints"]           # (24, 3)
    weights = data["weights"]         # (V, 24)
    rotations = data["rotations"]     # (N, 24, 4) [w, x, y, z]
    parent = data["parent"]           # (24,)
    joint_names = data["joint_names"] # (24,)
    fps = float(data["fps"])

    # Root translation (optional — may not exist in older NPZ files)
    root_translation = None
    if "root_translation" in data:
        root_translation = data["root_translation"].copy()  # (N, 3)
        root_translation[:, 0] *= args.translation_scale_x
        root_translation[:, 1] *= args.translation_scale_y
        print(f"  Root trans: {root_translation.shape} "
              f"(X={args.translation_scale_x}x, Y={args.translation_scale_y}x)")

    print(f"  Vertices:   {vertices.shape}")
    print(f"  Faces:      {faces.shape}")
    print(f"  Joints:     {joints.shape}")
    print(f"  Weights:    {weights.shape}")
    print(f"  Rotations:  {rotations.shape}")
    print(f"  FPS:        {fps}")

    # Convert from SMPL Y-up to Blender Z-up
    print("\nConverting Y-up → Z-up...")
    vertices = yup_to_zup_positions(vertices)
    joints = yup_to_zup_positions(joints)
    rotations = yup_to_zup_quaternions(rotations)
    if root_translation is not None:
        root_translation = yup_to_zup_positions(root_translation)

    # Clear default scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    # Step 1: Create mesh
    print("\n[1/5] Creating mesh...")
    mesh_obj = create_mesh(vertices, faces)
    print(f"  Mesh: {len(mesh_obj.data.vertices)} verts, "
          f"{len(mesh_obj.data.polygons)} faces")

    # Step 2: Create armature
    print("[2/5] Creating armature...")
    arm_obj = create_armature(joints, parent, joint_names)
    print(f"  Armature: {len(arm_obj.data.bones)} bones")

    # Step 3: Apply skinning
    print("[3/5] Applying skinning weights...")
    apply_skinning(mesh_obj, arm_obj, weights, joint_names)
    print(f"  Vertex groups: {len(mesh_obj.vertex_groups)}")

    # Step 4: Keyframe animation (rotations + root translation)
    print("[4/5] Keyframing animation...")
    keyframe_animation(arm_obj, rotations, joint_names, fps,
                       root_translation=root_translation)

    # Step 5: Apply subdivision + export GLB
    print("[5/6] Applying subdivision...")
    apply_subdivision(mesh_obj)
    print(f"  Mesh after subdiv: {len(mesh_obj.data.vertices)} verts, "
          f"{len(mesh_obj.data.polygons)} faces")

    print("[6/6] Exporting GLB...")
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    export_glb(args.output)

    print("=" * 60)
    print("Conversion complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
