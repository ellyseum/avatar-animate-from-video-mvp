"""
PKL-to-NPZ Converter for FrankMocap Output (SMPL-X with Hands)

Extracts body + hand rotations from FrankMocap full-mode PKL predictions,
converts to quaternions, and runs SMPL-X forward pass for rest-pose mesh/joints/weights.

Supports both body-only (SMPL, 24 joints) and full-mode (SMPL-X, 55 joints) PKL output.
Auto-detects mode from PKL keys.

Designed to run inside the FrankMocap Docker container (has numpy, scipy, smplx, torch).

Usage:
    python pkl_to_npz.py \
        --input_dir /workspace/mocap \
        --output /workspace/animation.npz

Output NPZ contains:
    vertices:    (V, 3)      float64  - Rest-pose mesh vertices (10475 SMPL-X / 6890 SMPL)
    faces:       (F, 3)      int32    - Triangle face indices
    joints:      (J, 3)      float64  - Rest-pose joint positions (55 or 24)
    weights:     (V, J)      float64  - LBS skinning weights
    rotations:   (N, J, 4)   float64  - Per-frame quaternions [w, x, y, z]
    parent:      (J,)        int32    - Parent joint indices (-1 = root)
    joint_names: (J,)        str      - Joint name strings
    fps:         scalar      float64  - Frame rate
    model_type:  str                  - "smplx" or "smpl"
"""

import argparse
import glob
import os
import pickle
import sys

import numpy as np
from scipy.spatial.transform import Rotation

# ============================================================================
# SMPL-X Joint Hierarchy (55 joints)
# ============================================================================
# Body (22) + Face (3: jaw, left_eye, right_eye) + Left Hand (15) + Right Hand (15)

SMPLX_JOINT_NAMES = [
    # Body (0-21) — same order as SMPL minus LeftHandEnd/RightHandEnd
    "Hips",           # 0  - pelvis/root
    "LeftUpLeg",      # 1  - left_hip
    "RightUpLeg",     # 2  - right_hip
    "Spine",          # 3  - spine1
    "LeftLeg",        # 4  - left_knee
    "RightLeg",       # 5  - right_knee
    "Chest",          # 6  - spine2
    "LeftFoot",       # 7  - left_ankle
    "RightFoot",      # 8  - right_ankle
    "UpperChest",     # 9  - spine3
    "LeftToeBase",    # 10 - left_foot
    "RightToeBase",   # 11 - right_foot
    "Neck",           # 12
    "LeftShoulder",   # 13 - left_collar
    "RightShoulder",  # 14 - right_collar
    "Head",           # 15
    "LeftArm",        # 16 - left_shoulder
    "RightArm",       # 17 - right_shoulder
    "LeftForeArm",    # 18 - left_elbow
    "RightForeArm",   # 19 - right_elbow
    "LeftHand",       # 20 - left_wrist
    "RightHand",      # 21 - right_wrist
    # Face (22-24)
    "Jaw",            # 22
    "LeftEye",        # 23
    "RightEye",       # 24
    # Left hand (25-39)
    "LeftIndex1",     # 25
    "LeftIndex2",     # 26
    "LeftIndex3",     # 27
    "LeftMiddle1",    # 28
    "LeftMiddle2",    # 29
    "LeftMiddle3",    # 30
    "LeftPinky1",     # 31
    "LeftPinky2",     # 32
    "LeftPinky3",     # 33
    "LeftRing1",      # 34
    "LeftRing2",      # 35
    "LeftRing3",      # 36
    "LeftThumb1",     # 37
    "LeftThumb2",     # 38
    "LeftThumb3",     # 39
    # Right hand (40-54)
    "RightIndex1",    # 40
    "RightIndex2",    # 41
    "RightIndex3",    # 42
    "RightMiddle1",   # 43
    "RightMiddle2",   # 44
    "RightMiddle3",   # 45
    "RightPinky1",    # 46
    "RightPinky2",    # 47
    "RightPinky3",    # 48
    "RightRing1",     # 49
    "RightRing2",     # 50
    "RightRing3",     # 51
    "RightThumb1",    # 52
    "RightThumb2",    # 53
    "RightThumb3",    # 54
]

