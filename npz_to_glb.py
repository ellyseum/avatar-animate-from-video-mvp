"""
NPZ-to-GLB Converter — Skinned Animated Avatar

Two modes:
  1. SMPL mode (default): Builds mesh from vertices/faces/weights in the NPZ.
  2. Retarget mode (--model): Imports a Mixamo FBX character and retargets
     SMPL rotations onto it with rest-pose compensation.

SMPL mode builds a complete animated GLB from SMPL/SMPL-X data exported by
pkl_to_npz.py:
  - Creates mesh from vertices/faces (6890 SMPL or 10475 SMPL-X)
  - Creates armature with actual joint positions (24 or 55 bones)
  - Applies LBS skinning weights as vertex groups
  - Keyframes quaternion rotations (identity rest = direct application)
  - Exports GLB with animation

Retarget mode:
  - Imports a Mixamo FBX (T-pose, with skin)
  - Maps SMPL joint names to Mixamo bone names
  - Computes rest-pose compensation (SMPL has identity rest, Mixamo has
    limb-aligned bones)
  - Applies SMPL rotations with compensation
  - Exports GLB preserving original Mixamo materials/textures

Supports both SMPL (24 joints, body only) and SMPL-X (55 joints, body + hands).
Joint count is auto-detected from the NPZ data.

Runs inside the blender-headless Docker container.

Usage:
    # SMPL mode (default):
    blender -b --python npz_to_glb.py -- \
        --input /workspace/animation.npz \
        --output /workspace/result.glb

    # Retarget mode (Mixamo character):
    blender -b --python npz_to_glb.py -- \
        --input /workspace/animation.npz \
        --output /workspace/result.glb \
        --model /workspace/character.fbx
"""

import argparse
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector


# ============================================================================
# Blender version compatibility — fcurve creation
# ============================================================================
# Blender 5.0 replaced action.fcurves with layered actions (layers → strips
# → channelbags → fcurves). This helper abstracts over both APIs.

def create_action_fcurves(arm_obj, action_name):
    """Create an action and return a fcurve factory.

    Returns (action, new_fcurve_fn) where new_fcurve_fn(data_path, index)
    creates an FCurve on the action for the given armature.
    """
    action = bpy.data.actions.new(name=action_name)
    if not arm_obj.animation_data:
        arm_obj.animation_data_create()
    arm_obj.animation_data.action = action

    if bpy.app.version >= (5, 0, 0):
        # Blender 5.0+: layered actions
        layer = action.layers.new(name="Layer")
        strip = layer.strips.new(type='KEYFRAME')
        slot = action.slots.new(id_type='OBJECT', name=arm_obj.name)
        arm_obj.animation_data.action_slot = slot
        channelbag = strip.channelbags.new(slot=slot)

        def new_fcurve(data_path, index):
            return channelbag.fcurves.new(data_path=data_path, index=index)
    else:
        # Blender 4.x and earlier
        def new_fcurve(data_path, index):
            return action.fcurves.new(data_path=data_path, index=index)

    return action, new_fcurve


# ============================================================================
# MANO Hand Mean Pose
# ============================================================================
# FrankMocap outputs hand poses as deltas from the MANO mean hand pose.
# For SMPL mode, deltas are fine (rest mesh has the mean baked in).
# For retarget mode (Mixamo flat-hand rest), we need full rotations.
#
# These values are from mean_mano_params.pkl (finger portion, 15 joints × 3).
# Joint order: Index(1,2,3), Middle(1,2,3), Pinky(1,2,3), Ring(1,2,3), Thumb(1,2,3)
# Same values for left and right hand (poses are in each hand's local frame).

_MANO_HAND_MEAN = np.array([
    [-0.00046054, -0.13827843, -0.04112660],  # Index1
    [-0.00630807,  0.00454280, -0.22666131],  # Index2
    [ 0.03638863, -0.05067103, -0.17757850],  # Index3
    [ 0.10856168, -0.00116203,  0.08901200],  # Middle1
    [-0.09065530, -0.08827010, -0.27470364],  # Middle2
    [ 0.02924421, -0.00051533, -0.22187421],  # Middle3
    [ 0.14447515,  0.14358631,  0.05688015],  # Pinky1
    [ 0.05511344, -0.13310488, -0.11181867],  # Pinky2
    [ 0.07288117,  0.04253169, -0.23913862],  # Pinky3
    [ 0.15338545,  0.04116660,  0.06212063],  # Ring1
    [-0.04701511, -0.11192031, -0.27242702],  # Ring2
    [ 0.01190135,  0.09378217, -0.12873621],  # Ring3
    [-0.01223526,  0.11216179, -0.16758871],  # Thumb1
    [-0.22457263, -0.05582608,  0.14514961],  # Thumb2
    [ 0.03649001,  0.00107752, -0.08376615],  # Thumb3
], dtype=np.float64)

