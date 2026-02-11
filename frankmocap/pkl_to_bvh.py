"""
PKL-to-BVH Converter for FrankMocap Output

Converts FrankMocap prediction PKL files into BVH animation + rest-pose OBJ mesh.
Designed to run inside the FrankMocap Docker container (has numpy, scipy, smplx, torch).

Usage:
    python pkl_to_bvh.py \
        --input_dir /workspace/mocap \
        --output_bvh /workspace/animation.bvh \
        --output_mesh /workspace/smpl_rest.obj

    # Inside container:
    docker run --rm --gpus all \
        -v data/jobs/123:/workspace \
        -v smpl:/opt/frankmocap/extra_data/smpl \
        -v pkl_to_bvh.py:/workspace/pkl_to_bvh.py:ro \
        frankmocap-gpu python /workspace/pkl_to_bvh.py \
        --input_dir /workspace/mocap \
        --output_bvh /workspace/animation.bvh \
        --output_mesh /workspace/smpl_rest.obj
"""

import argparse
import glob
import os
import pickle
import sys

import numpy as np
from scipy.spatial.transform import Rotation

# ============================================================================
# SMPL Joint Hierarchy (24 joints)
# ============================================================================

# SMPL joint names matching retarget_and_export.py DEFAULT_BONE_MAPPING targets
SMPL_JOINT_NAMES = [
    "Hips",           # 0  - root
    "LeftUpLeg",      # 1
    "RightUpLeg",     # 2
    "Spine",          # 3
    "LeftLeg",        # 4
    "RightLeg",       # 5
    "Chest",          # 6  (Spine1 in SMPL)
    "LeftFoot",       # 7
    "RightFoot",      # 8
    "UpperChest",     # 9  (Spine2 in SMPL)
    "LeftToeBase",    # 10
    "RightToeBase",   # 11
    "Neck",           # 12
    "LeftShoulder",   # 13 (L_Collar)
    "RightShoulder",  # 14 (R_Collar)
    "Head",           # 15
    "LeftArm",        # 16
    "RightArm",       # 17
    "LeftForeArm",    # 18
    "RightForeArm",   # 19
    "LeftHand",       # 20
    "RightHand",      # 21
    "LeftHandEnd",    # 22 (unused leaf)
    "RightHandEnd",   # 23 (unused leaf)
]

# Parent index for each joint (-1 = root)
SMPL_PARENT = [
    -1,  # 0: Hips (root)
     0,  # 1: LeftUpLeg -> Hips
     0,  # 2: RightUpLeg -> Hips
     0,  # 3: Spine -> Hips
     1,  # 4: LeftLeg -> LeftUpLeg
     2,  # 5: RightLeg -> RightUpLeg
     3,  # 6: Chest -> Spine
     4,  # 7: LeftFoot -> LeftLeg
     5,  # 8: RightFoot -> RightLeg
     6,  # 9: UpperChest -> Chest
     7,  # 10: LeftToeBase -> LeftFoot
     8,  # 11: RightToeBase -> RightFoot
     9,  # 12: Neck -> UpperChest
     9,  # 13: LeftShoulder -> UpperChest
     9,  # 14: RightShoulder -> UpperChest
    12,  # 15: Head -> Neck
    13,  # 16: LeftArm -> LeftShoulder
    14,  # 17: RightArm -> RightShoulder
    16,  # 18: LeftForeArm -> LeftArm
    17,  # 19: RightForeArm -> RightArm
    18,  # 20: LeftHand -> LeftForeArm
    19,  # 21: RightHand -> RightForeArm
    20,  # 22: LeftHandEnd -> LeftHand
    21,  # 23: RightHandEnd -> RightHand
]