SMPLX_PARENT = np.array([
    -1,  # 0:  Hips (root)
     0,  # 1:  LeftUpLeg -> Hips
     0,  # 2:  RightUpLeg -> Hips
     0,  # 3:  Spine -> Hips
     1,  # 4:  LeftLeg -> LeftUpLeg
     2,  # 5:  RightLeg -> RightUpLeg
     3,  # 6:  Chest -> Spine
     4,  # 7:  LeftFoot -> LeftLeg
     5,  # 8:  RightFoot -> RightLeg
     6,  # 9:  UpperChest -> Chest
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
    15,  # 22: Jaw -> Head
    15,  # 23: LeftEye -> Head
    15,  # 24: RightEye -> Head
    # Left hand fingers -> LeftHand (20)
    20, 25, 26,  # 25-27: LeftIndex 1,2,3
    20, 28, 29,  # 28-30: LeftMiddle 1,2,3
    20, 31, 32,  # 31-33: LeftPinky 1,2,3
    20, 34, 35,  # 34-36: LeftRing 1,2,3
    20, 37, 38,  # 37-39: LeftThumb 1,2,3
    # Right hand fingers -> RightHand (21)
    21, 40, 41,  # 40-42: RightIndex 1,2,3
    21, 43, 44,  # 43-45: RightMiddle 1,2,3
    21, 46, 47,  # 46-48: RightPinky 1,2,3
    21, 49, 50,  # 49-51: RightRing 1,2,3
    21, 52, 53,  # 52-54: RightThumb 1,2,3
], dtype=np.int32)

# Legacy SMPL (body-only, 24 joints) — kept for backward compat
SMPL_JOINT_NAMES = [
    "Hips", "LeftUpLeg", "RightUpLeg", "Spine", "LeftLeg", "RightLeg",
    "Chest", "LeftFoot", "RightFoot", "UpperChest", "LeftToeBase", "RightToeBase",
    "Neck", "LeftShoulder", "RightShoulder", "Head", "LeftArm", "RightArm",
    "LeftForeArm", "RightForeArm", "LeftHand", "RightHand",
    "LeftHandEnd", "RightHandEnd",
]
SMPL_PARENT = np.array([
    -1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14,
    16, 17, 18, 19, 20, 21,
], dtype=np.int32)

# Camera-to-world fix: FrankMocap uses OpenCV convention (Y-down, Z-forward)
# We need Y-up, Z-backward. Apply diag(1, -1, -1) to root rotation.
_CAMERA_FIX = np.diag([1.0, -1.0, -1.0])


# ============================================================================
# PKL Loading
# ============================================================================

