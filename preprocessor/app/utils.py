import os
import subprocess
import tempfile
from pathlib import Path
from PIL import Image


def extract_frames(video_path: str, output_dir: str) -> tuple[list[str], float]:
    """Extract all frames from a video using ffmpeg.

    Returns (list of frame paths, fps).
    """
    os.makedirs(output_dir, exist_ok=True)

    # Get fps from video
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate",
            "-of", "csv=p=0",
            video_path,
        ],
        capture_output=True, text=True, check=True,
    )
    fps_str = result.stdout.strip()
    if "/" in fps_str:
        num, den = fps_str.split("/")
        fps = float(num) / float(den)
    else:
        fps = float(fps_str)

    # Extract frames
    pattern = os.path.join(output_dir, "frame_%06d.png")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vsync", "0",
            pattern,
        ],
        capture_output=True, check=True,
    )

    frames = sorted(
        [os.path.join(output_dir, f) for f in os.listdir(output_dir)
         if f.startswith("frame_") and f.endswith(".png")]
    )
    return frames, fps


def stitch_frames(frame_dir: str, output_path: str, fps: float):
    """Stitch processed frames back into a video using ffmpeg."""
    pattern = os.path.join(frame_dir, "frame_%06d.png")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-r", str(fps),
            "-i", pattern,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "18",
            "-preset", "fast",
            "-an",
            output_path,
        ],
        capture_output=True, check=True,
    )


def process_video_frames(
    input_path: str,
    output_path: str,
    frame_processor,
    batch_size: int = 4,
) -> tuple[int, float]:
    """Extract frames, process them, and stitch back.

    frame_processor: callable that takes list[Image] and returns list[Image]
    Returns (frame_count, fps).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        input_frames_dir = os.path.join(tmpdir, "input")
        output_frames_dir = os.path.join(tmpdir, "output")
        os.makedirs(output_frames_dir)

        frame_paths, fps = extract_frames(input_path, input_frames_dir)
        total = len(frame_paths)
        print(f"[utils] Extracted {total} frames at {fps:.2f} fps")

        # Process in batches
        for i in range(0, total, batch_size):
            batch_paths = frame_paths[i:i + batch_size]
            batch_images = [Image.open(p).convert("RGB") for p in batch_paths]

            processed = frame_processor(batch_images)

            for j, img in enumerate(processed):
                idx = i + j
                out_name = f"frame_{idx + 1:06d}.png"
                img.save(os.path.join(output_frames_dir, out_name))

            print(f"[utils] Processed {min(i + batch_size, total)}/{total} frames")

        stitch_frames(output_frames_dir, output_path, fps)
        return total, fps
