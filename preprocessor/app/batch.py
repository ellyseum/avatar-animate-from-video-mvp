"""CLI batch mode: process a video and exit."""

import argparse
import sys
import time

from .pipeline import load_pipeline, process_frames_batch
from .config import settings
from .utils import process_video_frames


def main():
    parser = argparse.ArgumentParser(description="Silhouette preprocessor batch mode")
    parser.add_argument("--input", required=True, help="Input video path")
    parser.add_argument("--output", required=True, help="Output video path")
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--negative-prompt", default=None)
    parser.add_argument("--steps", type=int, default=None)
    parser.add_argument("--strength", type=float, default=None)
    parser.add_argument("--guidance-scale", type=float, default=None)
    parser.add_argument("--controlnet-scale", type=float, default=None)
    parser.add_argument("--batch-size", type=int, default=None)

    args = parser.parse_args()

    print(f"[batch] Loading models...")
    load_pipeline()

    params = {
        "prompt": args.prompt,
        "negative_prompt": args.negative_prompt,
        "num_inference_steps": args.steps,
        "strength": args.strength,
        "guidance_scale": args.guidance_scale,
        "controlnet_conditioning_scale": args.controlnet_scale,
    }

    batch_size = args.batch_size or settings.batch_size

    def frame_processor(images):
        return process_frames_batch(images, **params)

    print(f"[batch] Processing {args.input} → {args.output}")
    start = time.time()
    frame_count, fps = process_video_frames(
        args.input, args.output, frame_processor, batch_size,
    )
    elapsed = time.time() - start

    print(f"[batch] Done: {frame_count} frames at {fps:.1f} fps in {elapsed:.1f}s "
          f"({frame_count / elapsed:.1f} frames/sec)")


if __name__ == "__main__":
    main()
