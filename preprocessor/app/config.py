from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_id: str = "stable-diffusion-v1-5/stable-diffusion-v1-5"
    controlnet_id: str = "lllyasviel/control_v11f1p_sd15_depth"

    prompt: str = (
        "solid white silhouette of a person, pure black background, "
        "flat white shape, no shading, no detail, binary mask, "
        "black and white only, high contrast"
    )
    negative_prompt: str = (
        "gray, gradient, shading, color, texture, detail, face, "
        "clothing, background detail, noise, grain, realistic, "
        "photograph, 3d render, shadow"
    )

    num_inference_steps: int = 20
    guidance_scale: float = 9.0
    controlnet_conditioning_scale: float = 1.2

    image_size: int = 512
    batch_size: int = 4

    model_config = {"env_prefix": "PREPROCESSOR_"}


settings = Settings()
