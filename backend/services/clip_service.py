import json
import numpy as np
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
import torch
import io

_model = None
_processor = None
MODEL_NAME = "openai/clip-vit-base-patch32"


def _load():
    global _model, _processor
    if _model is None:
        print("[clip] loading model…")
        _model = CLIPModel.from_pretrained(MODEL_NAME)
        _processor = CLIPProcessor.from_pretrained(MODEL_NAME)
        _model.eval()
        print("[clip] model ready")


def _to_tensor(feats) -> torch.Tensor:
    """Extract tensor from get_image_features output regardless of return type."""
    if isinstance(feats, torch.Tensor):
        return feats
    if hasattr(feats, 'image_embeds'):
        return feats.image_embeds
    if hasattr(feats, 'pooler_output'):
        return feats.pooler_output
    if hasattr(feats, 'last_hidden_state'):
        return feats.last_hidden_state[:, 0]
    raise ValueError(f"Cannot extract tensor from {type(feats)}")


def embed_images(image_bytes_list: list[bytes]) -> list[list[float]]:
    """Return one CLIP embedding per image (list of floats, L2-normalised)."""
    _load()
    images = [Image.open(io.BytesIO(b)).convert("RGB") for b in image_bytes_list]
    inputs = _processor(images=images, return_tensors="pt")
    with torch.no_grad():
        feats = _to_tensor(_model.get_image_features(pixel_values=inputs["pixel_values"]))
    feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats.cpu().numpy().tolist()


def embed_single(image_bytes: bytes) -> np.ndarray:
    """Return a single L2-normalised CLIP embedding as numpy array."""
    _load()
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    inputs = _processor(images=[image], return_tensors="pt")
    with torch.no_grad():
        feats = _to_tensor(_model.get_image_features(pixel_values=inputs["pixel_values"]))
    feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats.cpu().numpy()[0]


def best_match(
    query_embedding: np.ndarray,
    candidates: list[dict],  # [{"id": ..., "name": ..., "embeddings": [[...], ...], "ad_video_url": ...}]
    threshold: float = 0.20,
    margin: float = 0.07,
) -> dict | None:
    """
    Compare query against all candidate product embeddings.
    Each product has multiple reference embeddings (one per uploaded photo).
    Returns the best-matching product only if:
      - its score is above threshold, AND
      - it beats the second-best by at least `margin` (avoids ambiguous matches).
    """
    scored = []
    for candidate in candidates:
        ref_embeddings = np.array(candidate["embeddings"])  # shape (N, 512)
        scores = ref_embeddings @ query_embedding            # cosine sim (already normalised)
        scored.append((float(scores.max()), candidate))

    scored.sort(key=lambda x: x[0], reverse=True)
    print("[clip] scores:", [(round(s,3), c["name"]) for s, c in scored])

    if not scored or scored[0][0] < threshold:
        return None

    # Require clear winner when multiple products exist
    if len(scored) >= 2 and (scored[0][0] - scored[1][0]) < margin:
        return None

    score, winner = scored[0]
    return {**winner, "score": score}
