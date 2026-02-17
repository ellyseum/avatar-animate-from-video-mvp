"""
Automated alignment: match our SMPL mesh to FrankMocap's red detection bbox.

Strategy: The red bbox in FrankMocap's source-side render defines exactly where
the person's body is. Our SMPL mesh should fit snugly inside this bbox.
We iteratively adjust ortho_scale and camera position until the mesh bbox
matches the detection bbox.

Creates greyscale onion-skin composites at each iteration for verification.
"""
import os
import subprocess
import json

import numpy as np
from PIL import Image


def find_red_bbox(frank_jpg):
    """Extract the red detection bbox from FrankMocap's left half."""
    full = np.array(Image.open(frank_jpg))
    left = full[:, :360, :]
    r, g, b = left[:,:,0].astype(int), left[:,:,1].astype(int), left[:,:,2].astype(int)
    red_mask = (r > 200) & (g < 50) & (b < 50)
    if not red_mask.any():
        return None
    rows = np.where(red_mask.any(axis=1))[0]
    cols = np.where(red_mask.any(axis=0))[0]
    return {
        "top": int(rows.min()), "bot": int(rows.max()),
        "left": int(cols.min()), "right": int(cols.max()),
    }


def measure_our_mesh(our_png):
    """Measure our mesh's bounding box from RGBA alpha channel."""
    img = np.array(Image.open(our_png))
    alpha = img[:, :, 3]
    mask = alpha > 10
    if not mask.any():
        return None
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    return {
        "top": int(rows.min()), "bot": int(rows.max()),
        "left": int(cols.min()), "right": int(cols.max()),
    }


def render_frame(frame, scale, cam_z_adj, cam_x_adj=0.0):
    """Render one frame via Docker blender-headless."""
    script = "/home/jocel/projects/avatar-animate-from-video-mvp/scale_test.py"
    job_dir = "/home/jocel/projects/avatar-animate-from-video-mvp/data/jobs/d184e1d8"
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{job_dir}:/workspace",
        "-v", f"{script}:/workspace/scale_test.py:ro",
        "blender-headless", "-b",
        "--python", "/workspace/scale_test.py", "--",
        "--input", "/workspace/result.glb",
        "--npz", "/workspace/animation_v3.npz",
        "--output_dir", "/workspace/align_iter",
        "--frame", str(frame),
        "--scales", f"{scale:.4f}",
        "--cam_z_adjust", f"{cam_z_adj:.6f}",
        "--cam_x_adjust", f"{cam_x_adj:.6f}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.returncode == 0


def create_onion_skin(our_png, frank_jpg, output_png, red_bbox):
    """Create greyscale onion skin: source in greyscale, our mesh orange, frank mesh blue."""
    full = np.array(Image.open(frank_jpg))
    source = full[:, :360, :]
    frank_overlay = full[:, 360:, :]

    # Greyscale source as base
    grey = np.mean(source, axis=2, keepdims=True).astype(np.uint8)
    base = np.repeat(grey, 3, axis=2).astype(float)

    # Overlay FrankMocap mesh (blue) where it differs from source
    diff = np.abs(frank_overlay.astype(float) - source.astype(float)).sum(axis=2)
    frank_alpha = np.clip((diff - 30) / 100, 0, 0.6)
    for c in range(3):
        base[:, :, c] = base[:, :, c] * (1 - frank_alpha) + frank_overlay[:, :, c] * frank_alpha

    # Overlay our mesh (orange tint)
    ours = np.array(Image.open(our_png))
    our_alpha = ours[:, :, 3].astype(float) / 255.0 * 0.55
    for c in range(3):
        rgb = ours[:, :, c].astype(float)
        if c == 0: rgb = np.clip(rgb * 1.5, 0, 255)
        elif c == 2: rgb *= 0.3
        base[:, :, c] = base[:, :, c] * (1 - our_alpha) + rgb * our_alpha

    # Draw red bbox outline
    if red_bbox:
        t, b_, l, r_ = red_bbox["top"], red_bbox["bot"], red_bbox["left"], red_bbox["right"]
        for px in range(max(0, l), min(360, r_+1)):
            for y in [t, b_]:
                if 0 <= y < 640:
                    base[y, px] = [255, 0, 0]
        for py in range(max(0, t), min(640, b_+1)):
            for x in [l, r_]:
                if 0 <= x < 360:
                    base[py, x] = [255, 0, 0]

    Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).save(output_png)


