import platform
import shutil

import pytest

from app.integrations.image.providers import ImageRequest, ProceduralImages
from app.integrations.tts.providers import SystemTTS, TTSConfig
from app.video_engine import ffmpeg
from app.video_engine.renderer import RenderSpec, SceneInput, render, write_srt


@pytest.mark.skipif(not (shutil.which("espeak-ng") or platform.system() == "Windows"), reason="no system TTS")
def test_real_voice_render(tmp_path):
    tts = SystemTTS(TTSConfig(name="system"))
    scenes = []
    for i, text in enumerate(["A quick test of the narration engine.", "Captions should follow the voice."]):
        img = ProceduralImages(None).generate(ImageRequest(prompt=text, width=1280, height=720, headline="Test" if i == 0 else ""),
                                              tmp_path / f"{i}.png")
        secs = tts.synthesize(text, "en", tmp_path / f"{i}.wav")
        assert secs > 1
        scenes.append(SceneInput(narration=text, audio=tmp_path / f"{i}.wav", audio_seconds=secs, image=img))
    res = render(RenderSpec(width=1280, height=720, scenes=scenes, workdir=tmp_path / "w", output=tmp_path / "out.mp4"))
    p = ffmpeg.probe(res.path)
    assert (p.width, p.height, p.video_codec, p.audio_codec) == (1280, 720, "h264", "aac")
    assert abs(p.duration - sum(s.audio_seconds for s in scenes)) < 2
    srt = write_srt(res.cues, tmp_path / "s.srt").read_text()
    assert "-->" in srt and "Captions" in srt