# Map SMPL-X finger joint indices to MANO hand mean indices
# Left hand: joints 25-39, Right hand: joints 40-54
# Both follow MANO order: Index(0-2), Middle(3-5), Pinky(6-8), Ring(9-11), Thumb(12-14)
_FINGER_JOINT_START_LEFT = 25
_FINGER_JOINT_START_RIGHT = 40
_FINGER_JOINTS_PER_HAND = 15


def add_hand_mean_for_retarget(rotations, joint_names):
    """Add MANO hand mean to finger quaternions for retarget mode.

    Converts finger quaternions to axis-angle, adds the MANO mean pose,
    converts back to quaternions. This gives us the full rotation from
    identity (flat hand) to the actual hand pose, which is what we need
    for retargeting to Mixamo's flat-hand rest pose.

    Must be called BEFORE Y-up to Z-up conversion (rotations are in Y-up).

    Args:
        rotations: (N, J, 4) quaternions [w,x,y,z] in Y-up, MODIFIED IN PLACE
        joint_names: joint name strings
    """
    names = [str(n) for n in joint_names]
    n_joints = len(names)
    if n_joints <= 24:
        return rotations  # No hand joints

    n_frames = rotations.shape[0]
    adjusted = 0

    for hand_start in [_FINGER_JOINT_START_LEFT, _FINGER_JOINT_START_RIGHT]:
        for local_idx in range(_FINGER_JOINTS_PER_HAND):
            joint_idx = hand_start + local_idx
            if joint_idx >= n_joints:
                break

            mean_rv = _MANO_HAND_MEAN[local_idx]  # (3,) axis-angle

            # Convert quaternions to axis-angle (rotvec)
            quats = rotations[:, joint_idx].copy()  # (N, 4) [w,x,y,z]

            # Canonicalize: ensure w >= 0
            neg_mask = quats[:, 0] < 0
            quats[neg_mask] *= -1

            w = np.clip(quats[:, 0], -1.0, 1.0)
            half_angle = np.arccos(w)  # (N,)
            angle = 2 * half_angle
            sin_half = np.sin(half_angle)

            # axis = xyz / sin(half_angle)
            axes = np.zeros((n_frames, 3), dtype=np.float64)
            valid = sin_half > 1e-10
            axes[valid] = quats[valid, 1:] / sin_half[valid, np.newaxis]

            delta_rv = axes * angle[:, np.newaxis]  # (N, 3) rotvec

            # Add hand mean: full_rotvec = delta + mean
            full_rv = delta_rv + mean_rv[np.newaxis, :]

            # Convert back to quaternion
            full_angle = np.linalg.norm(full_rv, axis=1)  # (N,)
            full_half = full_angle / 2
            valid2 = full_angle > 1e-10

            full_axes = np.zeros_like(full_rv)
            full_axes[valid2] = full_rv[valid2] / full_angle[valid2, np.newaxis]

            new_w = np.ones(n_frames, dtype=np.float64)
            new_xyz = np.zeros((n_frames, 3), dtype=np.float64)
            new_w[valid2] = np.cos(full_half[valid2])
            new_xyz[valid2] = full_axes[valid2] * np.sin(full_half[valid2])[:, np.newaxis]

            rotations[:, joint_idx, 0] = new_w
            rotations[:, joint_idx, 1:] = new_xyz
            adjusted += 1

    print(f"  Added MANO hand mean to {adjusted} finger joint tracks")
    return rotations


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
# SMPL → Mixamo Bone Mapping
# ============================================================================

# Explicit renames where SMPL and Mixamo names differ
_SMPL_TO_MIXAMO_RENAME = {
    "Chest": "Spine1",
    "UpperChest": "Spine2",
}

# SMPL finger names use e.g. "LeftIndex1", Mixamo uses "LeftHandIndex1"
_FINGER_NAMES = ["Thumb", "Index", "Middle", "Ring", "Pinky"]

# Joints that exist in SMPL-X but have no Mixamo equivalent
_SKIP_JOINTS = {"Jaw", "LeftEye", "RightEye"}