def main():
    job_dir = "/home/jocel/projects/avatar-animate-from-video-mvp/data/jobs/d184e1d8"
    frank_frame = 200
    our_frame = 160  # time-matched
    frank_jpg = f"{job_dir}/mocap/rendered/{frank_frame:05d}.jpg"
    iter_dir = f"{job_dir}/align_iter"
    os.makedirs(iter_dir, exist_ok=True)

    # Get the clean red bounding box as our target
    red = find_red_bbox(frank_jpg)
    if not red:
        print("ERROR: Could not find red bounding box")
        return
    red_cx = (red["left"] + red["right"]) / 2
    red_cy = (red["top"] + red["bot"]) / 2
    red_h = red["bot"] - red["top"]
    red_w = red["right"] - red["left"]
    print(f"Red bbox target: top={red['top']} bot={red['bot']} left={red['left']} right={red['right']}")
    print(f"  center=({red_cx:.0f}, {red_cy:.0f}) w={red_w} h={red_h}")

    # Starting params
    scale = 1.40
    cam_z_adj = 0.214
    cam_x_adj = 0.0
    # Empirical: cam_z_adj per pixel vertical shift ≈ 0.00319
    PX_PER_CZ = 1.0 / 0.00319  # pixels per unit cam_z
    # cam_x works similarly but for horizontal (positive = camera right = mesh shifts left in frame)
    PX_PER_CX = PX_PER_CZ  # same scale for ortho camera

    for iteration in range(20):
        print(f"\n{'='*50}")
        print(f"Iter {iteration}: scale={scale:.4f}, cam_z={cam_z_adj:.4f}, cam_x={cam_x_adj:.4f}")

        if not render_frame(our_frame, scale, cam_z_adj, cam_x_adj):
            print("Render failed"); break

        out_png = f"{iter_dir}/scale_{scale:.2f}.png"
        m = measure_our_mesh(out_png)
        if not m:
            print("Mesh measurement failed"); break

        our_h = m["bot"] - m["top"]
        our_w = m["right"] - m["left"]
        our_cx = (m["left"] + m["right"]) / 2
        our_cy = (m["top"] + m["bot"]) / 2
        clipped = m["top"] <= 1 or m["bot"] >= 638

        print(f"  Ours: top={m['top']} bot={m['bot']} left={m['left']} right={m['right']}")
        print(f"  center=({our_cx:.0f}, {our_cy:.0f}) w={our_w} h={our_h} {'[CLIPPED]' if clipped else ''}")

        # Mesh should overlap the bbox nearly perfectly
        MESH_TO_BBOX_RATIO = 1.0
        target_h = red_h * MESH_TO_BBOX_RATIO
        target_cy = red_cy  # center on bbox center
        target_cx = red_cx

        h_err = our_h - target_h if not clipped else 0
        cy_err = our_cy - target_cy
        cx_err = our_cx - target_cx

        print(f"  Target: h={target_h:.0f} cy={target_cy:.0f} cx={target_cx:.0f}")
        print(f"  Errors: h={h_err:+.0f}px, cy={cy_err:+.0f}px, cx={cx_err:+.0f}px")

        # Check convergence (all within 3px)
        if abs(h_err) < 4 and abs(cy_err) < 4 and abs(cx_err) < 4:
            print(f"\n*** CONVERGED at iteration {iteration} ***")
            create_onion_skin(out_png, frank_jpg, f"{iter_dir}/onion_final.png", red)
            break

        # Adjust scale (height matching)
        if abs(h_err) > 3 and not clipped:
            ratio = our_h / target_h
            new_scale = scale * (1 + (ratio - 1) * 0.7)
            new_scale = max(1.0, min(3.0, new_scale))
            print(f"  → scale: {scale:.4f} → {new_scale:.4f}")
            scale = new_scale

        # Adjust vertical position
        if abs(cy_err) > 3:
            adjustment = -cy_err / PX_PER_CZ * 0.7
            new_cz = max(-0.5, min(0.5, cam_z_adj + adjustment))
            print(f"  → cam_z: {cam_z_adj:.4f} → {new_cz:.4f}")
            cam_z_adj = new_cz

        # Adjust horizontal position
        if abs(cx_err) > 3:
            # Positive cx_err = our center is RIGHT of target → shift left → increase cam_x (camera right)
            adjustment = cx_err / PX_PER_CX * 0.7
            new_cx = max(-0.5, min(0.5, cam_x_adj + adjustment))
            print(f"  → cam_x: {cam_x_adj:.4f} → {new_cx:.4f}")
            cam_x_adj = new_cx

        create_onion_skin(out_png, frank_jpg, f"{iter_dir}/onion_iter{iteration:02d}.png", red)

    # Final result
    print(f"\nFinal params: scale={scale:.4f}, cam_z_adjust={cam_z_adj:.4f}, cam_x_adjust={cam_x_adj:.4f}")
    params = {"scale": round(scale, 4), "cam_z_adjust": round(cam_z_adj, 4), "cam_x_adjust": round(cam_x_adj, 4)}
    with open(f"{iter_dir}/final_params.json", "w") as f:
        json.dump(params, f, indent=2)
    print(f"Saved to {iter_dir}/final_params.json")


if __name__ == "__main__":
    main()
