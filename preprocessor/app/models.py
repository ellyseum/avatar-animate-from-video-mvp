from pydantic import BaseModel


class ProcessRequest(BaseModel):
    """Process individual frames."""
    frames: list[str] | None = None  # base64-encoded images
    input_dir: str | None = None     # filesystem path to frame directory
    output_dir: str | None = None    # filesystem path for output frames

    prompt: str | None = None
    negative_prompt: str | None = None
    num_inference_steps: int | None = None
    strength: float | None = None
    guidance_scale: float | None = None
    controlnet_conditioning_scale: float | None = None


class ProcessVideoRequest(BaseModel):
    """Process a full video file."""
    input_path: str | None = None    # filesystem path (volume mount mode)
    output_path: str | None = None   # filesystem path for output

    prompt: str | None = None
    negative_prompt: str | None = None
    num_inference_steps: int | None = None
    strength: float | None = None
    guidance_scale: float | None = None
    controlnet_conditioning_scale: float | None = None


class ProcessVideoResponse(BaseModel):
    output_path: str | None = None
    frame_count: int = 0
    elapsed_seconds: float = 0.0


class ConfigUpdate(BaseModel):
    prompt: str | None = None
    negative_prompt: str | None = None
    num_inference_steps: int | None = None
    strength: float | None = None
    guidance_scale: float | None = None
    controlnet_conditioning_scale: float | None = None
    image_size: int | None = None
    batch_size: int | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    gpu_name: str | None = None
    gpu_memory_mb: int | None = None
    model_loaded: bool = False
    model_id: str | None = None
    controlnet_id: str | None = None