def build_bone_mapping(smpl_joint_names, mixamo_bone_names):
    """Build a mapping from SMPL joint index to Mixamo bone name.

    Args:
        smpl_joint_names: list of SMPL joint name strings
        mixamo_bone_names: set of Mixamo bone names (without 'mixamorig:' prefix)

    Returns:
        dict mapping SMPL joint index → Mixamo bone name (stripped of prefix)
    """
    mapping = {}

    for idx, smpl_name in enumerate(smpl_joint_names):
        name = str(smpl_name)

        if name in _SKIP_JOINTS:
            continue

        # Try explicit rename first
        if name in _SMPL_TO_MIXAMO_RENAME:
            mixamo_name = _SMPL_TO_MIXAMO_RENAME[name]
            if mixamo_name in mixamo_bone_names:
                mapping[idx] = mixamo_name
                continue

        # Try direct match
        if name in mixamo_bone_names:
            mapping[idx] = name
            continue

        # Try finger prefix: LeftIndex1 → LeftHandIndex1
        matched = False
        for finger in _FINGER_NAMES:
            for side in ["Left", "Right"]:
                for digit in ["1", "2", "3"]:
                    smpl_finger = f"{side}{finger}{digit}"
                    mixamo_finger = f"{side}Hand{finger}{digit}"
                    if name == smpl_finger and mixamo_finger in mixamo_bone_names:
                        mapping[idx] = mixamo_finger
                        matched = True
                        break
                if matched:
                    break
            if matched:
                break

        if not matched and name not in _SKIP_JOINTS:
            print(f"  [warn] No Mixamo match for SMPL joint '{name}' (index {idx})")

    return mapping


def get_mixamo_bone_names(armature):
    """Extract Mixamo bone names, stripping the 'mixamorig*:' prefix.

    Mixamo exports use varying prefixes: 'mixamorig:', 'mixamorig1:',
    'mixamorig5:', etc. We strip everything up to and including the colon.

    Returns:
        dict mapping stripped name → original bone name
    """
    import re
    name_map = {}
    for bone in armature.data.bones:
        original = bone.name
        stripped = re.sub(r'^mixamorig\d*:', '', original)
        name_map[stripped] = original
    return name_map


def compute_rest_quats(armature):
    """Compute bone and parent rest quaternions for retarget formula.

    Returns two dicts:
        bone_rest:   bone name → bone's world-space rest Quaternion
        parent_rest: bone name → parent's world-space rest Quaternion (or None for roots)

    The correct retarget formula (rest-local) is:
        pose_q = bone_rest^-1 @ parent_rest @ smpl_q     (for child bones)
        pose_q = bone_rest^-1 @ smpl_q                   (for root bones)

    This produces exact world-space rotation matching with the SMPL source.
    The conjugation formula (bone_rest^-1 @ smpl_q @ bone_rest) is WRONG
    for bones whose rest orientation differs from their parent — it produces
    27-166° world-space errors for finger/hand bones.
    """
    bone_rest = {}
    parent_rest = {}

    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='EDIT')

    for ebone in armature.data.edit_bones:
        bone_rest[ebone.name] = ebone.matrix.to_3x3().to_quaternion()
        if ebone.parent:
            parent_rest[ebone.name] = ebone.parent.matrix.to_3x3().to_quaternion()
        else:
            parent_rest[ebone.name] = None

    bpy.ops.object.mode_set(mode='OBJECT')
    return bone_rest, parent_rest


def import_mixamo_fbx(filepath):
    """Import a Mixamo FBX file and return the armature object.

    After import, applies the armature's object scale so that edit-mode bone
    positions are in meters (FBX files are typically in centimeters, giving
    the armature a scale of 0.01).

    Args:
        filepath: path to the FBX file

    Returns:
        bpy.types.Object — the armature object
    """
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(
        filepath=filepath,
        automatic_bone_orientation=True,
    )
    after = set(bpy.data.objects.keys())
    new_objects = [bpy.data.objects[n] for n in after - before]

    armature = None
    for obj in new_objects:
        if obj.type == 'ARMATURE':
            armature = obj
            break

    if armature is None:
        raise RuntimeError(f"No armature found in FBX: {filepath}")

    # Apply armature rotation + scale.
    # FBX import adds -90° X rotation (Y-up → Z-up) on the object, and
    # cm scale (0.01). Baking both into the bones puts everything in
    # Blender's Z-up meter space, matching SMPL conventions.
    needs_apply = (abs(armature.scale[0] - 1.0) > 0.001 or
                   abs(armature.rotation_euler.x) > 0.01 or
                   abs(armature.rotation_euler.y) > 0.01 or
                   abs(armature.rotation_euler.z) > 0.01)
    if needs_apply:
        import math
        rot_deg = tuple(math.degrees(r) for r in armature.rotation_euler)
        print(f"  Applying transform: rot=({rot_deg[0]:.1f}°,{rot_deg[1]:.1f}°,{rot_deg[2]:.1f}°) "
              f"scale={armature.scale[0]:.4f}")
        bpy.ops.object.select_all(action='DESELECT')
        for obj in new_objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

    print(f"  Imported FBX: {len(new_objects)} objects, "
          f"armature '{armature.name}' with {len(armature.data.bones)} bones")
    return armature


