import torch
from PIL import Image, ImageOps
from diffusers import (
    ControlNetModel,
    StableDiffusionControlNetPipeline,
    DPMSolverMultistepScheduler,
)
from controlnet_aux import MidasDetector

from .config import settings

_pipe = None
_depth_estimator = None


def get_device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def load_pipeline():
    global _pipe, _depth_estimator

    if _pipe is not None:
        return _pipe

    device = get_device()
    dtype = torch.float16 if device.type == "cuda" else torch.float32

    print(f"[pipeline] Loading ControlNet: {settings.controlnet_id}")
    controlnet = ControlNetModel.from_pretrained(
        settings.controlnet_id,
        torch_dtype=dtype,
    )

    print(f"[pipeline] Loading SD 1.5 (txt2img + ControlNet): {settings.model_id}")
    _pipe = StableDiffusionControlNetPipeline.from_pretrained(
        settings.model_id,
        controlnet=controlnet,
        torch_dtype=dtype,
        safety_checker=None,
        requires_safety_checker=False,
    )

    _pipe.scheduler = DPMSolverMultistepScheduler.from_config(
        _pipe.scheduler.config
    )

    _pipe.to(device)
    _pipe.enable_attention_slicing()

    if device.type == "cuda":
        try:
            _pipe.enable_xformers_memory_efficient_attention()
            print("[pipeline] xformers enabled")
        except Exception:
            print("[pipeline] xformers not available, using default attention")

    print("[pipeline] Loading MiDaS depth estimator")
    _depth_estimator = MidasDetector.from_pretrained("lllyasviel/Annotators")

    print("[pipeline] All models loaded")
    return _pipe


def get_depth_map(image: Image.Image) -> Image.Image:
    global _depth_estimator
    if _depth_estimator is None:
        load_pipeline()
    depth = _depth_estimator(image)
    # Invert: MiDaS gives bright=close, but ControlNet depth expects
    # white=far (background). Inverting makes person=dark in the control
    # image, which helps SD generate white silhouette for the person region.
    return ImageOps.invert(depth)


def to_silhouette(image: Image.Image) -> Image.Image:
    """Post-process: convert SD output to clean white-on-black binary mask."""
    gray = image.convert("L")
    # Threshold at midpoint — anything brighter than 128 becomes white
    return gray.point(lambda x: 255 if x > 128 else 0, mode="L").convert("RGB")


def process_frame(
    image: Image.Image,
    prompt: str | None = None,
    negative_prompt: str | None = None,
    num_inference_steps: int | None = None,
    guidance_scale: float | None = None,
    controlnet_conditioning_scale: float | None = None,
) -> Image.Image:
    pipe = load_pipeline()

    size = settings.image_size
    original_size = image.size
    image_resized = image.resize((size, size), Image.LANCZOS)

    depth_map = get_depth_map(image_resized)

    result = pipe(
        prompt=prompt or settings.prompt,
        negative_prompt=negative_prompt or settings.negative_prompt,
        image=depth_map,
        num_inference_steps=num_inference_steps or settings.num_inference_steps,
        guidance_scale=guidance_scale or settings.guidance_scale,
        controlnet_conditioning_scale=(
            controlnet_conditioning_scale
            or settings.controlnet_conditioning_scale
        ),
        width=size,
        height=size,
    ).images[0]

    result = to_silhouette(result)

    # Restore original resolution
    if result.size != original_size:
        result = result.resize(original_size, Image.LANCZOS)

    return result


def process_frames_batch(
    images: list[Image.Image],
    prompt: str | None = None,
    negative_prompt: str | None = None,
    num_inference_steps: int | None = None,
    strength: float | None = None,
    guidance_scale: float | None = None,
    controlnet_conditioning_scale: float | None = None,
) -> list[Image.Image]:
    pipe = load_pipeline()

    size = settings.image_size
    original_sizes = [img.size for img in images]

    images_resized = [img.resize((size, size), Image.LANCZOS) for img in images]
    depth_maps = [get_depth_map(img) for img in images_resized]

    _prompt = prompt or settings.prompt
    _neg = negative_prompt or settings.negative_prompt
    n = len(images)

    results = pipe(
        prompt=[_prompt] * n,
        negative_prompt=[_neg] * n,
        image=depth_maps,
        num_inference_steps=num_inference_steps or settings.num_inference_steps,
        guidance_scale=guidance_scale or settings.guidance_scale,
        controlnet_conditioning_scale=(
            controlnet_conditioning_scale
            or settings.controlnet_conditioning_scale
        ),
        width=size,
        height=size,
    ).images

    # Post-process to binary silhouettes + restore original resolutions
    output = []
    for img, orig_size in zip(results, original_sizes):
        img = to_silhouette(img)
        if img.size != orig_size:
            img = img.resize(orig_size, Image.LANCZOS)
        output.append(img)

    return output


def is_loaded() -> bool:
    return _pipe is not None


def gpu_info() -> dict:
    info = {"gpu_name": None, "gpu_memory_mb": None}
    if torch.cuda.is_available():
        info["gpu_name"] = torch.cuda.get_device_name(0)
        info["gpu_memory_mb"] = torch.cuda.get_device_properties(0).total_memory // (1024 * 1024)
    return info