def load_pkl_frames(input_dir):
    """Load all FrankMocap PKL prediction files in frame order.

    Auto-detects full mode (body+hands) vs body-only from PKL keys.

    Returns (frames, is_full_mode) where frames is list of dicts.
    """
    pattern = os.path.join(input_dir, "*_prediction_result.pkl")
    files = sorted(glob.glob(pattern))

    if not files:
        pattern = os.path.join(input_dir, "**", "*_prediction_result.pkl")
        files = sorted(glob.glob(pattern, recursive=True))

    if not files:
        raise FileNotFoundError(
            f"No *_prediction_result.pkl files found in {input_dir}"
        )

    # Check first file to detect mode
    with open(files[0], "rb") as f:
        first_data = pickle.load(f)
    first_pred = first_data.get("pred_output_list", [{}])[0]
    is_full = "pred_left_hand_pose" in first_pred
    print(f"Detected mode: {'full (body+hands)' if is_full else 'body-only'}")

    frames = []
    for fpath in files:
        with open(fpath, "rb") as f:
            data = pickle.load(f)

        preds = data.get("pred_output_list", [])
        if not preds:
            print(f"  Warning: no predictions in {os.path.basename(fpath)}, skipping")
            continue

        pred = preds[0]

        # Body rotations (24 joints × 3 axis-angle)
        if "pred_rotmat" in pred and pred["pred_rotmat"] is not None:
            body_rotmat = pred["pred_rotmat"].reshape(24, 3, 3).astype(np.float64)
        elif "pred_body_pose" in pred:
            body_pose = pred["pred_body_pose"].reshape(24, 3).astype(np.float64)
            body_rotmat = Rotation.from_rotvec(body_pose).as_matrix()
        else:
            print(f"  Warning: no body rotation data in {os.path.basename(fpath)}, skipping")
            continue

        betas = pred["pred_betas"].reshape(10).astype(np.float64)

        frame = {
            "betas": betas,
            "camera": None,
            "bbox_top_left": None,
            "bbox_scale_ratio": None,
        }

        if is_full:
            # Full mode: combine body (22) + face (3 identity) + hands (15+15) = 55
            # Body: take joints 0-21, drop 22-23 (LeftHandEnd, RightHandEnd)
            rotmat_55 = np.eye(3, dtype=np.float64)[np.newaxis].repeat(55, axis=0)  # (55, 3, 3)
            rotmat_55[:22] = body_rotmat[:22]

            # Joints 22-24 (jaw, eyes) — identity (FrankMocap doesn't predict these)

            # Left hand: 15 joints → indices 25-39
            if "pred_left_hand_pose" in pred and pred["pred_left_hand_pose"] is not None:
                lh_pose = pred["pred_left_hand_pose"].reshape(15, 3).astype(np.float64)
                rotmat_55[25:40] = Rotation.from_rotvec(lh_pose).as_matrix()

            # Right hand: 15 joints → indices 40-54
            if "pred_right_hand_pose" in pred and pred["pred_right_hand_pose"] is not None:
                rh_pose = pred["pred_right_hand_pose"].reshape(15, 3).astype(np.float64)
                rotmat_55[40:55] = Rotation.from_rotvec(rh_pose).as_matrix()

            frame["rotmat"] = rotmat_55
        else:
            frame["rotmat"] = body_rotmat

        # Camera params
        if "pred_camera" in pred and pred["pred_camera"] is not None:
            frame["camera"] = pred["pred_camera"].reshape(3).astype(np.float64)
        if "bbox_top_left" in pred:
            frame["bbox_top_left"] = np.array(pred["bbox_top_left"], dtype=np.float64).reshape(2)
        if "bbox_scale_ratio" in pred:
            frame["bbox_scale_ratio"] = float(pred["bbox_scale_ratio"])

        # Vertex bounding box in image space (for overlay auto-calibration)
        if "pred_vertices_img" in pred and pred["pred_vertices_img"] is not None:
            verts_img = pred["pred_vertices_img"]
            vmin = verts_img.min(axis=0)
            vmax = verts_img.max(axis=0)
            # [x_min, y_min, x_max, y_max] in image pixels
            frame["vertex_bbox_img"] = np.array([vmin[0], vmin[1], vmax[0], vmax[1]],
                                                dtype=np.float64)

        frames.append(frame)

    print(f"Loaded {len(frames)} frames from {len(files)} PKL files")
    return frames, is_full


# ============================================================================
# Rotation Matrix → Quaternion Conversion
# ============================================================================

def rotmats_to_quats(all_rotmats):
    """Convert (N, J, 3, 3) rotation matrices to (N, J, 4) quaternions [w,x,y,z].

    Applies camera-to-world fix on root joint (index 0).
    """
    n_frames = len(all_rotmats)
    n_joints = all_rotmats.shape[1]
    quats = np.zeros((n_frames, n_joints, 4), dtype=np.float64)

    for i in range(n_frames):
        rotmats = all_rotmats[i].copy()

        # Camera-to-world fix on root only
        rotmats[0] = _CAMERA_FIX @ rotmats[0]

        # scipy returns [x, y, z, w], we need [w, x, y, z]
        scipy_quats = Rotation.from_matrix(rotmats).as_quat()
        quats[i, :, 0] = scipy_quats[:, 3]  # w
        quats[i, :, 1] = scipy_quats[:, 0]  # x
        quats[i, :, 2] = scipy_quats[:, 1]  # y
        quats[i, :, 3] = scipy_quats[:, 2]  # z

    return quats


