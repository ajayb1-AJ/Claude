"""Assemble the final MP4 with ffmpeg.

Pipeline: per-scene Ken Burns clips -> concat -> mux narration (+ music) ->
burn Gujarati subtitles.

ffmpeg must be installed and on PATH.
"""
from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .visuals import is_color_marker

FPS = 30


def _run(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed:\n  cmd: "
            + " ".join(args)
            + f"\n  stderr:\n{proc.stderr[-1500:]}"
        )


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install it: `brew install ffmpeg` (macOS) "
            "or `sudo apt-get install ffmpeg` (Ubuntu)."
        )


def build_video(
    images: list[Path],
    audio_path: Path,
    srt_path: Path | None,
    duration_sec: float,
    out_path: Path,
    cfg: Config,
) -> Path:
    ensure_ffmpeg()
    w, h = cfg.resolution
    work = out_path.parent / "_work"
    work.mkdir(parents=True, exist_ok=True)

    n = max(1, len(images))
    per_scene = max(2.5, duration_sec / n) + 0.6  # buffer; -shortest trims to audio

    scene_files: list[Path] = []
    for i, img in enumerate(images):
        scene = work / f"scene_{i:02d}.mp4"
        _build_scene(img, scene, per_scene, w, h, cfg)
        scene_files.append(scene)

    silent_video = work / "video_silent.mp4"
    _concat(scene_files, silent_video, work)

    muxed = work / "video_muxed.mp4"
    _add_audio(silent_video, audio_path, muxed, cfg)

    if srt_path and srt_path.exists() and cfg.get("subtitles", "enabled", default=True):
        _burn_subtitles(muxed, srt_path, out_path, cfg)
    else:
        shutil.move(str(muxed), str(out_path))

    shutil.rmtree(work, ignore_errors=True)
    return out_path


def _build_scene(img: Path, dest: Path, dur: float, w: int, h: int, cfg: Config) -> None:
    frames = int(math.ceil(dur * FPS))
    color = is_color_marker(img)
    if color:
        _run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"color=c=0x{color}:s={w}x{h}:d={dur:.2f}:r={FPS}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", f"{dur:.2f}",
            str(dest),
        ])
        return

    ken_burns = cfg.get("visuals", "ken_burns", default=True)
    if ken_burns:
        # Scale up so the slow zoom stays sharp, then zoompan.
        vf = (
            f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
            f"crop={w*2}:{h*2},"
            f"zoompan=z='min(zoom+0.0007,1.18)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS}"
        )
    else:
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}"
        )
    _run([
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(img),
        "-t", f"{dur:.2f}",
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
        str(dest),
    ])


def _concat(scenes: list[Path], dest: Path, work: Path) -> None:
    listfile = work / "concat.txt"
    listfile.write_text(
        "\n".join(f"file '{s.resolve()}'" for s in scenes), encoding="utf-8"
    )
    _run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c", "copy", str(dest),
    ])


def _add_audio(video: Path, narration: Path, dest: Path, cfg: Config) -> None:
    music_enabled = cfg.get("music", "enabled", default=False)
    music_file = cfg.path(cfg.get("music", "file", default=""))
    if music_enabled and music_file.exists():
        vol = cfg.get("music", "volume", default=0.08)
        _run([
            "ffmpeg", "-y",
            "-i", str(video),
            "-i", str(narration),
            "-stream_loop", "-1", "-i", str(music_file),
            "-filter_complex",
            f"[2:a]volume={vol}[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(dest),
        ])
    else:
        _run([
            "ffmpeg", "-y",
            "-i", str(video),
            "-i", str(narration),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(dest),
        ])


def _burn_subtitles(video: Path, srt: Path, dest: Path, cfg: Config) -> None:
    fonts_dir = cfg.path("assets", "fonts")
    size = cfg.get("subtitles", "font_size", default=22)
    if cfg.is_short:
        size = int(size * 1.4)
    style = (
        f"FontName=Noto Sans Gujarati,"
        f"FontSize={size},"
        f"PrimaryColour={cfg.get('subtitles', 'primary_color', default='&H00FFFFFF')},"
        f"OutlineColour={cfg.get('subtitles', 'outline_color', default='&H00000000')},"
        f"Outline={cfg.get('subtitles', 'outline', default=2)},"
        f"Alignment=2,MarginV=60"
    )
    # Escape for the ffmpeg filter argument.
    srt_arg = str(srt).replace("\\", "/").replace(":", r"\:")
    vf = f"subtitles='{srt_arg}':fontsdir='{fonts_dir}':force_style='{style}'"
    _run([
        "ffmpeg", "-y",
        "-i", str(video),
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(dest),
    ])
