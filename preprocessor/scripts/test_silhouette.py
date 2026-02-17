"""Single-frame smoke test for the silhouette pipeline."""

import sys
from pathlib import Path
from PIL import Image

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline import load_pipeline, process_frame


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_silhouette.py <input_image> [output_image]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "silhouette_test.png"

    print(f"Loading models...")
    load_pipeline()

    print(f"Processing: {input_path}")
    image = Image.open(input_path).convert("RGB")
    result = process_frame(image)

    result.save(output_path)
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
