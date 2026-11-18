"""Interchangeable text-to-speech providers. Each writes a 44.1kHz mono WAV and returns its duration."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.core.errors import ProviderError, ProviderNotConfigured
from app.video_engine import ffmpeg

# espeak-ng language codes for supported languages (Hinglish uses the Hindi voice).
ESPEAK_LANG = {
    "en": "en-us", "hi": "hi", "hinglish": "hi", "mr": "mr", "gu": "gu", "ta": "ta", "te": "te",
    "kn": "kn", "ml": "ml", "bn": "bn", "es": "es", "fr": "fr", "ar": "ar",
}


@dataclass
class TTSConfig:
    name: str
    voice: str = "default"
    api_key: str | None = None
    base_url: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


class TTSProvider:
    name = "base"
    is_paid = False
    license_note = ""

    def __init__(self, cfg: TTSConfig):
        self.cfg = cfg

    def synthesize(self, text: str, language: str, out_wav: Path) -> float:
        raise NotImplementedError

    def health(self) -> tuple[bool, str]:
        raise NotImplementedError

    @staticmethod
    def _finish(raw: Path, out_wav: Path) -> float:
        ffmpeg.to_wav(raw, out_wav)
        return ffmpeg.probe(out_wav).duration


class MockTTS(TTSProvider):
    """Silent audio whose length matches natural speech pace. For tests only."""

    name = "mock"
    license_note = "silence (no voice)"

    def synthesize(self, text, language, out_wav):
        seconds = max(1.5, len(text.split()) / 2.5)
        ffmpeg.silence(out_wav, seconds)
        return seconds

    def health(self):
        return True, "generates silent placeholder narration"


class SystemTTS(TTSProvider):
    """Offline OS voice: espeak-ng on Linux/Docker (many languages), SAPI on Windows."""

    name = "system"
    license_note = "OS-provided synthetic voice (espeak-ng GPLv3 output / Windows SAPI)"

    def _espeak(self):
        return shutil.which("espeak-ng") or shutil.which("espeak")

    def synthesize(self, text, language, out_wav):
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as td:
            raw = Path(td) / "raw.wav"
            exe = self._espeak()
            if exe:
                voice = ESPEAK_LANG.get(language, "en-us")
                rate = str(self.cfg.params.get("rate", 165))
                subprocess.run([exe, "-v", voice, "-s", rate, "-w", str(raw), text], check=True, capture_output=True, timeout=300)
            elif platform.system() == "Windows":
                txt = Path(td) / "t.txt"
                txt.write_text(text, encoding="utf-8")
                ps = (
                    "Add-Type -AssemblyName System.Speech;"
                    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                    f"$s.Rate={int(self.cfg.params.get('sapi_rate', 0))};"
                    f"$s.SetOutputToWaveFile('{raw}');"
                    f"$s.Speak([IO.File]::ReadAllText('{txt}'));$s.Dispose()"
                )
                proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                                      capture_output=True, text=True, timeout=300)
                if proc.returncode != 0 or not raw.exists():
                    raise ProviderError(f"Windows SAPI failed: {proc.stderr[:300]}", retryable=False)
            else:
                raise ProviderNotConfigured("No system TTS found. Install espeak-ng (apt install espeak-ng).")
            return self._finish(raw, out_wav)

    def health(self):
        if self._espeak():
            return True, f"espeak-ng at {self._espeak()}"
        if platform.system() == "Windows":
            return True, "Windows SAPI (English voices; install language packs for others)"
        return False, "espeak-ng not installed"


class KokoroTTS(TTSProvider):
    """Kokoro-FastAPI (OpenAI-compatible /v1/audio/speech). Apache-2.0 model weights."""

    name = "kokoro"
    license_note = "Kokoro-82M (Apache-2.0) synthetic voice"

    def _base(self):
        if not self.cfg.base_url:
            raise ProviderNotConfigured("Kokoro base URL is not set (e.g. http://localhost:8880)")
        return self.cfg.base_url.rstrip("/")

    def synthesize(self, text, language, out_wav):
        try:
            r = httpx.post(f"{self._base()}/v1/audio/speech", timeout=300, json={
                "model": "kokoro", "input": text, "voice": self.cfg.voice or "af_heart", "response_format": "wav",
                "speed": float(self.cfg.params.get("speed", 1.0)),
            })
        except httpx.HTTPError as e:
            raise ProviderError(f"Kokoro unreachable: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"Kokoro error {r.status_code}: {r.text[:200]}")
        return _save_and_finish(r.content, ".wav", out_wav)

    def health(self):
        try:
            r = httpx.get(f"{self._base()}/v1/audio/voices", timeout=5)
            return r.status_code == 200, "ok" if r.status_code == 200 else f"HTTP {r.status_code}"
        except (ProviderNotConfigured, httpx.HTTPError) as e:
            return False, str(e)


class PiperTTS(TTSProvider):
    """Piper HTTP server (`python -m piper.http_server`). Voice license depends on the chosen model."""

    name = "piper"
    license_note = "Piper voice model — check the voice's model card license"

    def _base(self):
        if not self.cfg.base_url:
            raise ProviderNotConfigured("Piper base URL is not set (e.g. http://localhost:5000)")
        return self.cfg.base_url.rstrip("/")

    def synthesize(self, text, language, out_wav):
        try:
            r = httpx.post(self._base(), json={"text": text}, timeout=300)
        except httpx.HTTPError as e:
            raise ProviderError(f"Piper unreachable: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"Piper error {r.status_code}: {r.text[:200]}")
        return _save_and_finish(r.content, ".wav", out_wav)

    def health(self):
        try:
            httpx.get(self._base(), timeout=5)
            return True, "reachable"
        except (ProviderNotConfigured, httpx.HTTPError) as e:
            return False, str(e)


class OpenAITTS(TTSProvider):
    name = "openai"
    is_paid = True
    license_note = "OpenAI TTS — AI-generated voice; disclose as synthetic per OpenAI usage policy"

    def synthesize(self, text, language, out_wav):
        if not self.cfg.api_key:
            raise ProviderNotConfigured("OpenAI API key is not configured")
        try:
            r = httpx.post("https://api.openai.com/v1/audio/speech", timeout=300,
                           headers={"Authorization": f"Bearer {self.cfg.api_key}"},
                           json={"model": self.cfg.params.get("model", "gpt-4o-mini-tts"), "input": text,
                                 "voice": self.cfg.voice if self.cfg.voice != "default" else "alloy", "response_format": "wav"})
        except httpx.HTTPError as e:
            raise ProviderError(f"OpenAI TTS unreachable: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"OpenAI TTS error {r.status_code}: {r.text[:200]}", retryable=r.status_code in (429, 500, 503))
        return _save_and_finish(r.content, ".wav", out_wav)

    def health(self):
        return (bool(self.cfg.api_key), "API key set" if self.cfg.api_key else "API key missing")


def _save_and_finish(content: bytes, suffix: str, out_wav: Path) -> float:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        return TTSProvider._finish(Path(tmp), out_wav)
    finally:
        os.unlink(tmp)


TTS_PROVIDERS: dict[str, type[TTSProvider]] = {
    "mock": MockTTS, "system": SystemTTS, "kokoro": KokoroTTS, "piper": PiperTTS, "openai": OpenAITTS,
}