# ============================================================================
# Root Translation from Weak Perspective Camera
# ============================================================================

_FOCAL = 5000.0
_IMG_SIZE = 224.0


def extract_root_translation(frames):
    """Derive per-frame root translation from weak perspective camera + bbox."""
    from scipy.signal import savgol_filter

    cameras = [f["camera"] for f in frames]
    bbox_tls = [f["bbox_top_left"] for f in frames]
    bbox_srs = [f["bbox_scale_ratio"] for f in frames]

    if cameras[0] is None:
        print("  No pred_camera data — skipping root translation")
        return None

    n = len(cameras)
    has_bbox = bbox_tls[0] is not None and bbox_srs[0] is not None

    if has_bbox:
        cam = np.array(cameras)
        tl = np.array(bbox_tls)
        sr = np.array(bbox_srs)

        x_crop = (cam[:, 1] + 1) / 2 * 224
        y_crop = (1 - cam[:, 2]) / 2 * 224

        x_img = x_crop / sr + tl[:, 0]
        y_img = y_crop / sr + tl[:, 1]

        dx = x_img - x_img[0]
        dy = y_img - y_img[0]

        s_avg = cam[:, 0].mean()
        sr_avg = sr.mean()
        crop_px = 224.0 / sr_avg
        pix_per_unit = s_avg * crop_px / 2.0

        translations = np.zeros((n, 3), dtype=np.float64)
        translations[:, 0] = dx / pix_per_unit
        translations[:, 1] = -dy / pix_per_unit

        print(f"  Image-space root: x=[{x_img.min():.1f}, {x_img.max():.1f}], "
              f"y=[{y_img.min():.1f}, {y_img.max():.1f}] px")
        print(f"  pix_per_unit={pix_per_unit:.1f} (s_avg={s_avg:.4f}, sr_avg={sr_avg:.4f})")
    else:
        translations = np.zeros((n, 3), dtype=np.float64)
        for i, cam in enumerate(cameras):
            s, tx, ty = cam
            translations[i] = [tx, -ty, 0.0]
        translations -= translations[0]

    window = min(11, n if n % 2 == 1 else n - 1)
    if window >= 5:
        for c in range(3):
            translations[:, c] = savgol_filter(translations[:, c], window, 2)

    print(f"  Root translation range: "
          f"X=[{translations[:,0].min():.3f}, {translations[:,0].max():.3f}], "
          f"Y=[{translations[:,1].min():.3f}, {translations[:,1].max():.3f}], "
          f"Z=[{translations[:,2].min():.3f}, {translations[:,2].max():.3f}]")

    return translations


# ============================================================================
# Quaternion Cleanup: Sign Correction + Temporal Smoothing
# ============================================================================

def fix_quaternion_signs(quats):
    """Ensure consecutive quaternions are on the same hemisphere."""
    n_frames, n_joints, _ = quats.shape
    flips = 0
    for j in range(n_joints):
        for i in range(1, n_frames):
            if np.dot(quats[i, j], quats[i - 1, j]) < 0:
                quats[i, j] *= -1
                flips += 1
    print(f"  Fixed {flips} quaternion sign flips")
    return quats


def smooth_quaternions(quats, window=5, order=2, hand_window=11):
    """Apply Savitzky-Golay smoothing to quaternion component tracks.

    Hand joints (index 25+) get a wider smoothing window because FrankMocap's
    hand detector is much noisier than body, especially for distant/small hands.
    """
    from scipy.signal import savgol_filter

    n_frames = quats.shape[0]
    if n_frames < window:
        return quats

    smoothed = np.empty_like(quats)
    n_joints = quats.shape[1]

    for j in range(n_joints):
        # Wider window for wrist (20-21) + hand joints (25-54) to kill spaz/jitter
        w = hand_window if j >= 20 else window
        w = min(w, n_frames if n_frames % 2 == 1 else n_frames - 1)
        if w < 3:
            smoothed[:, j] = quats[:, j]
            continue
        for c in range(4):
            smoothed[:, j, c] = savgol_filter(quats[:, j, c], w, order)
        norms = np.linalg.norm(smoothed[:, j], axis=-1, keepdims=True)
        smoothed[:, j] /= norms

    print(f"  Smoothed {n_joints} joint tracks (body window={window}, hand window={hand_window})")
    return smoothed


