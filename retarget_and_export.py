"""
Retarget and Export Script for Blender Headless

This script imports a rigged target mesh and source animation, retargets the
animation to the target skeleton, bakes it, and exports the animated mesh.

Usage:
    blender -b --python retarget_and_export.py -- \
        --target avatar.glb \
        --source motion.bvh \
        --output animated_avatar.glb

    docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
        -b --python /workspace/retarget_and_export.py -- \
        --target /workspace/avatar.glb \
        --source /workspace/motion.bvh \
        --output /workspace/animated_avatar.glb

Arguments:
    --target, -t        Target rigged mesh file (.glb, .gltf, .fbx)
    --source, -s        Source animation file (.bvh, .glb, .gltf, .fbx)
    --output, -o        Output file path (.glb, .gltf, .fbx)
    --mapping, -m       Optional JSON file with bone name mapping
    --start-frame       Start frame for baking (default: auto-detect)
    --end-frame         End frame for baking (default: auto-detect)
    --fps               Frames per second (default: 30)
    --scale             Scale factor for source animation (default: 1.0)
    --root-motion       Include root motion (default: True)
    --log-file          Optional log file path
    --help, -h          Show this help message
"""

import bpy
import sys
import os
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime
from mathutils import Matrix, Vector, Quaternion, Euler
import math


# ============================================================================
# Default Bone Mapping
# ============================================================================

# Common bone name mappings from various mocap formats to standard names
# Format: { "source_name": "target_name" }
DEFAULT_BONE_MAPPING = {
    # Root/Hips variations
    "Hips": "Hips",
    "hip": "Hips",
    "hips": "Hips",
    "pelvis": "Hips",
    "Pelvis": "Hips",
    "root": "Hips",
    "Root": "Hips",
    
    # Spine variations
    "Spine": "Spine",
    "spine": "Spine",
    "spine1": "Spine",
    "Spine1": "Spine",
    "SpineLower": "Spine",
    
    "Spine1": "Chest",
    "Spine2": "Chest",
    "spine2": "Chest",
    "chest": "Chest",
    "Chest": "Chest",
    "SpineMid": "Chest",
    
    "Spine3": "UpperChest",
    "spine3": "UpperChest",
    "UpperChest": "UpperChest",
    "upperchest": "UpperChest",
    "SpineUpper": "UpperChest",
    
    # Neck/Head variations
    "Neck": "Neck",
    "neck": "Neck",
    "neck1": "Neck",
    
    "Head": "Head",
    "head": "Head",
    
    # Left Arm
    "LeftShoulder": "LeftShoulder",
    "leftshoulder": "LeftShoulder",
    "lShoulder": "LeftShoulder",
    "L_Shoulder": "LeftShoulder",
    "shoulder.L": "LeftShoulder",
    
    "LeftArm": "LeftArm",
    "leftarm": "LeftArm",
    "LeftUpArm": "LeftArm",
    "LeftUpperArm": "LeftArm",
    "lUpperArm": "LeftArm",
    "L_UpperArm": "LeftArm",
    "upper_arm.L": "LeftArm",
    
    "LeftForeArm": "LeftForeArm",
    "leftforearm": "LeftForeArm",
    "LeftLowArm": "LeftForeArm",
    "LeftLowerArm": "LeftForeArm",
    "lLowerArm": "LeftForeArm",
    "L_LowerArm": "LeftForeArm",
    "forearm.L": "LeftForeArm",
    
    "LeftHand": "LeftHand",
    "lefthand": "LeftHand",
    "lHand": "LeftHand",
    "L_Hand": "LeftHand",
    "hand.L": "LeftHand",
    
    # Right Arm
    "RightShoulder": "RightShoulder",
    "rightshoulder": "RightShoulder",
    "rShoulder": "RightShoulder",
    "R_Shoulder": "RightShoulder",
    "shoulder.R": "RightShoulder",
    
    "RightArm": "RightArm",
    "rightarm": "RightArm",
    "RightUpArm": "RightArm",
    "RightUpperArm": "RightArm",
    "rUpperArm": "RightArm",
    "R_UpperArm": "RightArm",
    "upper_arm.R": "RightArm",
    
    "RightForeArm": "RightForeArm",
    "rightforearm": "RightForeArm",
    "RightLowArm": "RightForeArm",
    "RightLowerArm": "RightForeArm",
    "rLowerArm": "RightForeArm",
    "R_LowerArm": "RightForeArm",
    "forearm.R": "RightForeArm",
    
    "RightHand": "RightHand",
    "righthand": "RightHand",
    "rHand": "RightHand",
    "R_Hand": "RightHand",
    "hand.R": "RightHand",
    
    # Left Leg
    "LeftUpLeg": "LeftUpLeg",
    "leftupleg": "LeftUpLeg",
    "LeftUpperLeg": "LeftUpLeg",
    "LeftThigh": "LeftUpLeg",
    "lThigh": "LeftUpLeg",
    "L_Thigh": "LeftUpLeg",
    "thigh.L": "LeftUpLeg",
    
    "LeftLeg": "LeftLeg",
    "leftleg": "LeftLeg",
    "LeftLowLeg": "LeftLeg",
    "LeftLowerLeg": "LeftLeg",
    "LeftShin": "LeftLeg",
    "lShin": "LeftLeg",
    "L_Shin": "LeftLeg",
    "shin.L": "LeftLeg",
    
    "LeftFoot": "LeftFoot",
    "leftfoot": "LeftFoot",
    "lFoot": "LeftFoot",
    "L_Foot": "LeftFoot",
    "foot.L": "LeftFoot",
    
    "LeftToeBase": "LeftToeBase",
    "lefttoebase": "LeftToeBase",
    "LeftToe": "LeftToeBase",
    "lToe": "LeftToeBase",
    "L_Toe": "LeftToeBase",
    "toe.L": "LeftToeBase",
    
    # Right Leg
    "RightUpLeg": "RightUpLeg",
    "rightupleg": "RightUpLeg",
    "RightUpperLeg": "RightUpLeg",
    "RightThigh": "RightUpLeg",
    "rThigh": "RightUpLeg",
    "R_Thigh": "RightUpLeg",
    "thigh.R": "RightUpLeg",
    
    "RightLeg": "RightLeg",
    "rightleg": "RightLeg",
    "RightLowLeg": "RightLeg",
    "RightLowerLeg": "RightLeg",
    "RightShin": "RightLeg",
    "rShin": "RightLeg",
    "R_Shin": "RightLeg",
    "shin.R": "RightLeg",
    
    "RightFoot": "RightFoot",
    "rightfoot": "RightFoot",
    "rFoot": "RightFoot",
    "R_Foot": "RightFoot",
    "foot.R": "RightFoot",
    
    "RightToeBase": "RightToeBase",
    "righttoebase": "RightToeBase",
    "RightToe": "RightToeBase",
    "rToe": "RightToeBase",
    "R_Toe": "RightToeBase",
    "toe.R": "RightToeBase",
}


