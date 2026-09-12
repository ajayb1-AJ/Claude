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


def _dated_dir(cfg: Config) -> Path:
    """A folder named by today's date (YYYY-MM-DD). If more than one video is
    made the same day, add -2, -3, ... so nothing is overwritten."""
    date = time.strftime("%Y-%m-%d")
    base = cfg.path("output", date)
    job = base
    n = 2
    while job.exists():
        job = cfg.path("output", f"{date}-{n}")
        n += 1
    job.mkdir(parents=True, exist_ok=True)
    return job


def run_pipeline(topic: str, cfg: Config, do_upload: bool | None = None,
                 script=None) -> dict:
    """Run the full pipeline. If `script` (a VideoScript) is provided, the LLM
    step is skipped entirely — used by manual-script mode (no Anthropic key)."""
    if do_upload is None:
        do_upload = cfg.get("upload", "enabled", default=False)

    job_dir = _dated_dir(cfg)
    print(f"\n=== Topic: {topic}\n    Output: {job_dir}")

    # 1. Script -------------------------------------------------------------
    if script is None:
        print("[1/5] Generating Gujarati script (Claude)...")
        script = generate_script(topic, cfg)
    else:
        print("[1/5] Using your manual script (no Anthropic API).")
    (job_dir / "script.json").write_text(script.to_json(), encoding="utf-8")
    print(f"      Title: {script.title}")

    # 2. Voiceover + subtitles ---------------------------------------------
    print("[2/5] Synthesizing voiceover (ElevenLabs)...")
    voice = synthesize(script.narration, job_dir, cfg)
    print(f"      Duration: {voice.duration_sec:.1f}s")

    # 3. Visuals ------------------------------------------------------------
    # One scene per spoken BEAT: the visual cut lands exactly on each beat, so
    # voice and edit stay synced (from the voiceover manifest). Falls back to a
    # paced count if per-beat timing isn't available.
    scene_durations = voice.scene_durations or None
    if scene_durations:
        n_scenes = len(scene_durations)
        # Match each scene's image to that beat's actual words (Gujarati->query).
        from .keywords import beats_to_queries
        theme = cfg.get("niche", "visual_theme", default="cinematic indian village")
        scene_queries = beats_to_queries(voice.beats, theme) or script.scenes
        print(f"[3/5] Gathering {n_scenes} beat-matched visuals (1 per spoken beat)...")
    else:
        n_scenes = scene_count_for_duration(
            voice.duration_sec or cfg.get("channel", "target_duration_sec", default=90), cfg
        )
        scene_queries = script.scenes
        print(f"[3/5] Gathering {n_scenes} distinct visuals...")
    assets = gather_scene_assets(scene_queries, job_dir / "images", cfg, count=n_scenes)
    kinds = ", ".join(a.kind[0] for a in assets)  # e.g. "i,v,i,v,..."
    print(f"      {len(assets)} scenes [{kinds}]")

    # 4. Assemble -----------------------------------------------------------
    print("[4/5] Assembling video (ffmpeg: motion, SFX, music, captions)...")
    out_path = job_dir / "final.mp4"
    build_video(
        images=assets,
        scene_durations=scene_durations,
        audio_path=voice.audio_path,
        srt_path=voice.srt_path,
        duration_sec=voice.duration_sec or cfg.get("channel", "target_duration_sec", default=90),
        out_path=out_path,
        cfg=cfg,
    )
    print(f"      Wrote {out_path}")

    # Write a copy-paste-ready title / description / hashtags file next to the
    # video, so everything for uploading lives in the dated folder.
    _write_upload_details(job_dir, script, cfg)

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


def _hashtags(tags: list[str]) -> list[str]:
    """Turn tags into #hashtags and add standard Shorts/Reels tags."""
    out: list[str] = []
    seen: set[str] = set()
    standard = ["shorts", "reels", "ગુજરાતી", "gujarati", "motivation",
                "moralstory", "બોધકથા", "viral"]
    for t in list(tags) + standard:
        tag = "#" + re.sub(r"\s+", "", t.strip().lstrip("#"))
        key = tag.lower()
        if len(tag) > 1 and key not in seen:
            seen.add(key)
            out.append(tag)
    return out[:20]  # YouTube ignores more than ~15; keep it tidy


def _write_upload_details(job_dir: Path, script, cfg: Config) -> None:
    """Write a copy-paste-ready title/description/hashtags file in the folder."""
    tags = _hashtags(getattr(script, "tags", []) or [])
    hashtag_line = " ".join(tags)
    footer = cfg.get("upload", "description_footer", default="").strip()
    # A clean YouTube description: title, CTA, then hashtags.
    desc_parts = [script.title.strip()]
    if footer:
        desc_parts.append(footer)
    desc_parts.append(hashtag_line)
    description = "\n\n".join(p for p in desc_parts if p)

    content = (
        "================ YOUTUBE / SHORTS UPLOAD DETAILS ================\n\n"
        "TITLE (copy this):\n"
        f"{script.title.strip()}\n\n"
        "DESCRIPTION (copy this):\n"
        f"{description}\n\n"
        "HASHTAGS (already in description; copy separately if needed):\n"
        f"{hashtag_line}\n\n"
        "================================================================\n"
    )
    (job_dir / "upload_details.txt").write_text(content, encoding="utf-8")
    # Also machine-readable, for any future tooling.
    (job_dir / "upload_details.json").write_text(
        json.dumps({"title": script.title, "description": description,
                    "hashtags": tags}, ensure_ascii=False, indent=2),
        encoding="utf-8")