def reject_hand_outliers(quats, max_delta_deg=45):
    """Detect and interpolate through hand pose outlier frames.

    When the hand detector's bounding box jumps dramatically between frames,
    FrankMocap outputs wild hand rotations. Detect these as frames where any
    hand joint rotates more than max_delta_deg from its neighbors, then replace
    with SLERP interpolation.

    This is different from smoothing (which blurs everything) — it only fixes
    frames that are clearly wrong while preserving genuine motion.
    """
    n_frames, n_joints, _ = quats.shape
    if n_joints <= 24 or n_frames < 3:
        return quats  # No hands or too few frames

    max_delta_rad = np.radians(max_delta_deg)
    total_rejected = 0

    # Process wrist joints (20-21) AND finger joints (25+).
    # Wrists are "body" joints but heavily influenced by the hand detector —
    # when the hand bbox jumps, wrist rotations go wild too.
    hand_joints = list(range(20, 22)) + list(range(25, n_joints))
    for j in hand_joints:
        # Compute per-frame angular delta from previous frame
        # angle = 2 * arccos(|q1 · q2|)
        outliers = set()
        for i in range(1, n_frames):
            dot = np.clip(abs(np.dot(quats[i, j], quats[i - 1, j])), 0, 1)
            delta = 2.0 * np.arccos(dot)
            if delta > max_delta_rad:
                # Also check forward: is i+1 close to i-1? (confirming i is the outlier)
                if i < n_frames - 1:
                    dot_fwd = np.clip(abs(np.dot(quats[i + 1, j], quats[i - 1, j])), 0, 1)
                    fwd_delta = 2.0 * np.arccos(dot_fwd)
                    if fwd_delta < max_delta_rad:
                        # i-1 and i+1 agree, i is the outlier
                        outliers.add(i)
                    else:
                        # Could be a real transition or both are bad — mark both
                        outliers.add(i)
                else:
                    outliers.add(i)

        if not outliers:
            continue

        # SLERP interpolation through outlier spans
        sorted_outliers = sorted(outliers)
        total_rejected += len(sorted_outliers)

        # Build clean/outlier spans and interpolate
        for idx in sorted_outliers:
            # Find nearest clean frame before and after
            before = idx - 1
            while before >= 0 and before in outliers:
                before -= 1
            after = idx + 1
            while after < n_frames and after in outliers:
                after += 1

            if before < 0 and after >= n_frames:
                continue  # All frames are outliers, can't fix

            if before < 0:
                quats[idx, j] = quats[after, j]
            elif after >= n_frames:
                quats[idx, j] = quats[before, j]
            else:
                # SLERP between before and after
                t = (idx - before) / (after - before)
                q0 = quats[before, j]
                q1 = quats[after, j]
                dot = np.dot(q0, q1)
                if dot < 0:
                    q1 = -q1
                    dot = -dot
                dot = np.clip(dot, 0, 1)
                if dot > 0.9995:
                    # Very close — just lerp
                    result = q0 + t * (q1 - q0)
                    quats[idx, j] = result / np.linalg.norm(result)
                else:
                    theta = np.arccos(dot)
                    sin_theta = np.sin(theta)
                    quats[idx, j] = (np.sin((1 - t) * theta) * q0 +
                                     np.sin(t * theta) * q1) / sin_theta

    print(f"  Rejected {total_rejected} hand outlier frames (threshold {max_delta_deg}°/frame)")
    return quats