# ============================================================================
# Logging Setup
# ============================================================================

def setup_logging(log_file=None):
    """Configure logging to stdout and optionally to a file."""
    log_format = "[%(levelname)s] %(message)s"
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=handlers
    )
    
    return logging.getLogger(__name__)


# ============================================================================
# Argument Parsing
# ============================================================================

def parse_arguments():
    """Parse command-line arguments passed after '--'."""
    try:
        argv = sys.argv[sys.argv.index("--") + 1:]
    except ValueError:
        argv = []
    
    parser = argparse.ArgumentParser(
        description="Retarget animation from source to target skeleton and export",
        prog="retarget_and_export.py"
    )
    
    parser.add_argument(
        "--target", "-t",
        required=True,
        help="Target rigged mesh file (.glb, .gltf, .fbx)"
    )
    
    parser.add_argument(
        "--source", "-s",
        required=True,
        help="Source animation file (.bvh, .glb, .gltf, .fbx)"
    )
    
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output file path (.glb, .gltf, .fbx)"
    )
    
    parser.add_argument(
        "--mapping", "-m",
        help="Optional JSON file with bone name mapping"
    )
    
    parser.add_argument(
        "--start-frame",
        type=int,
        default=None,
        help="Start frame for baking (default: auto-detect)"
    )
    
    parser.add_argument(
        "--end-frame",
        type=int,
        default=None,
        help="End frame for baking (default: auto-detect)"
    )
    
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Frames per second (default: 30)"
    )
    
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Scale factor for source animation (default: 1.0)"
    )
    
    parser.add_argument(
        "--root-motion",
        action="store_true",
        default=True,
        help="Include root motion (default: True)"
    )
    
    parser.add_argument(
        "--no-root-motion",
        action="store_false",
        dest="root_motion",
        help="Exclude root motion"
    )
    
    parser.add_argument(
        "--log-file",
        help="Optional log file path"
    )
    
    return parser.parse_args(argv)


