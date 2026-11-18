"""Image (and ComfyUI video-clip) generation adapters."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import math
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFilter

from app.core.errors import ProviderError, ProviderNotConfigured
from app.video_engine.fonts import get_font
from app.video_engine.text import wrap_text


@dataclass
class ImageConfig:
    name: str
    model: str = ""
    api_key: str | None = None
    base_url: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageRequest:
    prompt: str
    width: int
    height: int
    headline: str = ""
    language: str = "en"
    primary: str = "#6D28D9"
    secondary: str = "#F59E0B"
    style: str = "motion_graphics"
    seed: int | None = None


class ImageProvider:
    name = "base"
    is_paid = False
    license_type = "ai_generated"
    license_note = ""

    def __init__(self, cfg: ImageConfig):
        self.cfg = cfg

    def generate(self, req: ImageRequest, out: Path) -> Path:
        raise NotImplementedError

    def health(self) -> tuple[bool, str]:
        raise NotImplementedError


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    img = img.resize((math.ceil(img.width * scale), math.ceil(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


class ProceduralImages(ImageProvider):
    """Original abstract motion-graphics backgrounds drawn with Pillow. Free, offline, fully owned."""

    name = "procedural"
    license_type = "procedural_generated"
    license_note = "Generated procedurally by this application; no third-party content."

    def health(self):
        return True, "offline Pillow renderer"

    def generate(self, req: ImageRequest, out: Path) -> Path:
        seed = req.seed if req.seed is not None else int(hashlib.sha1(req.prompt.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)
        w, h = req.width, req.height
        p, s = _hex(req.primary), _hex(req.secondary)
        dark = _mix(p, (8, 8, 20), 0.75)
        # Diagonal gradient (computed small, then upscaled — fast).
        small = Image.new("RGB", (64, 64))
        px = small.load()
        angle = rng.random() * math.pi
        for y in range(64):
            for x in range(64):
                t = ((x / 63) * math.cos(angle) + (y / 63) * math.sin(angle) + 1) / 2.5
                px[x, y] = _mix(dark, p, max(0.0, min(1.0, t)))
        img = small.resize((w, h), Image.BICUBIC)
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for _ in range(rng.randint(5, 9)):
            r = rng.randint(min(w, h) // 10, min(w, h) // 2)
            cx, cy = rng.randint(-r // 2, w + r // 2), rng.randint(-r // 2, h + r // 2)
            col = s if rng.random() < 0.4 else _mix(p, (255, 255, 255), rng.random() * 0.5)
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*col, rng.randint(25, 70)))
        for _ in range(rng.randint(3, 6)):  # accent lines
            y0 = rng.randint(0, h)
            d.line((0, y0, w, y0 + rng.randint(-h // 3, h // 3)), fill=(*s, 60), width=rng.randint(3, 10))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=max(2, min(w, h) // 120)))
        img = Image.alpha_composite(img.convert("RGBA"), layer)
        if req.headline:
            self._headline(img, req)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.convert("RGB").save(out, "PNG")
        return out

    @staticmethod
    def _headline(img: Image.Image, req: ImageRequest) -> None:
        w, h = img.size
        size = int(min(w, h) * 0.085)
        font = get_font(size, req.language)
        d = ImageDraw.Draw(img)
        lines = wrap_text(d, req.headline, font, int(w * 0.84))[:3]
        y = int(h * (0.16 if h > w else 0.12))
        for line in lines:
            tw = d.textlength(line, font=font)
            d.text(((w - tw) / 2, y), line, font=font, fill=(255, 255, 255), stroke_width=max(2, size // 14),
                   stroke_fill=(0, 0, 0))
            y += int(size * 1.2)


class ComfyUIClient:
    """Runs a user-supplied ComfyUI API-format workflow. Placeholders replaced in every string value:
    {{prompt}}, {{negative}}, {{width}}, {{height}}, {{seed}}, {{frames}}."""

    def __init__(self, base_url: str | None, workflow: dict | None):
        if not base_url:
            raise ProviderNotConfigured("ComfyUI base URL is not set (e.g. http://localhost:8188)")
        if not workflow:
            raise ProviderNotConfigured("No ComfyUI workflow JSON saved for this provider (export with 'Save (API format)')")
        self.base = base_url.rstrip("/")
        self.workflow = workflow

    def _fill(self, node: Any, values: dict[str, Any]) -> Any:
        if isinstance(node, dict):
            return {k: self._fill(v, values) for k, v in node.items()}
        if isinstance(node, list):
            return [self._fill(v, values) for v in node]
        if isinstance(node, str):
            for k, v in values.items():
                token = "{{" + k + "}}"
                if node == token:
                    return v  # keep numeric type
                node = node.replace(token, str(v))
        return node

    def run(self, values: dict[str, Any], timeout: int = 1800) -> tuple[bytes, str]:
        wf = self._fill(copy.deepcopy(self.workflow), values)
        try:
            r = httpx.post(f"{self.base}/prompt", json={"prompt": wf}, timeout=30)
            r.raise_for_status()
            pid = r.json()["prompt_id"]
            deadline = time.time() + timeout
            while time.time() < deadline:
                h = httpx.get(f"{self.base}/history/{pid}", timeout=30).json()
                if pid in h:
                    status = h[pid].get("status", {})
                    if status.get("status_str") == "error":
                        raise ProviderError(f"ComfyUI workflow error: {json.dumps(status)[:300]}", retryable=False)
                    for node_out in h[pid].get("outputs", {}).values():
                        for key in ("videos", "gifs", "images"):
                            for f in node_out.get(key, []):
                                v = httpx.get(f"{self.base}/view", params={"filename": f["filename"], "subfolder": f.get("subfolder", ""),
                                                                          "type": f.get("type", "output")}, timeout=120)
                                v.raise_for_status()
                                return v.content, Path(f["filename"]).suffix
                    raise ProviderError("ComfyUI finished without image/video outputs", retryable=False)
                time.sleep(2)
        except httpx.HTTPError as e:
            raise ProviderError(f"ComfyUI request failed: {e}") from e
        raise ProviderError("ComfyUI timed out")

    def health(self) -> tuple[bool, str]:
        try:
            r = httpx.get(f"{self.base}/system_stats", timeout=5)
            dev = r.json().get("devices", [{}])[0]
            return True, f"{dev.get('name', 'device')} VRAM free {round(dev.get('vram_free', 0) / 1e9, 1)} GB"
        except (httpx.HTTPError, ValueError, IndexError) as e:
            return False, f"ComfyUI unreachable: {e}"


class ComfyUIImages(ImageProvider):
    name = "comfyui"
    license_type = "ai_generated"
    license_note = "Generated locally with ComfyUI — check the checkpoint's license permits commercial use."

    def _client(self):
        return ComfyUIClient(self.cfg.base_url, self.cfg.params.get("workflow"))

    def generate(self, req, out):
        seed = req.seed if req.seed is not None else random.randint(0, 2**31)
        data, _ = self._client().run({"prompt": f"{req.prompt}, {req.style}", "negative": "text, watermark, logo, trademark",
                                      "width": req.width, "height": req.height, "seed": seed})
        img = fit_cover(Image.open(io.BytesIO(data)).convert("RGB"), req.width, req.height)
        if req.headline:
            ProceduralImages._headline(img, req)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "PNG")
        return out

    def health(self):
        try:
            return self._client().health()
        except ProviderNotConfigured as e:
            return False, str(e)


class OpenAIImages(ImageProvider):
    name = "openai"
    is_paid = True
    license_type = "ai_generated"
    license_note = "OpenAI image output — ownership assigned to user per OpenAI terms."

    def generate(self, req, out):
        if not self.cfg.api_key:
            raise ProviderNotConfigured("OpenAI API key is not configured")
        size = "1024x1536" if req.height > req.width else "1536x1024"
        prompt = (f"{req.prompt}. Style: {req.style}. Original artwork, no text, no logos, "
                  "no real people, no copyrighted characters.")
        try:
            r = httpx.post("https://api.openai.com/v1/images/generations", timeout=300,
                           headers={"Authorization": f"Bearer {self.cfg.api_key}"},
                           json={"model": self.cfg.model or "gpt-image-1", "prompt": prompt, "size": size, "n": 1})
        except httpx.HTTPError as e:
            raise ProviderError(f"OpenAI Images unreachable: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"OpenAI Images error {r.status_code}: {r.text[:300]}", retryable=r.status_code in (429, 500, 503))
        img = Image.open(io.BytesIO(base64.b64decode(r.json()["data"][0]["b64_json"]))).convert("RGB")
        img = fit_cover(img, req.width, req.height)
        if req.headline:
            ProceduralImages._headline(img, req)
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out, "PNG")
        return out

    def health(self):
        return (bool(self.cfg.api_key), "API key set" if self.cfg.api_key else "API key missing")


IMAGE_PROVIDERS: dict[str, type[ImageProvider]] = {
    "procedural": ProceduralImages, "comfyui": ComfyUIImages, "openai": OpenAIImages,
}


class ComfyUIVideo:
    """Short AI video clips (Wan / LTX-Video) through a ComfyUI workflow. Requires a capable GPU."""

    name = "comfyui"
    license_note = "Generated locally with ComfyUI video model — verify model license (Wan: Apache-2.0; LTX: see model card)."

    def __init__(self, cfg: ImageConfig):
        self.cfg = cfg

    def generate(self, prompt: str, width: int, height: int, seconds: float, out: Path) -> Path:
        client = ComfyUIClient(self.cfg.base_url, self.cfg.params.get("workflow"))
        fps = int(self.cfg.params.get("fps", 16))
        data, suffix = client.run({"prompt": prompt, "negative": "text, watermark, logo", "width": width, "height": height,
                                   "seed": random.randint(0, 2**31), "frames": int(seconds * fps) + 1})
        raw = out.with_suffix(suffix or ".mp4")
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(data)
        return raw

    def health(self):
        try:
            return ComfyUIClient(self.cfg.base_url, self.cfg.params.get("workflow")).health()
        except ProviderNotConfigured as e:
            return False, str(e)
