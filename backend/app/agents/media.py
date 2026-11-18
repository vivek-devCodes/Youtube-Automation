"""Agents 7 (Voice), 8 (Visuals), 9 (Video Production). All steps are idempotent: assets that
already exist on disk + in the DB are reused, so a resumed run never regenerates finished work."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import storage
from app.integrations.image.providers import IMAGE_PROVIDERS, ComfyUIVideo, ImageConfig, ImageRequest
from app.integrations.registry import api_key_for, default_provider, model_config
from app.integrations.tts.providers import TTS_PROVIDERS, TTSConfig
from app.models import (AssetLicense, Channel, MediaAsset, Scene, Script, Subtitle, Thumbnail, Video, VideoMetadata,
                        Voiceover)
from app.services import usage
from app.video_engine import renderer

log = logging.getLogger(__name__)

VOICES = {  # voice_style -> provider-specific voice hints
    "female_warm": {"kokoro": "af_heart", "openai": "nova"},
    "male_calm": {"kokoro": "am_michael", "openai": "onyx"},
    "female_energetic": {"kokoro": "af_bella", "openai": "shimmer"},
    "male_energetic": {"kokoro": "am_adam", "openai": "echo"},
    "child_friendly": {"kokoro": "af_sky", "openai": "fable"},
}


def dims(video: Video, quality: str) -> tuple[int, int]:
    short_side = 720 if quality == "720p" else 1080
    long_side = 1280 if quality == "720p" else 1920
    return (short_side, long_side) if video.format == "short" else (long_side, short_side)


# ===================================================================== Agent 7
def generate_voice(db: Session, script: Script, channel: Channel, run_id: int | None = None) -> dict:
    row = default_provider(db, "tts")
    mc = model_config(db, row, "default")
    voice = VOICES.get(channel.settings.voice_style, {}).get(row.name) or (mc.model_name if mc else "default")
    provider = TTS_PROVIDERS[row.name](TTSConfig(name=row.name, voice=voice, api_key=api_key_for(row), base_url=row.base_url,
                                                  params={**(row.config or {}), "model": mc.model_name if mc else ""}))
    lang = channel.settings.voiceover_language or script.language
    made, reused = 0, 0
    for scene in db.scalars(select(Scene).where(Scene.script_id == script.id).order_by(Scene.idx)).all():
        existing = db.scalar(select(Voiceover).where(Voiceover.script_id == script.id, Voiceover.scene_id == scene.id))
        if existing and storage.exists(existing.path) and existing.provider == row.name:
            reused += 1
            continue
        if provider.is_paid and mc:
            est = len(scene.narration) / 1000 * mc.cost_per_unit
            usage.guard(db, est, f"TTS {row.name}")
        key = f"scripts/{script.id}/voice/scene_{scene.idx:03d}.wav"
        seconds = provider.synthesize(scene.narration, lang, storage.path(key))
        if provider.is_paid and mc:
            usage.record(db, provider=row.name, kind="tts", model=mc.model_name, task="voice", units=len(scene.narration),
                         cost_usd=round(len(scene.narration) / 1000 * mc.cost_per_unit, 6), channel_id=channel.id,
                         workflow_run_id=run_id)
        if existing:
            existing.path, existing.duration_seconds, existing.provider, existing.voice = key, seconds, row.name, voice
            existing.license_note = provider.license_note
        else:
            db.add(Voiceover(script_id=script.id, scene_id=scene.id, provider=row.name, voice=voice, language=lang,
                             path=key, duration_seconds=seconds, license_note=provider.license_note))
        db.commit()
        made += 1
    return {"provider": row.name, "voice": voice, "generated": made, "reused": reused}


# ===================================================================== Agent 8
def generate_visuals(db: Session, script: Script, video: Video, channel: Channel, run_id: int | None = None) -> dict:
    row = default_provider(db, "image")
    mc = model_config(db, row, "default")
    provider = IMAGE_PROVIDERS[row.name](ImageConfig(name=row.name, model=mc.model_name if mc else "", api_key=api_key_for(row),
                                                     base_url=row.base_url, params=row.config or {}))
    vrow = default_provider(db, "video")
    clip_budget = int((vrow.config or {}).get("max_clips_per_video", 2)) if vrow.name != "none" else 0
    w, h = dims(video, channel.settings.video_quality)
    brand = channel.brand
    made = reused = clips = 0
    style = channel.settings.visual_style.replace("_", " ")
    for scene in db.scalars(select(Scene).where(Scene.script_id == script.id).order_by(Scene.idx)).all():
        have = db.scalar(select(MediaAsset).where(MediaAsset.video_id == video.id, MediaAsset.scene_id == scene.id,
                                                  MediaAsset.kind == "image"))
        if not (have and storage.exists(have.path)):
            if provider.is_paid and mc:
                usage.guard(db, mc.cost_per_unit, f"image {row.name}")
            key = f"videos/{video.id}/images/scene_{scene.idx:03d}.png"
            req = ImageRequest(prompt=scene.visual_prompt or scene.narration, width=w, height=h,
                               headline=scene.on_screen_text if scene.idx == 0 else "", language=script.language,
                               primary=brand.primary_color if brand else "#6D28D9",
                               secondary=brand.secondary_color if brand else "#F59E0B", style=style,
                               seed=video.id * 1000 + scene.idx)
            path = provider.generate(req, storage.path(key))
            if provider.is_paid and mc:
                usage.record(db, provider=row.name, kind="image", model=mc.model_name, task="visual", units=1,
                             cost_usd=mc.cost_per_unit, channel_id=channel.id, video_id=video.id, workflow_run_id=run_id)
            _register(db, video, scene, "image", key, row.name, req.prompt, provider.license_type, provider.license_note, w, h)
            made += 1
        else:
            reused += 1
        # Optional AI video clips for the first scenes only (GPU-heavy).
        if clips < clip_budget and scene.idx < clip_budget:
            have_clip = db.scalar(select(MediaAsset).where(MediaAsset.video_id == video.id, MediaAsset.scene_id == scene.id,
                                                           MediaAsset.kind == "video_clip"))
            if not (have_clip and storage.exists(have_clip.path)):
                try:
                    gen = ComfyUIVideo(ImageConfig(name=vrow.name, base_url=vrow.base_url, params=vrow.config or {}))
                    out = gen.generate(f"{scene.visual_prompt}, {style}", w, h, scene.estimated_seconds + 1,
                                       storage.path(f"videos/{video.id}/clips/scene_{scene.idx:03d}.mp4"))
                    _register(db, video, scene, "video_clip", storage.key_for(out), vrow.name, scene.visual_prompt,
                              "ai_generated", gen.license_note, w, h)
                    clips += 1
                except Exception as e:  # clip generation is optional: fall back to animated still
                    log.warning("video clip generation failed for scene %s: %s", scene.idx, e)
    db.commit()
    return {"provider": row.name, "generated": made, "reused": reused, "clips": clips, "size": f"{w}x{h}"}


def _register(db, video, scene, kind, key, provider, prompt, license_type, note, w, h) -> MediaAsset:
    asset = MediaAsset(video_id=video.id, script_id=video.script_id, scene_id=scene.id if scene else None, kind=kind, path=key,
                       provider=provider, prompt=prompt[:2000], width=w, height=h, sha256=storage.sha256(storage.path(key)))
    db.add(asset)
    db.flush()
    db.add(AssetLicense(asset_id=asset.id, license_type=license_type, attribution="", notes=note, verified=True))
    return asset


# ===================================================================== Agent 9
def render_video(db: Session, script: Script, video: Video, channel: Channel) -> dict:
    cs = channel.settings
    w, h = dims(video, cs.video_quality)
    scenes_in = []
    for scene in db.scalars(select(Scene).where(Scene.script_id == script.id).order_by(Scene.idx)).all():
        vo = db.scalar(select(Voiceover).where(Voiceover.script_id == script.id, Voiceover.scene_id == scene.id))
        img = db.scalar(select(MediaAsset).where(MediaAsset.video_id == video.id, MediaAsset.scene_id == scene.id, MediaAsset.kind == "image"))
        clip = db.scalar(select(MediaAsset).where(MediaAsset.video_id == video.id, MediaAsset.scene_id == scene.id, MediaAsset.kind == "video_clip"))
        if not vo or not img:
            raise RuntimeError(f"scene {scene.idx} is missing voice or visual — earlier step incomplete")
        scenes_in.append(renderer.SceneInput(narration=scene.narration, audio=storage.path(vo.path), audio_seconds=vo.duration_seconds,
                                             image=storage.path(img.path), clip=storage.path(clip.path) if clip else None))
    workdir = storage.path(f"videos/{video.id}/work/.keep").parent
    out_key = f"videos/{video.id}/final.mp4"
    spec = renderer.RenderSpec(width=w, height=h, scenes=scenes_in, workdir=workdir, output=storage.path(out_key),
                               language=script.language, burn_subtitles=cs.burn_subtitles, music=cs.background_music,
                               music_seed=f"{channel.id}-{script.music_suggestion}-{video.id}",
                               crf=20 if cs.video_quality == "1080p" else 23)
    res = renderer.render(spec)

    # Music provenance record (synthesised by FFmpeg => original, no licence needed beyond ours)
    if res.music_path:
        mkey = f"videos/{video.id}/music.wav"
        Path(storage.path(mkey)).write_bytes(Path(res.music_path).read_bytes())
        if not db.scalar(select(MediaAsset).where(MediaAsset.video_id == video.id, MediaAsset.kind == "music")):
            _register(db, video, None, "music", mkey, "ffmpeg_synth", script.music_suggestion or "ambient pad",
                      "procedural_generated", "Original ambient pad synthesised by FFmpeg (aevalsrc)", None, None)

    # Subtitles (always produced as SRT sidecar; burned in when configured)
    srt_key = f"videos/{video.id}/subtitles.{script.language}.srt"
    renderer.write_srt(res.cues, storage.path(srt_key))
    sub = db.scalar(select(Subtitle).where(Subtitle.video_id == video.id, Subtitle.language == script.language))
    if not sub:
        db.add(Subtitle(video_id=video.id, language=script.language, format="srt", path=srt_key, burned_in=cs.burn_subtitles))

    # Thumbnail
    meta = db.scalar(select(VideoMetadata).where(VideoMetadata.video_id == video.id))
    first_img = db.scalar(select(MediaAsset).where(MediaAsset.video_id == video.id, MediaAsset.kind == "image").order_by(MediaAsset.id))
    thumb_key = f"videos/{video.id}/thumbnail.jpg"
    text = (meta.thumbnail_text if meta else "") or script.title
    renderer.make_thumbnail(storage.path(first_img.path) if first_img else None, text, script.language,
                            channel.brand.primary_color if channel.brand else "#6D28D9", storage.path(thumb_key))
    if not db.scalar(select(Thumbnail).where(Thumbnail.video_id == video.id, Thumbnail.path == thumb_key)):
        db.add(Thumbnail(video_id=video.id, path=thumb_key, text=text, provider="pillow", is_selected=True))

    video.file_path = out_key
    video.file_size = storage.path(out_key).stat().st_size
    video.duration_seconds = round(res.duration, 2)
    video.width, video.height = w, h
    video.status = "rendered"
    renderer.cleanup(workdir)
    db.commit()
    storage.mirror(out_key)
    return {"duration": video.duration_seconds, "size_mb": round(video.file_size / 1e6, 2), "resolution": f"{w}x{h}",
            "subtitle_cues": len(res.cues)}