def limit_angular_velocity(quats, max_deg_per_frame=30):
    """Cap the maximum rotation change per frame for wrist/hand joints.

    Unlike outlier rejection (which fixes single-frame spikes), this handles
    level shifts — sustained orientation changes that happen too abruptly.
    Turns any sharp transition into a smooth ramp limited to max_deg/frame.

    Runs forward then backward to avoid directional bias.
    """
    n_frames, n_joints, _ = quats.shape
    if n_joints <= 24 or n_frames < 2:
        return quats

    max_rad = np.radians(max_deg_per_frame)
    total_limited = 0

    # Only apply to wrist joints (20-21) — finger joints are handled well
    # by outlier rejection + smoothing, and limiting velocity there would
    # kill legitimate fast finger motion
    wrist_joints = [20, 21]

    def slerp_step(q_from, q_to, max_angle):
        """SLERP from q_from toward q_to, limited to max_angle radians."""
        dot = np.dot(q_from, q_to)
        if dot < 0:
            q_to = -q_to
            dot = -dot
        dot = min(dot, 1.0)
        angle = 2.0 * np.arccos(dot)
        if angle <= max_angle:
            return q_to, False
        # Partial SLERP: move max_angle toward target
        t = max_angle / angle
        if dot > 0.9995:
            result = q_from + t * (q_to - q_from)
        else:
            theta = np.arccos(dot)
            sin_theta = np.sin(theta)
            result = (np.sin((1 - t) * theta) * q_from +
                      np.sin(t * theta) * q_to) / sin_theta
        result /= np.linalg.norm(result)
        return result, True

    for j in wrist_joints:
        limited = 0
        # Forward pass
        for i in range(1, n_frames):
            quats[i, j], was_limited = slerp_step(quats[i - 1, j], quats[i, j], max_rad)
            if was_limited:
                limited += 1
        # Backward pass (prevents forward-only bias from drifting)
        for i in range(n_frames - 2, -1, -1):
            quats[i, j], was_limited = slerp_step(quats[i + 1, j], quats[i, j], max_rad)
            if was_limited:
                limited += 1
        total_limited += limited

    print(f"  Limited {total_limited} wrist frames (max {max_deg_per_frame}°/frame)")
    return quats


def clamp_hand_rotations(quats, max_angle_deg=120):
    """Clamp hand joint rotations to prevent wild 360° spins.

    FrankMocap sometimes outputs extreme hand poses (full wrist inversions,
    fingers bent backwards). Clamp each hand joint's rotation angle to a
    maximum deviation from identity.
    """
    n_frames, n_joints, _ = quats.shape
    if n_joints <= 24:
        return quats  # No hands

    clamps = 0
    max_angle_rad = np.radians(max_angle_deg)

    # Include wrist joints (20-21) alongside finger joints (25+)
    hand_joints = list(range(20, 22)) + list(range(25, n_joints))
    for j in hand_joints:
        for i in range(n_frames):
            w, x, y, z = quats[i, j]
            # Angle = 2 * arccos(|w|) — clamp if too large
            angle = 2.0 * np.arccos(np.clip(abs(w), 0, 1))
            if angle > max_angle_rad:
                # Scale rotation to max angle
                half = max_angle_rad / 2.0
                sin_half = np.sin(half)
                old_sin = np.sin(angle / 2.0)
                if old_sin > 1e-8:
                    factor = sin_half / old_sin
                    quats[i, j] = [np.cos(half), x * factor, y * factor, z * factor]
                    clamps += 1

    print(f"  Clamped {clamps} hand rotations (max {max_angle_deg}°)")
    return quats


# ============================================================================
# SMPL-X / SMPL Forward Pass (rest pose)
# ============================================================================

