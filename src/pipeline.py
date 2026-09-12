"""Orchestrate: topic -> script -> voice -> visuals -> assemble -> upload."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from .assembler import build_video
from .config import Config
from .script_generator import generate_script, scene_count_for_duration
from .visuals import gather_scene_assets
from .voiceover import synthesize


def _slug(text: str) -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (ascii_part or "video")[:40]


def run_pipeline(topic: str, cfg: Config, do_upload: bool | None = None) -> dict:
    if do_upload is None:
        do_upload = cfg.get("upload", "enabled", default=False)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    job_dir = cfg.path("output", f"{stamp}-{_slug(topic)}")
    job_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n=== Topic: {topic}\n    Output: {job_dir}")

    # 1. Script -------------------------------------------------------------
    print("[1/5] Generating Gujarati script...")
    script = generate_script(topic, cfg)
    (job_dir / "script.json").write_text(script.to_json(), encoding="utf-8")
    print(f"      Title: {script.title}")

    # 2. Voiceover + subtitles ---------------------------------------------
    print("[2/5] Synthesizing voiceover (ElevenLabs)...")
    voice = synthesize(script.narration, job_dir, cfg)
    print(f"      Duration: {voice.duration_sec:.1f}s")

    # 3. Visuals ------------------------------------------------------------
    # Scene count follows the real narration length and the desired pace
    # (a new scene every ~seconds_per_scene), so the video is never static.
    n_scenes = scene_count_for_duration(
        voice.duration_sec or cfg.get("channel", "target_duration_sec", default=90), cfg
    )
    sps = cfg.get("visuals", "seconds_per_scene", default=3.5)
    print(f"[3/5] Gathering {n_scenes} distinct visuals (~{sps}s/scene, photos + video)...")
    assets = gather_scene_assets(script.scenes, job_dir / "images", cfg, count=n_scenes)
    kinds = ", ".join(a.kind[0] for a in assets)  # e.g. "i,v,i,v,..."
    print(f"      {len(assets)} scenes [{kinds}]")

    # 4. Assemble -----------------------------------------------------------
    print("[4/5] Assembling video (ffmpeg: motion, SFX, music, captions)...")
    out_path = job_dir / "final.mp4"
    build_video(
        images=assets,
        audio_path=voice.audio_path,
        srt_path=voice.srt_path,
        duration_sec=voice.duration_sec or cfg.get("channel", "target_duration_sec", default=90),
        out_path=out_path,
        cfg=cfg,
    )
    print(f"      Wrote {out_path}")

    result = {
        "topic": topic,
        "title": script.title,
        "video_path": str(out_path),
        "job_dir": str(job_dir),
        "uploaded": False,
        "video_id": None,
    }

    # 5. Upload -------------------------------------------------------------
    if do_upload:
        print("[5/5] Uploading to YouTube...")
        from .uploader import upload_video

        video_id = upload_video(out_path, script, cfg)
        result["uploaded"] = True
        result["video_id"] = video_id
    else:
        print("[5/5] Upload skipped (disabled).")

    (job_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
