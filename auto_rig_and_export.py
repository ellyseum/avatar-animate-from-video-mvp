"""
Auto Rig and Export Script for Blender Headless

This script imports a mesh, adds a humanoid armature, applies automatic weights,
and exports the rigged mesh to glTF or FBX format.

Usage:
    blender -b --python auto_rig_and_export.py -- --input mesh.obj --output rigged.glb
    
    docker run --rm --gpus all -v $(pwd):/workspace blender-headless \
        -b --python /workspace/auto_rig_and_export.py -- \
        --input /workspace/mesh.obj --output /workspace/rigged.glb

Arguments:
    --input, -i     Input mesh file path (.obj, .fbx, .ply, .stl)
    --output, -o    Output file path (.glb, .gltf, .fbx)
    --rig-type      Rig type: 'basic', 'rigify', 'metarig' (default: basic)
    --scale         Scale factor for the mesh (default: 1.0)
    --cleanup       Run mesh cleanup operations (default: True)
    --apply-transforms  Apply all transforms before rigging (default: True)
    --log-file      Optional log file path
    --help, -h      Show this help message
"""

import bpy
import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import datetime
from mathutils import Vector


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
    # Get arguments after '--' separator
    try:
        argv = sys.argv[sys.argv.index("--") + 1:]
    except ValueError:
        argv = []
    
    parser = argparse.ArgumentParser(
        description="Auto-rig a mesh and export with skeleton",
        prog="auto_rig_and_export.py"
    )
    
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Input mesh file path (.obj, .fbx, .ply, .stl)"
    )
    
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output file path (.glb, .gltf, .fbx)"
    )
    
    parser.add_argument(
        "--rig-type",
        choices=["basic", "rigify", "metarig"],
        default="basic",
        help="Type of rig to create (default: basic)"
    )
    
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Scale factor for the mesh (default: 1.0)"
    )
    
    parser.add_argument(
        "--cleanup",
        action="store_true",
        default=True,
        help="Run mesh cleanup operations"
    )
    
    parser.add_argument(
        "--no-cleanup",
        action="store_false",
        dest="cleanup",
        help="Skip mesh cleanup operations"
    )
    
    parser.add_argument(
        "--apply-transforms",
        action="store_true",
        default=True,
        help="Apply all transforms before rigging"
    )
    
    parser.add_argument(
        "--no-apply-transforms",
        action="store_false",
        dest="apply_transforms",
        help="Skip applying transforms"
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


# ============================================================================
# Mesh Import
# ============================================================================

def import_mesh(filepath, scale=1.0):
    """
    Import a mesh from various formats.
    
    Args:
        filepath: Path to the mesh file
        scale: Scale factor to apply
        
    Returns:
        The imported mesh object
    """
    filepath = Path(filepath)
    
    if not filepath.exists():
        raise FileNotFoundError(f"Input file not found: {filepath}")
    
    ext = filepath.suffix.lower()
    
    # Import based on file extension
    if ext == ".obj":
        bpy.ops.wm.obj_import(
            filepath=str(filepath),
            global_scale=scale
        )
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(
            filepath=str(filepath),
            global_scale=scale
        )
    elif ext == ".ply":
        bpy.ops.wm.ply_import(
            filepath=str(filepath),
            global_scale=scale
        )
    elif ext == ".stl":
        bpy.ops.wm.stl_import(
            filepath=str(filepath),
            global_scale=scale
        )
    elif ext == ".gltf" or ext == ".glb":
        bpy.ops.import_scene.gltf(
            filepath=str(filepath)
        )
        # Apply scale after import for glTF
        for obj in bpy.context.selected_objects:
            if obj.type == 'MESH':
                obj.scale *= scale
    else:
        raise ValueError(f"Unsupported file format: {ext}")
    
    # Find the imported mesh object
    mesh_obj = None
    for obj in bpy.context.selected_objects:
        if obj.type == 'MESH':
            mesh_obj = obj
            break
    
    if not mesh_obj:
        raise RuntimeError("No mesh object found after import")
    
    return mesh_obj


# ============================================================================
# Mesh Cleanup
# ============================================================================

def cleanup_mesh(mesh_obj, logger):
    """
    Perform mesh cleanup operations to prepare for rigging.
    
    Args:
        mesh_obj: The mesh object to clean up
        logger: Logger instance
    """
    logger.info("Running mesh cleanup...")
    
    # Make sure the mesh is selected and active
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    
    # Enter edit mode for cleanup operations
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    
    # Remove doubles (merge by distance)
    bpy.ops.mesh.remove_doubles(threshold=0.0001)
    
    # Recalculate normals
    bpy.ops.mesh.normals_make_consistent(inside=False)
    
    # Fill holes (small ones)
    try:
        bpy.ops.mesh.fill_holes(sides=4)
    except:
        pass  # Ignore if no holes
    
    # Return to object mode
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Apply smooth shading
    bpy.ops.object.shade_smooth()
    
    logger.info(f"Cleanup complete. Vertices: {len(mesh_obj.data.vertices)}, "
                f"Faces: {len(mesh_obj.data.polygons)}")


def apply_transforms(mesh_obj, logger):
    """
    Apply all transforms (location, rotation, scale) to the mesh.
    
    Args:
        mesh_obj: The mesh object
        logger: Logger instance
    """
    logger.info("Applying transforms...")
    
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    
    logger.info("Transforms applied")


def center_mesh_origin(mesh_obj, logger):
    """
    Center the mesh origin to the bottom center (feet position).
    
    Args:
        mesh_obj: The mesh object
        logger: Logger instance
    """
    logger.info("Centering mesh origin...")
    
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    
    # Set origin to geometry center
    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')
    
    # Move object so bottom is at Z=0
    bbox = [mesh_obj.matrix_world @ Vector(corner) for corner in mesh_obj.bound_box]
    min_z = min(v.z for v in bbox)
    mesh_obj.location.z -= min_z
    
    # Apply location
    bpy.ops.object.transform_apply(location=True)
    
    logger.info("Origin centered at bottom of mesh")


# ============================================================================
# Armature Creation
# ============================================================================

def create_basic_humanoid_armature(mesh_obj, logger):
    """
    Create a basic humanoid armature sized to fit the mesh.
    
    Args:
        mesh_obj: The mesh object to rig
        logger: Logger instance
        
    Returns:
        The armature object
    """
    logger.info("Creating basic humanoid armature...")
    
    # Calculate mesh dimensions
    bbox = [mesh_obj.matrix_world @ Vector(corner) for corner in mesh_obj.bound_box]
    min_z = min(v.z for v in bbox)
    max_z = max(v.z for v in bbox)
    height = max_z - min_z
    
    # Calculate approximate body proportions
    hip_height = height * 0.5
    spine_height = height * 0.6
    chest_height = height * 0.72
    neck_height = height * 0.85
    head_height = height * 0.92
    
    shoulder_width = height * 0.22
    hip_width = height * 0.1
    
    # Create armature
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    armature_obj = bpy.context.active_object
    armature_obj.name = "Humanoid_Armature"
    armature = armature_obj.data
    armature.name = "Humanoid_Rig"
    
    # Get the default bone and rename it to root
    root_bone = armature.edit_bones[0]
    root_bone.name = "Root"
    root_bone.head = (0, 0, 0)
    root_bone.tail = (0, 0, hip_height * 0.3)
    
    # Create spine hierarchy
    bones_data = [
        # (name, head_z, tail_z, parent, x_offset)
        ("Hips", hip_height * 0.95, hip_height * 1.05, "Root", 0),
        ("Spine", hip_height * 1.05, spine_height, "Hips", 0),
        ("Chest", spine_height, chest_height, "Spine", 0),
        ("UpperChest", chest_height, neck_height * 0.95, "Chest", 0),
        ("Neck", neck_height * 0.95, neck_height, "UpperChest", 0),
        ("Head", neck_height, head_height, "Neck", 0),
        
        # Left leg
        ("LeftUpLeg", hip_height, hip_height * 0.5, "Hips", hip_width),
        ("LeftLeg", hip_height * 0.5, height * 0.1, "LeftUpLeg", hip_width),
        ("LeftFoot", height * 0.1, height * 0.02, "LeftLeg", hip_width),
        ("LeftToeBase", height * 0.02, 0, "LeftFoot", hip_width + 0.05),
        
        # Right leg
        ("RightUpLeg", hip_height, hip_height * 0.5, "Hips", -hip_width),
        ("RightLeg", hip_height * 0.5, height * 0.1, "RightUpLeg", -hip_width),
        ("RightFoot", height * 0.1, height * 0.02, "RightLeg", -hip_width),
        ("RightToeBase", height * 0.02, 0, "RightFoot", -hip_width - 0.05),
        
        # Left arm
        ("LeftShoulder", chest_height, chest_height, "UpperChest", shoulder_width * 0.5),
        ("LeftArm", chest_height, chest_height * 0.75, "LeftShoulder", shoulder_width),
        ("LeftForeArm", chest_height * 0.75, hip_height * 1.1, "LeftArm", shoulder_width * 1.3),
        ("LeftHand", hip_height * 1.1, hip_height, "LeftForeArm", shoulder_width * 1.4),
        
        # Right arm
        ("RightShoulder", chest_height, chest_height, "UpperChest", -shoulder_width * 0.5),
        ("RightArm", chest_height, chest_height * 0.75, "RightShoulder", -shoulder_width),
        ("RightForeArm", chest_height * 0.75, hip_height * 1.1, "RightArm", -shoulder_width * 1.3),
        ("RightHand", hip_height * 1.1, hip_height, "RightForeArm", -shoulder_width * 1.4),
    ]
    
    for bone_name, head_z, tail_z, parent_name, x_offset in bones_data:
        bone = armature.edit_bones.new(bone_name)
        bone.head = (x_offset, 0, head_z)
        bone.tail = (x_offset, 0, tail_z)
        
        # Special case for horizontal bones (shoulders, feet)
        if "Shoulder" in bone_name:
            sign = 1 if "Left" in bone_name else -1
            bone.tail = (x_offset + sign * shoulder_width * 0.3, 0, head_z)
        elif "ToeBase" in bone_name:
            bone.tail = (x_offset, -height * 0.08, 0)
        
        if parent_name in armature.edit_bones:
            bone.parent = armature.edit_bones[parent_name]
        
        # Set bone roll for better deformation
        bone.roll = 0
    
    # Exit edit mode
    bpy.ops.object.mode_set(mode='OBJECT')
    
    bone_count = len(armature.bones)
    logger.info(f"Armature created with {bone_count} bones")
    
    return armature_obj


def create_metarig_armature(mesh_obj, logger):
    """
    Create a Rigify metarig (requires Rigify addon).
    
    Args:
        mesh_obj: The mesh object to rig
        logger: Logger instance
        
    Returns:
        The armature object
    """
    logger.info("Creating Rigify metarig...")
    
    # Enable Rigify addon
    try:
        bpy.ops.preferences.addon_enable(module='rigify')
    except:
        logger.warning("Rigify addon not available, falling back to basic rig")
        return create_basic_humanoid_armature(mesh_obj, logger)
    
    # Add metarig
    try:
        bpy.ops.object.armature_human_metarig_add()
    except:
        logger.warning("Failed to create metarig, falling back to basic rig")
        return create_basic_humanoid_armature(mesh_obj, logger)
    
    armature_obj = bpy.context.active_object
    
    # Scale metarig to fit mesh
    bbox = [mesh_obj.matrix_world @ Vector(corner) for corner in mesh_obj.bound_box]
    mesh_height = max(v.z for v in bbox) - min(v.z for v in bbox)
    
    # Default metarig height is approximately 1.7 units
    scale_factor = mesh_height / 1.7
    armature_obj.scale = (scale_factor, scale_factor, scale_factor)
    
    bpy.ops.object.transform_apply(scale=True)
    
    bone_count = len(armature_obj.data.bones)
    logger.info(f"Metarig created with {bone_count} bones")
    
    return armature_obj


def create_armature(mesh_obj, rig_type, logger):
    """
    Create an armature based on the specified rig type.
    
    Args:
        mesh_obj: The mesh object to rig
        rig_type: Type of rig ('basic', 'rigify', 'metarig')
        logger: Logger instance
        
    Returns:
        The armature object
    """
    if rig_type == "basic":
        return create_basic_humanoid_armature(mesh_obj, logger)
    elif rig_type in ["rigify", "metarig"]:
        return create_metarig_armature(mesh_obj, logger)
    else:
        logger.warning(f"Unknown rig type: {rig_type}, using basic")
        return create_basic_humanoid_armature(mesh_obj, logger)


# ============================================================================
# Automatic Skinning
# ============================================================================

def apply_automatic_weights(mesh_obj, armature_obj, logger):
    """
    Parent mesh to armature with automatic weights.
    
    Args:
        mesh_obj: The mesh object
        armature_obj: The armature object
        logger: Logger instance
    """
    logger.info("Applying automatic weights...")
    
    # Deselect all
    bpy.ops.object.select_all(action='DESELECT')
    
    # Select mesh first, then armature (armature will be active/parent)
    mesh_obj.select_set(True)
    armature_obj.select_set(True)
    bpy.context.view_layer.objects.active = armature_obj
    
    # Parent with automatic weights
    try:
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        logger.info("Automatic weights applied successfully")
    except Exception as e:
        logger.warning(f"Automatic weights failed: {e}")
        logger.info("Falling back to envelope weights...")
        
        try:
            bpy.ops.object.parent_set(type='ARMATURE_ENVELOPE')
            logger.info("Envelope weights applied as fallback")
        except Exception as e2:
            logger.error(f"Envelope weights also failed: {e2}")
            # Last resort: just parent without weights
            bpy.ops.object.parent_set(type='ARMATURE')
            logger.warning("Parented without weights - manual weight painting required")
    
    # Verify vertex groups were created
    if mesh_obj.vertex_groups:
        logger.info(f"Created {len(mesh_obj.vertex_groups)} vertex groups")
    else:
        logger.warning("No vertex groups created - skinning may have failed")


def normalize_weights(mesh_obj, logger):
    """
    Normalize vertex weights to ensure proper deformation.
    
    Args:
        mesh_obj: The mesh object
        logger: Logger instance
    """
    logger.info("Normalizing vertex weights...")
    
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    
    bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
    
    try:
        bpy.ops.object.vertex_group_normalize_all(lock_active=False)
        logger.info("Weights normalized")
    except:
        logger.warning("Weight normalization skipped")
    
    bpy.ops.object.mode_set(mode='OBJECT')


# ============================================================================
# Export
# ============================================================================

def export_mesh(mesh_obj, armature_obj, filepath, logger):
    """
    Export the rigged mesh to the specified format.
    
    Args:
        mesh_obj: The mesh object
        armature_obj: The armature object
        filepath: Output file path
        logger: Logger instance
        
    Returns:
        True if export succeeded, False otherwise
    """
    filepath = Path(filepath)
    ext = filepath.suffix.lower()
    
    # Create output directory if needed
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    # Select both mesh and armature for export
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    armature_obj.select_set(True)
    bpy.context.view_layer.objects.active = armature_obj
    
    logger.info(f"Exporting to {filepath}...")
    
    try:
        if ext in [".glb", ".gltf"]:
            bpy.ops.export_scene.gltf(
                filepath=str(filepath),
                use_selection=True,
                export_format='GLB' if ext == '.glb' else 'GLTF_SEPARATE',
                export_yup=True,
                export_apply=False,  # Keep armature modifiers
                export_animations=True,
                export_skins=True,
                export_all_influences=True
            )
        elif ext == ".fbx":
            bpy.ops.export_scene.fbx(
                filepath=str(filepath),
                use_selection=True,
                apply_scale_options='FBX_SCALE_ALL',
                add_leaf_bones=False,
                bake_anim=False,
                path_mode='COPY',
                embed_textures=True
            )
        else:
            logger.error(f"Unsupported export format: {ext}")
            return False
        
        # Verify export
        if filepath.exists():
            file_size = filepath.stat().st_size / 1024
            logger.info(f"Export successful: {filepath.name} ({file_size:.2f} KB)")
            return True
        else:
            logger.error("Export file not found after export operation")
            return False
            
    except Exception as e:
        logger.error(f"Export failed: {e}")
        return False


# ============================================================================
# Summary
# ============================================================================

def log_summary(mesh_obj, armature_obj, input_path, output_path, success, logger):
    """
    Log a summary of the rigging operation.
    
    Args:
        mesh_obj: The mesh object
        armature_obj: The armature object
        input_path: Input file path
        output_path: Output file path
        success: Whether export succeeded
        logger: Logger instance
    """
    logger.info("=" * 60)
    logger.info("AUTO-RIG SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"Input: {input_path}")
    logger.info(f"Output: {output_path}")
    logger.info("-" * 60)
    logger.info(f"Mesh Name: {mesh_obj.name}")
    logger.info(f"Vertices: {len(mesh_obj.data.vertices)}")
    logger.info(f"Faces: {len(mesh_obj.data.polygons)}")
    logger.info(f"Vertex Groups: {len(mesh_obj.vertex_groups)}")
    logger.info("-" * 60)
    logger.info(f"Armature Name: {armature_obj.name}")
    logger.info(f"Bone Count: {len(armature_obj.data.bones)}")
    logger.info("-" * 60)
    logger.info(f"Export Status: {'SUCCESS' if success else 'FAILED'}")
    logger.info("=" * 60)


# ============================================================================
# Main
# ============================================================================

def main():
    """Main entry point."""
    # Parse arguments
    args = parse_arguments()
    
    # Setup logging
    logger = setup_logging(args.log_file)
    
    logger.info("=" * 60)
    logger.info("AUTO-RIG AND EXPORT SCRIPT")
    logger.info("=" * 60)
    logger.info(f"Blender Version: {bpy.app.version_string}")
    logger.info(f"Input: {args.input}")
    logger.info(f"Output: {args.output}")
    logger.info(f"Rig Type: {args.rig_type}")
    logger.info(f"Scale: {args.scale}")
    logger.info("=" * 60)
    
    try:
        # Clear the scene
        clear_scene()
        
        # Import mesh
        logger.info(f"Importing mesh from {args.input}...")
        mesh_obj = import_mesh(args.input, args.scale)
        logger.info(f"Imported mesh: {mesh_obj.name}")
        
        # Center origin
        center_mesh_origin(mesh_obj, logger)
        
        # Apply transforms if requested
        if args.apply_transforms:
            apply_transforms(mesh_obj, logger)
        
        # Cleanup mesh if requested
        if args.cleanup:
            cleanup_mesh(mesh_obj, logger)
        
        # Create armature
        armature_obj = create_armature(mesh_obj, args.rig_type, logger)
        
        # Apply automatic weights
        apply_automatic_weights(mesh_obj, armature_obj, logger)
        
        # Normalize weights
        normalize_weights(mesh_obj, logger)
        
        # Export
        success = export_mesh(mesh_obj, armature_obj, args.output, logger)
        
        # Log summary
        log_summary(mesh_obj, armature_obj, args.input, args.output, success, logger)
        
        if not success:
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)
    
    logger.info("Script completed successfully")


if __name__ == "__main__":
    main()