# Rest-pose bone offsets in meters (approximate SMPL T-pose)
# These define the skeleton shape in BVH OFFSET fields
SMPL_OFFSETS = np.array([
    [ 0.000,  0.000,  0.000],  # 0: Hips (root)
    [ 0.083, -0.091,  0.000],  # 1: LeftUpLeg
    [-0.083, -0.091,  0.000],  # 2: RightUpLeg
    [ 0.000,  0.103,  0.000],  # 3: Spine
    [ 0.000, -0.392,  0.000],  # 4: LeftLeg
    [ 0.000, -0.392,  0.000],  # 5: RightLeg
    [ 0.000,  0.141,  0.000],  # 6: Chest
    [ 0.000, -0.424, -0.023],  # 7: LeftFoot
    [ 0.000, -0.424, -0.023],  # 8: RightFoot
    [ 0.000,  0.157,  0.000],  # 9: UpperChest
    [ 0.000, -0.069,  0.130],  # 10: LeftToeBase
    [ 0.000, -0.069,  0.130],  # 11: RightToeBase
    [ 0.000,  0.119,  0.000],  # 12: Neck
    [ 0.069,  0.057,  0.000],  # 13: LeftShoulder
    [-0.069,  0.057,  0.000],  # 14: RightShoulder
    [ 0.000,  0.082,  0.000],  # 15: Head
    [ 0.150,  0.000,  0.000],  # 16: LeftArm
    [-0.150,  0.000,  0.000],  # 17: RightArm
    [ 0.257,  0.000,  0.000],  # 18: LeftForeArm
    [-0.257,  0.000,  0.000],  # 19: RightForeArm
    [ 0.250,  0.000,  0.000],  # 20: LeftHand
    [-0.250,  0.000,  0.000],  # 21: RightHand
    [ 0.100,  0.000,  0.000],  # 22: LeftHandEnd
    [-0.100,  0.000,  0.000],  # 23: RightHandEnd
])


# ============================================================================
# PKL Loading
# ============================================================================

def load_pkl_frames(input_dir):
    """Load all FrankMocap PKL prediction files in frame order.

    Returns:
        list of dicts, each with keys:
            - body_pose: (24, 3) axis-angle rotations
            - betas: (10,) shape parameters
            - camera: (3,) camera params [scale, tx, ty]
    """
    pattern = os.path.join(input_dir, "*_prediction_result.pkl")
    files = sorted(glob.glob(pattern))

    if not files:
        # Try nested mocap subdirectories (FrankMocap sometimes nests by video name)
        pattern = os.path.join(input_dir, "**", "*_prediction_result.pkl")
        files = sorted(glob.glob(pattern, recursive=True))

    if not files:
        raise FileNotFoundError(
            f"No *_prediction_result.pkl files found in {input_dir}"
        )

    frames = []
    for fpath in files:
        with open(fpath, "rb") as f:
            data = pickle.load(f)

        preds = data.get("pred_output_list", [])
        if not preds:
            print(f"  Warning: no predictions in {os.path.basename(fpath)}, skipping")
            continue

        pred = preds[0]  # First (usually only) person detected
        body_pose = pred["pred_body_pose"].reshape(24, 3)
        betas = pred["pred_betas"].reshape(10)
        camera = pred["pred_camera"].reshape(3)

        frames.append({
            "body_pose": body_pose.astype(np.float64),
            "betas": betas.astype(np.float64),
            "camera": camera.astype(np.float64),
        })

    print(f"Loaded {len(frames)} frames from {len(files)} PKL files")
    return frames


# ============================================================================
# Axis-Angle → Euler Conversion
# ============================================================================

def axis_angle_to_euler(axis_angle, order="ZXY"):
    """Convert (N, 3) axis-angle rotations to Euler angles in degrees."""
    rotvecs = axis_angle.reshape(-1, 3)
    rot = Rotation.from_rotvec(rotvecs)
    euler = rot.as_euler(order.upper(), degrees=True)
    return euler


# FrankMocap outputs body pose in camera coordinates (OpenCV: X-right, Y-down, Z-forward).
# BVH and 3D viewers expect Y-up world coordinates. Apply 180° X-axis rotation to root.
_CAMERA_TO_WORLD = Rotation.from_rotvec([np.pi, 0, 0])


# ============================================================================
# BVH Writer
# ============================================================================

def build_children_map():
    """Build parent→children adjacency from SMPL_PARENT."""
    children = {i: [] for i in range(len(SMPL_JOINT_NAMES))}
    for i, p in enumerate(SMPL_PARENT):
        if p >= 0:
            children[p].append(i)
    return children