def smplx_forward_pass(avg_betas):
    """Run SMPL-X model in rest pose. Returns vertices, faces, joints, weights."""
    import torch
    import smplx

    model_path = os.environ.get("SMPL_MODEL_PATH", "/opt/frankmocap/extra_data/smpl")

    # SMPL-X expects smplx/SMPLX_NEUTRAL.pkl in model_path
    import tempfile
    tmpdir = tempfile.mkdtemp()

    smplx_raw = os.path.join(model_path, "SMPLX_NEUTRAL.pkl")
    if os.path.exists(smplx_raw):
        smplx_sub = os.path.join(tmpdir, "smplx")
        os.makedirs(smplx_sub, exist_ok=True)
        os.symlink(os.path.abspath(smplx_raw), os.path.join(smplx_sub, "SMPLX_NEUTRAL.pkl"))

    model = smplx.create(
        tmpdir, model_type="smplx", gender="neutral",
        use_pca=False, flat_hand_mean=False, batch_size=1, ext="pkl",
    )

    betas_tensor = torch.tensor(avg_betas, dtype=torch.float32).unsqueeze(0)
    with torch.no_grad():
        output = model(betas=betas_tensor)

    vertices = output.vertices[0].numpy().astype(np.float64)
    joints = output.joints[0].numpy().astype(np.float64)[:55]  # Only kinematic joints
    faces = model.faces.astype(np.int32)
    weights = model.lbs_weights.numpy().astype(np.float64)

    print(f"SMPL-X: {vertices.shape[0]} verts, {faces.shape[0]} faces, "
          f"{joints.shape[0]} joints, weights {weights.shape}")
    return vertices, faces, joints, weights


def smpl_forward_pass(avg_betas):
    """Run SMPL model in rest pose (body-only fallback)."""
    import torch
    import smplx

    model_path = os.environ.get("SMPL_MODEL_PATH", "/opt/frankmocap/extra_data/smpl")

    smpl_pkl = os.path.join(model_path, "smpl", "SMPL_NEUTRAL.pkl")
    basic_pkl = os.path.join(model_path, "basicModel_neutral_lbs_10_207_0_v1.0.0.pkl")

    if os.path.exists(basic_pkl) and not os.path.exists(smpl_pkl):
        import tempfile
        tmpdir = tempfile.mkdtemp()
        smpl_subdir = os.path.join(tmpdir, "smpl")
        os.makedirs(smpl_subdir, exist_ok=True)
        os.symlink(os.path.abspath(basic_pkl),
                    os.path.join(smpl_subdir, "SMPL_NEUTRAL.pkl"))
        model_path = tmpdir

    model = smplx.create(model_path, model_type="smpl", gender="neutral", batch_size=1)
    betas_tensor = torch.tensor(avg_betas, dtype=torch.float32).unsqueeze(0)

    with torch.no_grad():
        output = model(betas=betas_tensor)

    vertices = output.vertices[0].numpy().astype(np.float64)
    joints = output.joints[0].numpy().astype(np.float64)[:24]
    faces = model.faces.astype(np.int32)
    weights = model.lbs_weights.numpy().astype(np.float64)

    print(f"SMPL: {vertices.shape[0]} verts, {faces.shape[0]} faces, "
          f"{joints.shape[0]} joints, weights {weights.shape}")
    return vertices, faces, joints, weights


