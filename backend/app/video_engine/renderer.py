"""FFmpeg render pipeline: scenes -> captioned clips -> concat -> music + loudness -> MP4 (H.264/AAC)."""
from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from app.video_engine import ffmpeg
from app.video_engine.fonts import get_font
from app.video_engine.text import chunk_caption, wrap_text

log = logging.getLogger(__name__)
FPS = 30


@dataclass
class SceneInput:
    narration: str
    audio: Path
    audio_seconds: float
    image: Path | None = None
    clip: Path | None = None  # optional AI video clip, used instead of the still


@dataclass
class RenderSpec:
    width: int
    height: int
    scenes: list[SceneInput]
    workdir: Path
    output: Path
    language: str = "en"
    burn_subtitles: bool = True
    music: bool = True
    music_seed: str = "default"
    crf: int = 21
    preset: str = "veryfast"
    caption_words: int = 5


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass
class RenderResult:
    path: Path
    duration: float
    cues: list[Cue] = field(default_factory=list)
    music_path: Path | None = None


def _caption_png(text: str, w: int, h: int, language: str, out: Path) -> None:
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    size = int(min(w, h) * (0.068 if h > w else 0.05))
    font = get_font(size, language)
    lines = wrap_text(d, text, font, int(w * 0.86))[:3]
    line_h = int(size * 1.25)
    block_h = line_h * len(lines)
    y = int(h * (0.70 if h > w else 0.80)) - block_h // 2
    pad = size // 3
    widest = max(d.textlength(line, font=font) for line in lines)
    d.rounded_rectangle(((w - widest) / 2 - pad * 2, y - pad, (w + widest) / 2 + pad * 2, y + block_h + pad),
                        radius=pad * 2, fill=(0, 0, 0, 150))
    for line in lines:
        tw = d.textlength(line, font=font)
        d.text(((w - tw) / 2, y), line, font=font, fill=(255, 255, 255, 255), stroke_width=max(1, size // 18), stroke_fill=(0, 0, 0, 255))
        y += line_h
    img.save(out, "PNG")


def _scene_cues(narration: str, start: float, seconds: float, words: int) -> list[Cue]:
    chunks = chunk_caption(narration, words) or [narration]
    total = sum(len(c) for c in chunks) or 1
    cues, t = [], start
    for c in chunks:  # time proportional to characters — a good proxy for speech time
        dur = seconds * len(c) / total
        cues.append(Cue(t, t + dur, c))
        t += dur
    return cues


def render_scene(spec: RenderSpec, idx: int, scene: SceneInput, start: float) -> tuple[Path, float, list[Cue]]:
    w, h = spec.width, spec.height
    seconds = round(scene.audio_seconds + 0.35, 3)
    frames = int(seconds * FPS)
    out = spec.workdir / f"scene_{idx:03d}.mp4"
    speech_offset = 0.15
    cues = _scene_cues(scene.narration, start + speech_offset, scene.audio_seconds, spec.caption_words)

    inputs: list[str] = []
    if scene.clip:
        inputs += ["-stream_loop", "-1", "-i", str(scene.clip)]
        base = f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={FPS},setsar=1[bg]"
    else:
        inputs += ["-loop", "1", "-framerate", str(FPS), "-i", str(scene.image)]
        zoom_dir = idx % 2  # alternate zoom-in / zoom-out for variety
        zexpr = "min(1.0+0.0009*on,1.15)" if zoom_dir == 0 else "max(1.15-0.0009*on,1.0)"
        base = (f"[0:v]scale={int(w * 1.2)}:{int(h * 1.2)},"
                f"zoompan=z='{zexpr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS},setsar=1[bg]")
    inputs += ["-i", str(scene.audio)]
    filters = [base]
    last = "bg"
    if spec.burn_subtitles:
        for j, cue in enumerate(cues):
            png = spec.workdir / f"cap_{idx:03d}_{j:02d}.png"
            _caption_png(cue.text, w, h, spec.language, png)
            inputs += ["-i", str(png)]
            a, b = cue.start - start, cue.end - start
            filters.append(f"[{last}][{j + 2}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[v{j}]")
            last = f"v{j}"
    fade_out = max(0.0, seconds - 0.2)
    filters.append(f"[{last}]fade=t=in:st=0:d=0.2,fade=t=out:st={fade_out:.3f}:d=0.2,format=yuv420p[vout]")
    filters.append(f"[1:a]adelay={int(speech_offset * 1000)}:all=1,apad,atrim=0:{seconds},aresample=44100,"
                   f"aformat=channel_layouts=stereo[aout]")
    ffmpeg.run([
        *inputs, "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
        "-t", f"{seconds}", "-r", str(FPS), "-c:v", "libx264", "-preset", spec.preset, "-crf", str(spec.crf),
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(out),
    ])
    return out, seconds, cues


CHORDS = [
    (220.00, 277.18, 329.63),  # A major
    (196.00, 246.94, 293.66),  # G major
    (174.61, 220.00, 261.63),  # F major
    (164.81, 196.00, 246.94),  # E minor
    (146.83, 174.61, 220.00),  # D minor
]


def make_music(seconds: float, seed: str, out: Path) -> Path:
    """Original ambient pad synthesised by FFmpeg (no third-party audio => clean provenance)."""
    a, b, c = CHORDS[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(CHORDS)]
    expr = (f"0.30*sin(2*PI*{a}*t)*(0.6+0.4*sin(2*PI*0.11*t))"
            f"+0.22*sin(2*PI*{b}*t)*(0.6+0.4*sin(2*PI*0.07*t+1))"
            f"+0.20*sin(2*PI*{c}*t)*(0.6+0.4*sin(2*PI*0.05*t+2))"
            f"+0.12*sin(2*PI*{a / 2}*t)")
    fade_out = max(0.0, seconds - 2)
    ffmpeg.run(["-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d={seconds:.2f}",
                "-af", f"lowpass=f=1800,aecho=0.8:0.6:120:0.3,afade=t=in:d=1.5,afade=t=out:st={fade_out:.2f}:d=2,"
                       "aformat=channel_layouts=stereo",
                "-c:a", "pcm_s16le", str(out)])
    return out


def render(spec: RenderSpec) -> RenderResult:
    spec.workdir.mkdir(parents=True, exist_ok=True)
    clips, cues, t = [], [], 0.0
    for i, sc in enumerate(spec.scenes):
        clip, secs, scene_cues = render_scene(spec, i, sc, t)
        clips.append(clip)
        cues.extend(scene_cues)
        t += secs
    listfile = spec.workdir / "concat.txt"
    listfile.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    joined = spec.workdir / "joined.mp4"
    ffmpeg.run(["-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(joined)])

    music_path = None
    spec.output.parent.mkdir(parents=True, exist_ok=True)
    loud = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if spec.music:
        music_path = make_music(t, spec.music_seed, spec.workdir / "music.wav")
        ffmpeg.run(["-i", str(joined), "-i", str(music_path), "-filter_complex",
                    f"[1:a]volume=0.10[m];[0:a][m]amix=inputs=2:duration=first:normalize=0,{loud}[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                    "-movflags", "+faststart", str(spec.output)])
    else:
        ffmpeg.run(["-i", str(joined), "-af", loud, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
                    "-movflags", "+faststart", str(spec.output)])
    duration = ffmpeg.probe(spec.output).duration
    return RenderResult(path=spec.output, duration=duration, cues=cues, music_path=music_path)


def write_srt(cues: list[Cue], out: Path) -> Path:
    def ts(x: float) -> str:
        ms = int(round(x * 1000))
        hh, ms = divmod(ms, 3600000)
        mm, ms = divmod(ms, 60000)
        ss, ms = divmod(ms, 1000)
        return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"

    out.write_text("\n".join(f"{i}\n{ts(c.start)} --> {ts(c.end)}\n{c.text}\n" for i, c in enumerate(cues, 1)), encoding="utf-8")
    return out


def make_thumbnail(base_image: Path | None, text: str, language: str, primary: str, out: Path) -> Path:
    from app.integrations.image.providers import ImageRequest, ProceduralImages, fit_cover

    W, H = 1280, 720
    if base_image and base_image.exists():
        img = fit_cover(Image.open(base_image).convert("RGB"), W, H)
    else:
        tmp = out.with_suffix(".bg.png")
        ProceduralImages(None).generate(ImageRequest(prompt=text, width=W, height=H, primary=primary), tmp)  # type: ignore[arg-type]
        img = Image.open(tmp).convert("RGB")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rectangle((0, int(H * 0.55), W, H), fill=(0, 0, 0, 140))
    img = Image.alpha_composite(img.convert("RGBA"), overlay)
    d = ImageDraw.Draw(img)
    font = get_font(96, language)
    lines = wrap_text(d, text.upper(), font, int(W * 0.9))[:2]
    y = int(H * 0.60)
    for line in lines:
        tw = d.textlength(line, font=font)
        d.text(((W - tw) / 2, y), line, font=font, fill=(255, 230, 0), stroke_width=5, stroke_fill=(0, 0, 0))
        y += 110
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out


def cleanup(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