# ============================================================================
# Scene Management
# ============================================================================

def clear_scene():
    """Remove all objects from the scene."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    
    # Clear orphan data
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    
    for block in bpy.data.armatures:
        if block.users == 0:
            bpy.data.armatures.remove(block)
    
    for block in bpy.data.actions:
        if block.users == 0:
            bpy.data.actions.remove(block)


# ============================================================================
# Import Functions
# ============================================================================

def import_file(filepath, scale=1.0):
    """
    Import a file based on its extension.
    
    Returns:
        tuple: (armature_object, mesh_objects, actions)
    """
    filepath = Path(filepath)
    
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")
    
    ext = filepath.suffix.lower()
    
    # Store objects before import
    objects_before = set(bpy.data.objects)
    actions_before = set(bpy.data.actions)
    
    if ext == ".bvh":
        bpy.ops.import_anim.bvh(
            filepath=str(filepath),
            global_scale=scale,
            use_fps_scale=True,
            update_scene_fps=False,
            update_scene_duration=True,
            use_cyclic=False,
            rotate_mode='NATIVE'
        )
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(
            filepath=str(filepath),
            global_scale=scale,
            use_anim=True,
            anim_offset=0
        )
    elif ext in [".glb", ".gltf"]:
        bpy.ops.import_scene.gltf(
            filepath=str(filepath)
        )
        # Apply scale after glTF import
        for obj in bpy.context.selected_objects:
            obj.scale *= scale
    else:
        raise ValueError(f"Unsupported file format: {ext}")
    
    # Find new objects and actions
    objects_after = set(bpy.data.objects)
    actions_after = set(bpy.data.actions)
    
    new_objects = objects_after - objects_before
    new_actions = actions_after - actions_before
    
    # Categorize objects
    armature = None
    meshes = []
    
    for obj in new_objects:
        if obj.type == 'ARMATURE':
            armature = obj
        elif obj.type == 'MESH':
            meshes.append(obj)
    
    return armature, meshes, list(new_actions)


# ============================================================================
# Bone Mapping
# ============================================================================

def load_bone_mapping(mapping_file):
    """Load bone mapping from a JSON file."""
    if mapping_file is None:
        return DEFAULT_BONE_MAPPING.copy()
    
    mapping_path = Path(mapping_file)
    if not mapping_path.exists():
        raise FileNotFoundError(f"Mapping file not found: {mapping_file}")
    
    with open(mapping_path, 'r') as f:
        custom_mapping = json.load(f)
    
    # Merge with default mapping (custom takes precedence)
    mapping = DEFAULT_BONE_MAPPING.copy()
    mapping.update(custom_mapping)
    
    return mapping


def find_target_bone(source_bone_name, bone_mapping, target_armature, logger):
    """
    Find the corresponding target bone for a source bone.
    
    Args:
        source_bone_name: Name of the source bone
        bone_mapping: Dictionary mapping source to target names
        target_armature: Target armature object
        logger: Logger instance
        
    Returns:
        Target bone name or None if not found
    """
    # Check direct mapping
    if source_bone_name in bone_mapping:
        target_name = bone_mapping[source_bone_name]
        if target_name in target_armature.data.bones:
            return target_name
    
    # Check case-insensitive match in target
    source_lower = source_bone_name.lower()
    for target_bone in target_armature.data.bones:
        if target_bone.name.lower() == source_lower:
            return target_bone.name
    
    # Check if source name exists directly in target
    if source_bone_name in target_armature.data.bones:
        return source_bone_name
    
    return None


def build_bone_mapping(source_armature, target_armature, bone_mapping, logger):
    """
    Build a complete mapping between source and target bones.
    
    Returns:
        dict: {source_bone_name: target_bone_name}
    """
    mapping = {}
    unmapped = []
    
    for source_bone in source_armature.data.bones:
        target_bone = find_target_bone(
            source_bone.name, 
            bone_mapping, 
            target_armature,
            logger
        )
        
        if target_bone:
            mapping[source_bone.name] = target_bone
        else:
            unmapped.append(source_bone.name)
    
    logger.info(f"Mapped {len(mapping)} bones")
    
    if unmapped:
        logger.warning(f"Unmapped source bones ({len(unmapped)}): {', '.join(unmapped[:10])}")
        if len(unmapped) > 10:
            logger.warning(f"  ... and {len(unmapped) - 10} more")
    
    return mapping


# ============================================================================
# Animation Retargeting
# ============================================================================

def get_bone_rest_matrix(armature, bone_name):
    """Get the rest pose matrix for a bone in armature space."""
    bone = armature.data.bones.get(bone_name)
    if bone:
        return bone.matrix_local.copy()
    return Matrix.Identity(4)


def get_bone_pose_matrix(armature, bone_name, frame):
    """Get the pose matrix for a bone at a specific frame."""
    bpy.context.scene.frame_set(frame)
    pose_bone = armature.pose.bones.get(bone_name)
    if pose_bone:
        return pose_bone.matrix.copy()
    return Matrix.Identity(4)


def retarget_animation(source_armature, target_armature, bone_mapping, 
                       start_frame, end_frame, include_root_motion, logger):
    """
    Retarget animation from source to target armature.
    
    Args:
        source_armature: Source armature with animation
        target_armature: Target armature to receive animation
        bone_mapping: Dict mapping source bone names to target bone names
        start_frame: Start frame of animation
        end_frame: End frame of animation
        include_root_motion: Whether to include root/hip translation
        logger: Logger instance
        
    Returns:
        The created action
    """
    logger.info(f"Retargeting animation from frame {start_frame} to {end_frame}")
    
    # Create new action for target
    action_name = f"Retargeted_{source_armature.name}"
    action = bpy.data.actions.new(name=action_name)
    
    if target_armature.animation_data is None:
        target_armature.animation_data_create()
    target_armature.animation_data.action = action
    
    # Calculate rest pose differences
    rest_matrices = {}
    for source_bone, target_bone in bone_mapping.items():
        source_rest = get_bone_rest_matrix(source_armature, source_bone)
        target_rest = get_bone_rest_matrix(target_armature, target_bone)
        rest_matrices[source_bone] = (source_rest, target_rest)
    
    # Identify root bone (usually Hips)
    root_bones = ['Hips', 'hips', 'pelvis', 'Pelvis', 'Root', 'root']
    source_root = None
    target_root = None
    
    for root_name in root_bones:
        if root_name in bone_mapping:
            source_root = root_name
            target_root = bone_mapping[root_name]
            break
    
    # Process each frame
    total_frames = end_frame - start_frame + 1
    log_interval = max(1, total_frames // 10)
    
    for frame in range(start_frame, end_frame + 1):
        if (frame - start_frame) % log_interval == 0:
            progress = ((frame - start_frame) / total_frames) * 100
            logger.info(f"  Processing frame {frame} ({progress:.0f}%)")
        
        bpy.context.scene.frame_set(frame)
        
        for source_bone, target_bone in bone_mapping.items():
            source_pose_bone = source_armature.pose.bones.get(source_bone)
            target_pose_bone = target_armature.pose.bones.get(target_bone)
            
            if not source_pose_bone or not target_pose_bone:
                continue
            
            # Get source rotation
            source_rot = source_pose_bone.rotation_quaternion.copy()
            if source_pose_bone.rotation_mode == 'XYZ':
                source_rot = source_pose_bone.rotation_euler.to_quaternion()
            elif source_pose_bone.rotation_mode == 'AXIS_ANGLE':
                aa = source_pose_bone.rotation_axis_angle
                source_rot = Quaternion(aa[1:], aa[0])
            
            # Apply rotation to target
            target_pose_bone.rotation_mode = 'QUATERNION'
            target_pose_bone.rotation_quaternion = source_rot
            target_pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
            
            # Handle root motion (translation)
            if include_root_motion and source_bone == source_root:
                # Get source location and scale appropriately
                source_loc = source_pose_bone.location.copy()
                target_pose_bone.location = source_loc
                target_pose_bone.keyframe_insert(data_path="location", frame=frame)
    
    logger.info(f"Created action '{action_name}' with {total_frames} frames")
    
    return action


def detect_animation_range(armature, actions):
    """
    Detect the frame range of animation data.
    
    Returns:
        tuple: (start_frame, end_frame)
    """
    start = float('inf')
    end = float('-inf')
    
    # Check armature's current action
    if armature.animation_data and armature.animation_data.action:
        action = armature.animation_data.action
        if action.frame_range:
            start = min(start, int(action.frame_range[0]))
            end = max(end, int(action.frame_range[1]))
    
    # Check provided actions
    for action in actions:
        if action.frame_range:
            start = min(start, int(action.frame_range[0]))
            end = max(end, int(action.frame_range[1]))
    
    # Fallback to scene range
    if start == float('inf') or end == float('-inf'):
        start = bpy.context.scene.frame_start
        end = bpy.context.scene.frame_end
    
    return int(start), int(end)


# ============================================================================
# Animation Baking
# ============================================================================

def bake_animation(armature, start_frame, end_frame, logger):
    """
    Bake all constraints and drivers to keyframes.
    
    Args:
        armature: Armature object with animation
        start_frame: Start frame
        end_frame: End frame
        logger: Logger instance
    """
    logger.info("Baking animation to keyframes...")
    
    # Select armature
    bpy.ops.object.select_all(action='DESELECT')
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    
    # Enter pose mode
    bpy.ops.object.mode_set(mode='POSE')
    
    # Select all bones
    bpy.ops.pose.select_all(action='SELECT')
    
    # Bake action
    bpy.ops.nla.bake(
        frame_start=start_frame,
        frame_end=end_frame,
        only_selected=True,
        visual_keying=True,
        clear_constraints=False,
        clear_parents=False,
        use_current_action=True,
        bake_types={'POSE'}
    )
    
    # Return to object mode
    bpy.ops.object.mode_set(mode='OBJECT')
    
    logger.info("Animation baked successfully")


# ============================================================================
# Export Functions
# ============================================================================

def export_animated_mesh(target_armature, target_meshes, output_path, logger):
    """
    Export the animated mesh with skeleton.
    
    Args:
        target_armature: Armature object with baked animation
        target_meshes: List of mesh objects
        output_path: Output file path
        logger: Logger instance
        
    Returns:
        bool: True if export succeeded
    """
    output_path = Path(output_path)
    ext = output_path.suffix.lower()
    
    # Create output directory
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Select objects for export
    bpy.ops.object.select_all(action='DESELECT')
    target_armature.select_set(True)
    for mesh in target_meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = target_armature
    
    logger.info(f"Exporting to {output_path}...")
    
    try:
        if ext in [".glb", ".gltf"]:
            bpy.ops.export_scene.gltf(
                filepath=str(output_path),
                use_selection=True,
                export_format='GLB' if ext == '.glb' else 'GLTF_SEPARATE',
                export_yup=True,
                export_apply=False,
                export_animations=True,
                export_skins=True,
                export_all_influences=True,
                export_current_frame=False,
                export_frame_range=True
            )
        elif ext == ".fbx":
            bpy.ops.export_scene.fbx(
                filepath=str(output_path),
                use_selection=True,
                apply_scale_options='FBX_SCALE_ALL',
                add_leaf_bones=False,
                bake_anim=True,
                bake_anim_use_all_bones=True,
                bake_anim_use_all_actions=False,
                bake_anim_force_startend_keying=True,
                path_mode='COPY',
                embed_textures=True
            )
        else:
            logger.error(f"Unsupported export format: {ext}")
            return False
        
        if output_path.exists():
            file_size = output_path.stat().st_size / 1024
            logger.info(f"Export successful: {output_path.name} ({file_size:.2f} KB)")
            return True
        else:
            logger.error("Export file not created")
            return False
            
    except Exception as e:
        logger.error(f"Export failed: {e}")
        return False


# ============================================================================
# Summary
# ============================================================================

def log_summary(source_armature, target_armature, bone_mapping, 
                input_source, input_target, output_path, 
                start_frame, end_frame, success, logger):
    """Log a summary of the retargeting operation."""
    logger.info("=" * 60)
    logger.info("RETARGET SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"Source Animation: {input_source}")
    logger.info(f"Target Mesh: {input_target}")
    logger.info(f"Output: {output_path}")
    logger.info("-" * 60)
    logger.info(f"Source Armature: {source_armature.name if source_armature else 'N/A'}")
    logger.info(f"Source Bones: {len(source_armature.data.bones) if source_armature else 0}")
    logger.info(f"Target Armature: {target_armature.name if target_armature else 'N/A'}")
    logger.info(f"Target Bones: {len(target_armature.data.bones) if target_armature else 0}")
    logger.info(f"Mapped Bones: {len(bone_mapping)}")
    logger.info("-" * 60)
    logger.info(f"Frame Range: {start_frame} - {end_frame}")
    logger.info(f"Total Frames: {end_frame - start_frame + 1}")
    logger.info("-" * 60)
    logger.info(f"Export Status: {'SUCCESS' if success else 'FAILED'}")
    logger.info("=" * 60)


# ============================================================================
# Main
# ============================================================================

def main():
    """Main entry point."""
    args = parse_arguments()
    logger = setup_logging(args.log_file)
    
    logger.info("=" * 60)
    logger.info("RETARGET AND EXPORT SCRIPT")
    logger.info("=" * 60)
    logger.info(f"Blender Version: {bpy.app.version_string}")
    logger.info(f"Target Mesh: {args.target}")
    logger.info(f"Source Animation: {args.source}")
    logger.info(f"Output: {args.output}")
    logger.info("=" * 60)
    
    source_armature = None
    target_armature = None
    bone_mapping_result = {}
    start_frame = 1
    end_frame = 250
    
    try:
        # Clear scene
        clear_scene()
        
        # Set FPS
        bpy.context.scene.render.fps = int(args.fps)
        logger.info(f"Set FPS to {args.fps}")
        
        # Load bone mapping
        bone_mapping = load_bone_mapping(args.mapping)
        logger.info(f"Loaded bone mapping with {len(bone_mapping)} entries")
        
        # Import target mesh (the avatar to animate)
        logger.info(f"Importing target mesh: {args.target}")
        target_armature, target_meshes, _ = import_file(args.target)
        
        if not target_armature:
            raise RuntimeError("No armature found in target file")
        
        logger.info(f"Target armature: {target_armature.name} "
                   f"({len(target_armature.data.bones)} bones)")
        logger.info(f"Target meshes: {[m.name for m in target_meshes]}")
        
        # Import source animation
        logger.info(f"Importing source animation: {args.source}")
        source_armature, _, source_actions = import_file(args.source, args.scale)
        
        if not source_armature:
            raise RuntimeError("No armature found in source file")
        
        logger.info(f"Source armature: {source_armature.name} "
                   f"({len(source_armature.data.bones)} bones)")
        
        # Detect animation range
        if args.start_frame is not None and args.end_frame is not None:
            start_frame = args.start_frame
            end_frame = args.end_frame
        else:
            start_frame, end_frame = detect_animation_range(source_armature, source_actions)
        
        logger.info(f"Animation range: {start_frame} - {end_frame}")
        
        # Build bone mapping
        bone_mapping_result = build_bone_mapping(
            source_armature, target_armature, bone_mapping, logger
        )
        
        if not bone_mapping_result:
            raise RuntimeError("No bones could be mapped between source and target")
        
        # Retarget animation
        action = retarget_animation(
            source_armature, target_armature, bone_mapping_result,
            start_frame, end_frame, args.root_motion, logger
        )
        
        # Bake animation
        bake_animation(target_armature, start_frame, end_frame, logger)
        
        # Delete source armature (no longer needed)
        bpy.ops.object.select_all(action='DESELECT')
        source_armature.select_set(True)
        bpy.ops.object.delete()
        
        # Set scene frame range
        bpy.context.scene.frame_start = start_frame
        bpy.context.scene.frame_end = end_frame
        
        # Export
        success = export_animated_mesh(
            target_armature, target_meshes, args.output, logger
        )
        
        # Log summary
        log_summary(
            source_armature, target_armature, bone_mapping_result,
            args.source, args.target, args.output,
            start_frame, end_frame, success, logger
        )
        
        if not success:
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Still log summary with what we have
        log_summary(
            source_armature, target_armature, bone_mapping_result,
            args.source, args.target, args.output,
            start_frame, end_frame, False, logger
        )
        
        sys.exit(1)
    
    logger.info("Script completed successfully")


if __name__ == "__main__":
    main()