# ============================================================================
# Main
# ============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Convert FrankMocap PKL predictions to NPZ (quats + SMPL-X mesh)"
    )
    parser.add_argument("--input_dir", required=True,
                        help="Directory containing *_prediction_result.pkl files")
    parser.add_argument("--output", required=True,
                        help="Output .npz file path")
    parser.add_argument("--fps", type=float, default=30.0,
                        help="Animation frame rate (default: 30)")
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 60)
    print("PKL-to-NPZ Converter (SMPL-X)")
    print("=" * 60)
    print(f"Input:  {args.input_dir}")
    print(f"Output: {args.output}")
    print(f"FPS:    {args.fps}")
    print("=" * 60)

    # Load frames (auto-detects full vs body-only mode)
    frames, is_full = load_pkl_frames(args.input_dir)
    if not frames:
        print("ERROR: No frames loaded")
        sys.exit(1)

    n_joints = 55 if is_full else 24
    joint_names = SMPLX_JOINT_NAMES if is_full else SMPL_JOINT_NAMES
    parent = SMPLX_PARENT if is_full else SMPL_PARENT
    model_type = "smplx" if is_full else "smpl"

    # Stack rotation matrices: (N, J, 3, 3)
    all_rotmats = np.stack([f["rotmat"] for f in frames])
    print(f"Rotation matrices: {all_rotmats.shape}")

    # Convert to quaternions [w, x, y, z]: (N, J, 4)
    quats = rotmats_to_quats(all_rotmats)
    print(f"Quaternions: {quats.shape}")

    # Fix quaternion sign flips
    print("\nFixing quaternion signs...")
    quats = fix_quaternion_signs(quats)

    # Hand pose cleanup (full mode only)
    if is_full:
        # 1. Reject outlier frames — two passes to catch cascading issues
        #    (first pass fixes big spikes, second catches residual discontinuities)
        print("Rejecting hand pose outliers (pass 1)...")
        quats = reject_hand_outliers(quats, max_delta_deg=45)
        print("Rejecting hand pose outliers (pass 2)...")
        quats = reject_hand_outliers(quats, max_delta_deg=35)

        # 2. Limit wrist angular velocity — prevents level-shift snaps
        #    (outlier rejection handles spikes, this handles sustained jumps)
        print("Limiting wrist angular velocity...")
        quats = limit_angular_velocity(quats, max_deg_per_frame=30)

        # 3. Clamp extreme hand rotations (prevents 360° wrist spins)
        print("Clamping hand rotations...")
        quats = clamp_hand_rotations(quats, max_angle_deg=120)

    # Temporal smoothing (wider window for noisy hand joints)
    print("Applying temporal smoothing...")
    quats = smooth_quaternions(quats, window=5, order=2, hand_window=11)

    norms = np.linalg.norm(quats, axis=-1)
    print(f"Quaternion norms: min={norms.min():.6f}, max={norms.max():.6f}, "
          f"mean={norms.mean():.6f}")

    # Root translation
    print("\nExtracting root translation...")
    root_translation = extract_root_translation(frames)

    # Forward pass with averaged betas
    avg_betas = np.mean([f["betas"] for f in frames], axis=0)
    print(f"Averaged betas: {avg_betas}")

    if is_full:
        vertices, faces, joints, weights = smplx_forward_pass(avg_betas)
    else:
        vertices, faces, joints, weights = smpl_forward_pass(avg_betas)

    # Save NPZ
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    save_dict = dict(
        vertices=vertices,
        faces=faces,
        joints=joints,
        weights=weights,
        rotations=quats,
        parent=parent,
        joint_names=np.array(joint_names),
        fps=np.float64(args.fps),
        model_type=np.array(model_type),
    )
    if root_translation is not None:
        save_dict["root_translation"] = root_translation

    # Save raw camera + bbox params for overlay rendering
    cams = [f["camera"] for f in frames]
    if cams[0] is not None:
        save_dict["cameras"] = np.array(cams)
    bbox_tls = [f["bbox_top_left"] for f in frames]
    if bbox_tls[0] is not None:
        save_dict["bbox_top_left"] = np.array(bbox_tls)
    bbox_srs = [f["bbox_scale_ratio"] for f in frames]
    if bbox_srs[0] is not None:
        save_dict["bbox_scale_ratio"] = np.array(bbox_srs)

    # Per-frame vertex bounding box in image space (for overlay auto-calibration)
    vbboxes = [f.get("vertex_bbox_img") for f in frames]
    if vbboxes[0] is not None:
        save_dict["vertex_bbox_img"] = np.array(vbboxes)
        print(f"  vertex_bbox_img: {save_dict['vertex_bbox_img'].shape}")

    np.savez(args.output, **save_dict)

    file_size = os.path.getsize(args.output) / (1024 * 1024)
    print(f"\nSaved: {args.output} ({file_size:.1f} MB)")
    print(f"  model_type: {model_type}")
    print(f"  vertices:   {vertices.shape}")
    print(f"  faces:      {faces.shape}")
    print(f"  joints:     {joints.shape}")
    print(f"  weights:    {weights.shape}")
    print(f"  rotations:  {quats.shape}")
    if root_translation is not None:
        print(f"  root_trans: {root_translation.shape}")
    print(f"  fps:        {args.fps}")
    print("=" * 60)
    print("Conversion complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
