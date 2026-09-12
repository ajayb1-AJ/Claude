"""Orchestrate: topic -> script -> voice -> visuals -> assemble -> upload."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from .assembler import build_video
from .config import Config
from .script_generator import generate_script
from .visuals import gather_images
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
    print("[3/5] Gathering visuals...")
    images = gather_images(script.scenes, job_dir / "images", cfg)
    print(f"      {len(images)} scene image(s)")

    # 4. Assemble -----------------------------------------------------------
    print("[4/5] Assembling video (ffmpeg)...")
    out_path = job_dir / "final.mp4"
    build_video(
        images=images,
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
