import base64
import io
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from PIL import Image

from .config import settings
from .models import (
    ConfigUpdate,
    HealthResponse,
    ProcessRequest,
    ProcessVideoRequest,
    ProcessVideoResponse,
)
from . import pipeline
from .utils import process_video_frames


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[server] Pre-loading models...")
    pipeline.load_pipeline()
    print("[server] Models ready")
    yield


app = FastAPI(title="Silhouette Preprocessor", lifespan=lifespan)


@app.get("/api/v1/health", response_model=HealthResponse)
def health():
    info = pipeline.gpu_info()
    return HealthResponse(
        status="ok",
        gpu_name=info["gpu_name"],
        gpu_memory_mb=info["gpu_memory_mb"],
        model_loaded=pipeline.is_loaded(),
        model_id=settings.model_id,
        controlnet_id=settings.controlnet_id,
    )


@app.get("/api/v1/config")
def get_config():
    return {
        "model_id": settings.model_id,
        "controlnet_id": settings.controlnet_id,
        "prompt": settings.prompt,
        "negative_prompt": settings.negative_prompt,
        "num_inference_steps": settings.num_inference_steps,
        "strength": settings.strength,
        "guidance_scale": settings.guidance_scale,
        "controlnet_conditioning_scale": settings.controlnet_conditioning_scale,
        "image_size": settings.image_size,
        "batch_size": settings.batch_size,
    }


@app.put("/api/v1/config")
def update_config(update: ConfigUpdate):
    for field, value in update.model_dump(exclude_none=True).items():
        setattr(settings, field, value)
    return get_config()


@app.post("/api/v1/process")
def process_frames(req: ProcessRequest):
    params = {
        "prompt": req.prompt,
        "negative_prompt": req.negative_prompt,
        "num_inference_steps": req.num_inference_steps,
        "strength": req.strength,
        "guidance_scale": req.guidance_scale,
        "controlnet_conditioning_scale": req.controlnet_conditioning_scale,
    }

    if req.frames:
        # Base64 mode
        images = []
        for b64 in req.frames:
            data = base64.b64decode(b64)
            images.append(Image.open(io.BytesIO(data)).convert("RGB"))

        results = pipeline.process_frames_batch(images, **params)

        output = []
        for img in results:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            output.append(base64.b64encode(buf.getvalue()).decode())

        return {"frames": output}

    elif req.input_dir:
        # Filesystem mode
        import os
        out_dir = req.output_dir or req.input_dir + "_processed"
        os.makedirs(out_dir, exist_ok=True)

        frame_files = sorted(
            f for f in os.listdir(req.input_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))
        )

        batch_size = settings.batch_size
        for i in range(0, len(frame_files), batch_size):
            batch_files = frame_files[i:i + batch_size]
            batch_images = [
                Image.open(os.path.join(req.input_dir, f)).convert("RGB")
                for f in batch_files
            ]

            results = pipeline.process_frames_batch(batch_images, **params)

            for img, fname in zip(results, batch_files):
                img.save(os.path.join(out_dir, fname))

        return {"output_dir": out_dir, "frame_count": len(frame_files)}

    else:
        raise HTTPException(400, "Provide either 'frames' (base64) or 'input_dir'")


@app.post("/api/v1/process-video", response_model=ProcessVideoResponse)
def process_video(req: ProcessVideoRequest):
    if not req.input_path:
        raise HTTPException(400, "input_path is required")

    import os
    if not os.path.exists(req.input_path):
        raise HTTPException(404, f"Input video not found: {req.input_path}")

    output_path = req.output_path or req.input_path.replace(
        ".mp4", "_silhouette.mp4"
    )

    params = {
        "prompt": req.prompt,
        "negative_prompt": req.negative_prompt,
        "num_inference_steps": req.num_inference_steps,
        "strength": req.strength,
        "guidance_scale": req.guidance_scale,
        "controlnet_conditioning_scale": req.controlnet_conditioning_scale,
    }

    def frame_processor(images):
        return pipeline.process_frames_batch(images, **params)

    start = time.time()
    frame_count, _ = process_video_frames(
        req.input_path, output_path, frame_processor, settings.batch_size,
    )
    elapsed = time.time() - start

    return ProcessVideoResponse(
        output_path=output_path,
        frame_count=frame_count,
        elapsed_seconds=round(elapsed, 2),
    )
