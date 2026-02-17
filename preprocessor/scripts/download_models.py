"""Pre-download models for baked Docker image."""

from diffusers import ControlNetModel, StableDiffusionControlNetImg2ImgPipeline
from controlnet_aux import MidasDetector

MODEL_ID = "stable-diffusion-v1-5/stable-diffusion-v1-5"
CONTROLNET_ID = "lllyasviel/control_v11f1p_sd15_depth"

print(f"Downloading ControlNet: {CONTROLNET_ID}")
ControlNetModel.from_pretrained(CONTROLNET_ID)

print(f"Downloading SD 1.5: {MODEL_ID}")
controlnet = ControlNetModel.from_pretrained(CONTROLNET_ID)
StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
    MODEL_ID, controlnet=controlnet,
)

print("Downloading MiDaS depth estimator")
MidasDetector.from_pretrained("lllyasviel/Annotators")

print("All models downloaded successfully")
