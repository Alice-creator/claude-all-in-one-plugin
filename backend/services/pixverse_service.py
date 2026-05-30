import os
import uuid
import httpx
import asyncio

PIXVERSE_API_KEY = os.getenv("PIXVERSE_API_KEY")
PIXVERSE_BASE_URL = "https://app-api.pixverse.ai"
POLL_INTERVAL = 5
POLL_TIMEOUT = 300


async def upload_image(image_path: str) -> int:
    with open(image_path, "rb") as f:
        files = {"image": f}
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{PIXVERSE_BASE_URL}/openapi/v2/image/upload",
                headers={"API-KEY": PIXVERSE_API_KEY},
                files=files,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("ErrCode") != 0:
                raise RuntimeError(f"PixVerse image upload failed: {data.get('ErrMsg')}")
            img_id = data["Resp"]["img_id"]
            print(f"[pixverse] Uploaded image: {img_id}")
            return img_id


async def get_balance() -> dict:
    """Check the current API credit balance."""
    trace_id = str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{PIXVERSE_BASE_URL}/openapi/v2/account/balance",
            headers={
                "API-KEY": PIXVERSE_API_KEY,
                "ai-trace-id": trace_id
            },
        )
        response.raise_for_status()
        data = response.json()
        if data.get("ErrCode") != 0:
            raise RuntimeError(f"Failed to fetch balance: {data.get('ErrMsg')}")
        
        balance = data["Resp"]
        print(f"[pixverse] API Balance - Monthly: {balance['credit_monthly']}, Package: {balance['credit_package']}")
        return balance


async def generate_video_from_image(
    img_id: int,
    prompt: str,
    model: str = "v6",
    duration: int = 5,
    quality: str = "540p",
    motion_mode: str = "normal",
    negative_prompt: str = "blurry, low quality, distorted",
) -> str:
    trace_id = str(uuid.uuid4())
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{PIXVERSE_BASE_URL}/openapi/v2/video/img/generate",
            headers={
                "API-KEY": PIXVERSE_API_KEY,
                "AI-trace-id": trace_id,
                "Content-Type": "application/json",
            },
            json={
                "img_id": img_id,
                "prompt": prompt,
                "model": model,
                "duration": duration,
                "quality": quality,
                "motion_mode": motion_mode,
                "negative_prompt": negative_prompt,
            },
        )
        response.raise_for_status()
        data = response.json()
        if data.get("ErrCode") != 0:
            raise RuntimeError(f"PixVerse video generation failed: {data.get('ErrMsg')}")
        
        video_id = data["Resp"]["video_id"]
        print(f"[pixverse] Submitted video job {video_id} with trace {trace_id}")
        
        video_url = await _poll_video_status(video_id)
        print(f"[pixverse] Video ready: {video_url}")
        return video_url


async def generate_video_from_text(
    prompt: str,
    model: str = "v6",
    duration: int = 5,
    quality: str = "540p",
    aspect_ratio: str = "16:9",
    motion_mode: str = "normal",
    negative_prompt: str = "blurry, low quality, distorted",
) -> str:
    trace_id = str(uuid.uuid4())
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{PIXVERSE_BASE_URL}/openapi/v2/video/t2v/generate",
            headers={
                "API-KEY": PIXVERSE_API_KEY,
                "AI-trace-id": trace_id,
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "model": model,
                "duration": duration,
                "quality": quality,
                "aspect_ratio": aspect_ratio,
                "motion_mode": motion_mode,
                "negative_prompt": negative_prompt,
            },
        )
        response.raise_for_status()
        data = response.json()
        if data.get("ErrCode") != 0:
            raise RuntimeError(f"PixVerse video generation failed: {data.get('ErrMsg')}")
        
        video_id = data["Resp"]["video_id"]
        print(f"[pixverse] Submitted video job {video_id} with trace {trace_id}")
        
        video_url = await _poll_video_status(video_id)
        print(f"[pixverse] Video ready: {video_url}")
        return video_url


async def _poll_video_status(video_id: int) -> str:
    start_time = asyncio.get_event_loop().time()
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > POLL_TIMEOUT:
                raise TimeoutError(f"Video generation timed out after {POLL_TIMEOUT}s")
            
            response = await client.get(
                f"{PIXVERSE_BASE_URL}/openapi/v2/video/result/{video_id}",
                headers={"API-KEY": PIXVERSE_API_KEY},
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("ErrCode") != 0:
                raise RuntimeError(f"PixVerse status check failed: {data.get('ErrMsg')}")
            
            status = data["Resp"].get("status")
            print(f"[pixverse] Video {video_id} status: {status}")
            
            if status == 1:
                return data["Resp"]["url"]
            elif status in (6, 7, 8):
                error_messages = {6: "deleted", 7: "moderation failed", 8: "generation failed"}
                raise RuntimeError(f"Video generation {error_messages.get(status, 'failed')}")
            
            await asyncio.sleep(POLL_INTERVAL)


async def generate_ad_video(
    product_name: str,
    product_description: str,
    product_style: str = "modern",
    image_path: str = None,
) -> str:
    prompt = (
        f"Professional product showcase of {product_name}. "
        f"{product_description}. "
        f"High-quality {product_style} style commercial video with smooth camera motion, "
        f"studio lighting, and cinematic presentation. "
        f"Clean background, centered product, commercial broadcast quality."
    )
    
    if image_path:
        img_id = await upload_image(image_path)
        return await generate_video_from_image(
            img_id=img_id,
            prompt=prompt,
            model="v6",
            duration=5,
            quality="540p",
            motion_mode="normal",
            negative_prompt="blurry, low quality, distorted, watermark, text, logo",
        )
    else:
        return await generate_video_from_text(
            prompt=prompt,
            model="v6",
            duration=5,
            quality="540p",
            aspect_ratio="16:9",
            motion_mode="normal",
            negative_prompt="blurry, low quality, distorted, watermark, text, logo",
        )