def write_bvh_hierarchy(fp, joint_idx, children_map, depth=0):
    """Recursively write BVH HIERARCHY section."""
    indent = "\t" * depth
    name = SMPL_JOINT_NAMES[joint_idx]
    offset = SMPL_OFFSETS[joint_idx]

    kids = children_map[joint_idx]

    if depth == 0:
        fp.write(f"{indent}ROOT {name}\n")
    else:
        fp.write(f"{indent}JOINT {name}\n")

    fp.write(f"{indent}{{\n")
    fp.write(f"{indent}\tOFFSET {offset[0]:.6f} {offset[1]:.6f} {offset[2]:.6f}\n")

    if depth == 0:
        # Root has position + rotation channels
        fp.write(f"{indent}\tCHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation\n")
    else:
        fp.write(f"{indent}\tCHANNELS 3 Zrotation Xrotation Yrotation\n")

    if kids:
        for child_idx in kids:
            write_bvh_hierarchy(fp, child_idx, children_map, depth + 1)
    else:
        # Leaf joint — add End Site
        fp.write(f"{indent}\tEnd Site\n")
        fp.write(f"{indent}\t{{\n")
        fp.write(f"{indent}\t\tOFFSET 0.000000 0.050000 0.000000\n")
        fp.write(f"{indent}\t}}\n")

    fp.write(f"{indent}}}\n")


def count_channels(joint_idx, children_map):
    """Count total channels in hierarchy (for MOTION header)."""
    kids = children_map[joint_idx]
    total = 6 if SMPL_PARENT[joint_idx] < 0 else 3  # root has 6, others have 3
    for child_idx in kids:
        total += count_channels(child_idx, children_map)
    return total


def get_joint_order(joint_idx, children_map):
    """Get depth-first joint order matching BVH hierarchy traversal."""
    order = [joint_idx]
    for child_idx in children_map[joint_idx]:
        order.extend(get_joint_order(child_idx, children_map))
    return order


def write_bvh(output_path, frames, fps=30.0):
    """Write BVH animation file from frame data.

    Args:
        output_path: Output .bvh file path
        frames: List of frame dicts with 'body_pose' key
        fps: Frames per second
    """
    children_map = build_children_map()
    joint_order = get_joint_order(0, children_map)
    n_frames = len(frames)
    frame_time = 1.0 / fps

    with open(output_path, "w") as fp:
        # HIERARCHY
        fp.write("HIERARCHY\n")
        write_bvh_hierarchy(fp, 0, children_map, depth=0)

        # MOTION
        fp.write("MOTION\n")
        fp.write(f"Frames: {n_frames}\n")
        fp.write(f"Frame Time: {frame_time:.6f}\n")

        for frame in frames:
            body_pose = frame["body_pose"].copy()  # (24, 3) axis-angle

            # Correct root orientation from camera frame (Y-down) to world frame (Y-up)
            root_rot = Rotation.from_rotvec(body_pose[0])
            body_pose[0] = (_CAMERA_TO_WORLD * root_rot).as_rotvec()

            euler_angles = axis_angle_to_euler(body_pose, order="ZXY")  # (24, 3) degrees

            values = []
            for j_idx in joint_order:
                if SMPL_PARENT[j_idx] < 0:
                    # Root: position + rotation
                    # Use zero position (no global translation from mocap)
                    values.extend([0.0, 0.0, 0.0])
                # Euler angles: Z, X, Y order
                z, x, y = euler_angles[j_idx]
                values.extend([z, x, y])

            fp.write(" ".join(f"{v:.4f}" for v in values) + "\n")

    print(f"Wrote BVH: {output_path} ({n_frames} frames, {fps} fps)")


# ============================================================================
# Rest-Pose OBJ Export
# ============================================================================