def retarget_to_mixamo(armature, rotations, joint_names, fps,
                       root_translation=None):
    """Apply SMPL animation to a Mixamo armature with rest-pose compensation.

    SMPL bones have identity rest orientation (all point +Y). Mixamo bones are
    oriented along limbs. To retarget:
        pose_quat = rest_quat_inv @ smpl_quat_zup

    Args:
        armature: Mixamo armature object (already imported)
        rotations: (N, J, 4) SMPL quaternions [w,x,y,z] already converted to Z-up
        joint_names: (J,) SMPL joint name strings
        fps: frame rate
        root_translation: (N, 3) optional root position offsets (Z-up)
    """
    n_frames, n_joints, _ = rotations.shape

    # Build bone mapping
    mixamo_names = get_mixamo_bone_names(armature)  # stripped → original
    smpl_names = [str(n) for n in joint_names]
    bone_map = build_bone_mapping(smpl_names, set(mixamo_names.keys()))

    print(f"  Bone mapping: {len(bone_map)}/{n_joints} SMPL joints mapped")
    for idx, stripped in sorted(bone_map.items()):
        print(f"    {smpl_names[idx]:20s} → {mixamo_names[stripped]}")

    # Compute rest quaternions for rest-local retarget formula
    bone_rest, parent_rest = compute_rest_quats(armature)

    # Compute model height for root translation scaling
    # Use the armature's bounding box in rest pose
    model_height = None
    if root_translation is not None:
        # Find hips and head bones to estimate height
        hips_name = mixamo_names.get("Hips")
        head_name = mixamo_names.get("Head")
        if hips_name and head_name:
            bpy.context.view_layer.objects.active = armature
            bpy.ops.object.mode_set(mode='EDIT')
            hips_bone = armature.data.edit_bones.get(hips_name)
            head_bone = armature.data.edit_bones.get(head_name)
            if hips_bone and head_bone:
                model_height = (head_bone.head - hips_bone.head).length
            bpy.ops.object.mode_set(mode='OBJECT')

        # SMPL rest-pose height (from NPZ joints, Y-up before conversion)
        # joints are already Z-up at this point, so height = Z extent
        # We'll compute from joint_names — Hips is index 0
        smpl_height = None
        # We don't have raw joints here; use a reasonable default ratio
        if model_height:
            print(f"  Model hips→head height: {model_height:.3f}m")

    # Set up animation
    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = n_frames - 1
    bpy.context.scene.render.fps = int(fps)

    # Remove the FBX import's baked T-pose action (otherwise glTF exports
    # both actions and Three.js picks the wrong one)
    if armature.animation_data and armature.animation_data.action:
        old_action = armature.animation_data.action
        armature.animation_data.action = None
        bpy.data.actions.remove(old_action)
        print(f"  Removed FBX baked action")

    # Clear ALL NLA data to prevent interference with glTF export timing
    if armature.animation_data:
        for track in list(armature.animation_data.nla_tracks):
            armature.animation_data.nla_tracks.remove(track)
        print(f"  Cleared NLA tracks")

    # Ensure correct FPS (FBX import may have changed fps_base)
    bpy.context.scene.render.fps_base = 1.0

    action, new_fcurve = create_action_fcurves(armature, "Retarget_Animation")

    # Set all mapped bones to quaternion mode
    for idx, stripped in bone_map.items():
        original = mixamo_names[stripped]
        pb = armature.pose.bones.get(original)
        if pb:
            pb.rotation_mode = 'QUATERNION'

    print(f"  Keyframing {n_frames} frames...")

    # Create fcurves for rotation
    fcurves = {}
    for idx, stripped in bone_map.items():
        original = mixamo_names[stripped]
        pb = armature.pose.bones.get(original)
        if not pb:
            continue
        data_path = f'pose.bones["{original}"].rotation_quaternion'
        bone_fcs = []
        for ch in range(4):
            fc = new_fcurve(data_path=data_path, index=ch)
            fc.keyframe_points.add(n_frames)
            bone_fcs.append(fc)
        fcurves[idx] = (bone_fcs, original)

    # Root translation fcurves
    loc_fcurves = None
    if root_translation is not None:
        hips_original = mixamo_names.get("Hips")
        if hips_original:
            pb = armature.pose.bones.get(hips_original)
            if pb:
                data_path = f'pose.bones["{hips_original}"].location'
                loc_fcurves = []
                for ch in range(3):
                    fc = new_fcurve(data_path=data_path, index=ch)
                    fc.keyframe_points.add(n_frames)
                    loc_fcurves.append(fc)
                print(f"  Root translation → {hips_original}")

    # Fill keyframes with retarget formula.
    #
    # Body bones (SMPL indices 0-19, 22-24): conjugation formula
    #   pose_q = bone_rest^-1 @ smpl_q @ bone_rest
    #
    # Wrist + finger bones (20-21, 25-54): rest-local formula
    #   pose_q = bone_rest^-1 @ parent_rest @ smpl_q
    #   The wrist bones have 54-166° conjugation error, which cascades
    #   to ALL finger children. rest-local has 0° error.
    _HAND_INDICES = {20, 21} | set(range(25, 55))  # wrists + all fingers

    for idx, (bone_fcs, original) in fcurves.items():
        br = bone_rest.get(original)
        if br is None:
            continue
        br_inv = br.inverted()
        pr = parent_rest.get(original)
        use_rest_local = idx in _HAND_INDICES and pr is not None

        for frame in range(n_frames):
            w, x, y, z = rotations[frame, idx]
            smpl_q = Quaternion((w, x, y, z))
            if use_rest_local:
                pose_q = br_inv @ pr @ smpl_q
            else:
                pose_q = br_inv @ smpl_q @ br
            for ch, val in enumerate([pose_q.w, pose_q.x, pose_q.y, pose_q.z]):
                kf = bone_fcs[ch].keyframe_points[frame]
                kf.co = (frame, val)
                kf.interpolation = 'LINEAR'

    # Fill root translation — transform armature-space into Hips bone-local space.
    # pose.bones["Hips"].location is in the bone's REST-LOCAL frame, not armature
    # space. SMPL Hips has identity rest, so it works directly. Mixamo Hips has a
    # non-identity rest orientation (~90° X because bone points along spine).
    if loc_fcurves is not None:
        hips_rest_mat = armature.data.bones[hips_original].matrix_local.to_3x3()
        hips_rot_inv = hips_rest_mat.inverted()
        print(f"  Hips rest rotation (for root translation): {hips_rest_mat}")

        for frame in range(n_frames):
            armature_loc = Vector(root_translation[frame].tolist())
            local_loc = hips_rot_inv @ armature_loc
            for ch in range(3):
                kf = loc_fcurves[ch].keyframe_points[frame]
                kf.co = (frame, float(local_loc[ch]))
                kf.interpolation = 'LINEAR'

    # Update fcurves
    for idx, (bone_fcs, _) in fcurves.items():
        for fc in bone_fcs:
            fc.update()
    if loc_fcurves:
        for fc in loc_fcurves:
            fc.update()

    print(f"  Animation: {n_frames} frames at {fps} fps "
          f"({n_frames / fps:.1f}s)")


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

    # Create action (compatible with Blender 4.x and 5.0+)
    action, new_fcurve = create_action_fcurves(arm_obj, "SMPL_Animation")

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
            fc = new_fcurve(data_path=data_path, index=ch)
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
                fc = new_fcurve(data_path=data_path, index=ch)
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
    """Export scene as GLB with animations, skinning, and materials/textures."""
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
        export_image_format='AUTO',
        export_materials='EXPORT',
        export_texcoords=True,
        export_frame_range=True,  # Use scene frame range
        export_anim_slide_to_zero=False,  # Keep frame numbers as-is
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
    parser.add_argument(
        "--model", default=None,
        help="Mixamo FBX file to retarget onto (omit for SMPL mesh mode)"
    )
    return parser.parse_args(argv)


def main():
    args = parse_args()

    mode = "retarget" if args.model else "smpl"

    print("=" * 60)
    print(f"NPZ-to-GLB Converter ({mode} mode)")
    print("=" * 60)
    print(f"Input:  {args.input}")
    print(f"Output: {args.output}")
    if args.model:
        print(f"Model:  {args.model}")
    print("=" * 60)

    # Load NPZ
    data = np.load(args.input, allow_pickle=True)
    rotations = data["rotations"]     # (N, J, 4) [w, x, y, z]
    joint_names = data["joint_names"] # (J,)
    fps = float(data["fps"])

    # Root translation (optional — may not exist in older NPZ files)
    root_translation = None
    if "root_translation" in data:
        root_translation = data["root_translation"].copy()  # (N, 3)
        root_translation[:, 0] *= args.translation_scale_x
        root_translation[:, 1] *= args.translation_scale_y
        print(f"  Root trans: {root_translation.shape} "
              f"(X={args.translation_scale_x}x, Y={args.translation_scale_y}x)")

    print(f"  Rotations:  {rotations.shape}")
    print(f"  FPS:        {fps}")

    # For retarget mode: add MANO hand mean to finger deltas (must be done
    # in Y-up BEFORE coordinate conversion, because axis-angle addition is
    # frame-dependent and the mean values are in MANO's Y-up frame)
    if args.model and rotations.shape[1] > 24:
        print("\nAdding MANO hand mean for retarget...")
        rotations = add_hand_mean_for_retarget(rotations, joint_names)

    # Convert from SMPL Y-up to Blender Z-up
    print("\nConverting Y-up → Z-up...")
    rotations = yup_to_zup_quaternions(rotations)
    if root_translation is not None:
        root_translation = yup_to_zup_positions(root_translation)

    # Clear default scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    if args.model:
        # ---- Retarget mode: import Mixamo FBX, apply SMPL animation ----
        print("\n[1/3] Importing Mixamo FBX...")
        armature = import_mixamo_fbx(args.model)

        print("[2/3] Retargeting animation...")
        retarget_to_mixamo(armature, rotations, joint_names, fps,
                           root_translation=root_translation)

        print("[3/3] Exporting GLB...")
        os.makedirs(os.path.dirname(os.path.abspath(args.output)),
                    exist_ok=True)
        export_glb(args.output)
    else:
        # ---- SMPL mode: build mesh from NPZ data ----
        vertices = data["vertices"]       # (V, 3)
        faces = data["faces"]             # (F, 3)
        joints = data["joints"]           # (24, 3)
        weights = data["weights"]         # (V, 24)
        parent = data["parent"]           # (24,)

        print(f"  Vertices:   {vertices.shape}")
        print(f"  Faces:      {faces.shape}")
        print(f"  Joints:     {joints.shape}")
        print(f"  Weights:    {weights.shape}")

        vertices = yup_to_zup_positions(vertices)
        joints = yup_to_zup_positions(joints)

        # Step 1: Create mesh
        print("\n[1/6] Creating mesh...")
        mesh_obj = create_mesh(vertices, faces)
        print(f"  Mesh: {len(mesh_obj.data.vertices)} verts, "
              f"{len(mesh_obj.data.polygons)} faces")

        # Step 2: Create armature
        print("[2/6] Creating armature...")
        arm_obj = create_armature(joints, parent, joint_names)
        print(f"  Armature: {len(arm_obj.data.bones)} bones")

        # Step 3: Apply skinning
        print("[3/6] Applying skinning weights...")
        apply_skinning(mesh_obj, arm_obj, weights, joint_names)
        print(f"  Vertex groups: {len(mesh_obj.vertex_groups)}")

        # Step 4: Keyframe animation (rotations + root translation)
        print("[4/6] Keyframing animation...")
        keyframe_animation(arm_obj, rotations, joint_names, fps,
                           root_translation=root_translation)

        # Step 5: Apply subdivision + export GLB
        print("[5/6] Applying subdivision...")
        apply_subdivision(mesh_obj)
        print(f"  Mesh after subdiv: {len(mesh_obj.data.vertices)} verts, "
              f"{len(mesh_obj.data.polygons)} faces")

        print("[6/6] Exporting GLB...")
        os.makedirs(os.path.dirname(os.path.abspath(args.output)),
                    exist_ok=True)
        export_glb(args.output)

    print("=" * 60)
    print("Conversion complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