def export_rest_pose_obj(output_path, betas=None):
    """Export SMPL rest-pose mesh as OBJ using smplx library.

    Falls back to a minimal cube if smplx is not available.
    """
    try:
        import torch
        import smplx

        model_path = os.environ.get(
            "SMPL_MODEL_PATH",
            "/opt/frankmocap/extra_data/smpl"
        )

        # smplx.create expects model_path to be the parent dir containing
        # a "smpl" or "smplx" subdirectory with the .pkl. If the .pkl files
        # are at model_path directly (flat layout), point one level up.
        smpl_pkl = os.path.join(model_path, "smpl", "SMPL_NEUTRAL.pkl")
        basic_pkl = os.path.join(model_path, "basicModel_neutral_lbs_10_207_0_v1.0.0.pkl")
        smplx_pkl = os.path.join(model_path, "SMPLX_NEUTRAL.pkl")

        if os.path.exists(basic_pkl) and not os.path.exists(smpl_pkl):
            # Flat layout — create temp symlink structure for smplx.create
            import tempfile, shutil
            tmpdir = tempfile.mkdtemp()
            smpl_subdir = os.path.join(tmpdir, "smpl")
            os.makedirs(smpl_subdir, exist_ok=True)
            os.symlink(os.path.abspath(basic_pkl),
                        os.path.join(smpl_subdir, "SMPL_NEUTRAL.pkl"))
            if os.path.exists(smplx_pkl):
                smplx_subdir = os.path.join(tmpdir, "smplx")
                os.makedirs(smplx_subdir, exist_ok=True)
                os.symlink(os.path.abspath(smplx_pkl),
                            os.path.join(smplx_subdir, "SMPLX_NEUTRAL.pkl"))
            model_path = tmpdir

        # Try SMPL first (lighter), fall back to SMPLX
        try:
            model = smplx.create(
                model_path,
                model_type="smpl",
                gender="neutral",
                batch_size=1,
            )
        except Exception:
            model = smplx.create(
                model_path,
                model_type="smplx",
                gender="neutral",
                batch_size=1,
            )

        if betas is not None:
            betas_tensor = torch.tensor(betas, dtype=torch.float32).unsqueeze(0)
        else:
            betas_tensor = torch.zeros(1, 10, dtype=torch.float32)

        with torch.no_grad():
            output = model(betas=betas_tensor)

        vertices = output.vertices[0].numpy()
        faces = model.faces  # (F, 3) 0-indexed

        with open(output_path, "w") as fp:
            fp.write("# SMPL rest-pose mesh\n")
            for v in vertices:
                fp.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            for f in faces:
                # OBJ faces are 1-indexed
                fp.write(f"f {f[0]+1} {f[1]+1} {f[2]+1}\n")

        print(f"Wrote OBJ: {output_path} ({len(vertices)} verts, {len(faces)} faces)")

    except Exception as e:
        print(f"Warning: SMPL mesh export failed ({e}), writing placeholder")
        _write_placeholder_obj(output_path)


def _write_placeholder_obj(output_path):
    """Write a simple unit cube OBJ as placeholder."""
    with open(output_path, "w") as fp:
        fp.write("# Placeholder mesh (smplx not available)\n")
        for x in [-0.5, 0.5]:
            for y in [0.0, 1.7]:
                for z in [-0.2, 0.2]:
                    fp.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        faces = [
            (1,2,4,3), (5,7,8,6), (1,5,6,2),
            (3,4,8,7), (1,3,7,5), (2,6,8,4),
        ]
        for f in faces:
            fp.write(f"f {f[0]} {f[1]} {f[2]} {f[3]}\n")
    print(f"Wrote placeholder OBJ: {output_path}")


# ============================================================================
# Main
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert FrankMocap PKL predictions to BVH + OBJ"
    )
    parser.add_argument(
        "--input_dir", required=True,
        help="Directory containing *_prediction_result.pkl files"
    )
    parser.add_argument(
        "--output_bvh", required=True,
        help="Output BVH animation file path"
    )
    parser.add_argument(
        "--output_mesh", default=None,
        help="Output rest-pose OBJ mesh path (optional)"
    )
    parser.add_argument(
        "--fps", type=float, default=30.0,
        help="Animation frame rate (default: 30)"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("PKL-to-BVH Converter")
    print("=" * 60)
    print(f"Input: {args.input_dir}")
    print(f"Output BVH: {args.output_bvh}")
    print(f"Output Mesh: {args.output_mesh or '(none)'}")
    print(f"FPS: {args.fps}")
    print("=" * 60)

    # Load frames
    frames = load_pkl_frames(args.input_dir)
    if not frames:
        print("ERROR: No frames loaded")
        sys.exit(1)

    # Write BVH
    os.makedirs(os.path.dirname(os.path.abspath(args.output_bvh)), exist_ok=True)
    write_bvh(args.output_bvh, frames, fps=args.fps)

    # Write rest-pose mesh
    if args.output_mesh:
        os.makedirs(os.path.dirname(os.path.abspath(args.output_mesh)), exist_ok=True)
        avg_betas = np.mean([f["betas"] for f in frames], axis=0)
        export_rest_pose_obj(args.output_mesh, betas=avg_betas)

    print("=" * 60)
    print("Conversion complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
