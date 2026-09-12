"""Assemble a professional-looking MP4 with ffmpeg.

Video : per-scene clips (Ken-Burns motion on photos, trimmed/scaled video
        clips) concatenated with punchy hard cuts, gentle fade in/out overall.
Audio : narration (loudness-normalized, optional pitch shift) + transition
        whoosh SFX at every cut + optional sidechain-ducked background music.
Text  : Gujarati captions burned in.

Every optional audio stage is best-effort: if one fails, the pipeline falls
back to the previous good audio so a video always renders.

ffmpeg must be installed and on PATH.
"""
from __future__ import annotations

import math
import random
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .visuals import SceneAsset, is_color_marker

FPS = 30


def _run(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed:\n  cmd: " + " ".join(str(a) for a in args)
            + f"\n  stderr:\n{proc.stderr[-1500:]}"
        )


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install it: winget install Gyan.FFmpeg "
            "(Windows) / brew install ffmpeg (macOS) / apt-get install ffmpeg."
        )


def build_video(
    images: list,           # list[SceneAsset] (or Paths for backward compat)
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

    assets = _as_assets(images)
    n = max(1, len(assets))
    # Distribute the real narration duration evenly across scenes.
    total = max(duration_sec, 3.0)
    per = total / n
    durations = [per] * n
    durations[-1] = total - per * (n - 1)  # last absorbs rounding

    # 1) Build normalized per-scene clips (video only) --------------------
    scene_files: list[Path] = []
    for i, (asset, dur) in enumerate(zip(assets, durations)):
        scene = work / f"scene_{i:02d}.mp4"
        first, last = (i == 0), (i == n - 1)
        _build_scene(asset, scene, dur, w, h, first, last, cfg)
        scene_files.append(scene)

    silent = work / "video_silent.mp4"
    _concat(scene_files, silent, work)

    # 2) Build the audio bed ---------------------------------------------
    cut_times = _cumulative(durations)[:-1]  # transition points (skip 0 and end)
    final_audio = _build_audio(audio_path, cut_times, work, cfg)

    # 3) Mux video + audio ------------------------------------------------
    muxed = work / "muxed.mp4"
    _run([
        "ffmpeg", "-y", "-i", str(silent), "-i", str(final_audio),
        "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-shortest", str(muxed),
    ])

    # 4) Burn subtitles ---------------------------------------------------
    if srt_path and srt_path.exists() and cfg.get("subtitles", "enabled", default=True):
        _burn_subtitles(muxed, srt_path, out_path, cfg)
    else:
        shutil.move(str(muxed), str(out_path))

    shutil.rmtree(work, ignore_errors=True)
    return out_path


# --------------------------------------------------------------------------
# Scene clips
# --------------------------------------------------------------------------
def _build_scene(asset: SceneAsset, dest: Path, dur: float, w: int, h: int,
                 first: bool, last: bool, cfg: Config) -> None:
    fade = float(cfg.get("visuals", "transition_fade_sec", default=0.5))
    tail = _fade_filter(dur, fade, first, last)

    color = is_color_marker(asset.path) if asset.kind == "image" else None
    if color:
        vf = f"format=yuv420p{(',' + tail) if tail else ''}"
        _run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", f"color=c=0x{color}:s={w}x{h}:d={dur:.2f}:r={FPS}",
            "-vf", vf, "-t", f"{dur:.2f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dest),
        ])
        return

    if asset.kind == "video":
        # Scale/crop to fill, loop if shorter than the scene, trim to dur.
        chain = (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},setsar=1,fps={FPS}"
        )
        if tail:
            chain += "," + tail
        _run([
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(asset.path),
            "-t", f"{dur:.2f}", "-an", "-vf", chain,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), str(dest),
        ])
        return

    # Image -> Ken Burns (randomized zoom-in / zoom-out).
    frames = int(math.ceil(dur * FPS))
    if cfg.get("visuals", "ken_burns", default=True):
        chain = _ken_burns(w, h, frames)
    else:
        chain = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    if tail:
        chain += "," + tail
    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(asset.path),
        "-t", f"{dur:.2f}", "-vf", chain,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), str(dest),
    ])


def _ken_burns(w: int, h: int, frames: int) -> str:
    zoom_in = random.random() < 0.5
    if zoom_in:
        z = "min(zoom+0.0007,1.18)"
    else:
        z = "if(eq(on,0),1.18,max(zoom-0.0007,1.0))"
    # Slight random pan target.
    xs = random.choice(["iw/2-(iw/zoom/2)", "0", "iw-(iw/zoom)"])
    ys = random.choice(["ih/2-(ih/zoom/2)", "0", "ih-(ih/zoom)"])
    return (
        f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
        f"crop={w*2}:{h*2},"
        f"zoompan=z='{z}':d={frames}:x='{xs}':y='{ys}':s={w}x{h}:fps={FPS}"
    )


def _fade_filter(dur: float, fade: float, first: bool, last: bool) -> str:
    """Fade in only on the first scene and fade out only on the last, so
    internal cuts stay punchy (the whoosh SFX marks those)."""
    parts = []
    if first:
        parts.append(f"fade=t=in:st=0:d={min(fade, dur/2):.2f}")
    if last:
        st = max(0.0, dur - fade)
        parts.append(f"fade=t=out:st={st:.2f}:d={min(fade, dur/2):.2f}")
    return ",".join(parts)


def _concat(scenes: list[Path], dest: Path, work: Path) -> None:
    listfile = work / "concat.txt"
    listfile.write_text(
        "\n".join(f"file '{s.resolve().as_posix()}'" for s in scenes), encoding="utf-8"
    )
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
        "-c", "copy", str(dest),
    ])


# --------------------------------------------------------------------------
# Audio bed: narration -> +SFX -> +ducked music
# --------------------------------------------------------------------------
def _build_audio(narration: Path, cut_times: list[float], work: Path, cfg: Config) -> Path:
    audio = _process_narration(narration, work, cfg)
    audio = _add_sfx(audio, cut_times, work, cfg)
    audio = _add_music(audio, work, cfg)
    return audio


def _process_narration(narration: Path, work: Path, cfg: Config) -> Path:
    """Loudness-normalize and optionally pitch-shift (timing preserved)."""
    filters = []
    pitch = float(cfg.get("voiceover", "pitch", default=1.0))
    if abs(pitch - 1.0) > 1e-3:
        # Shift pitch, then restore tempo so subtitles stay in sync.
        filters.append(f"asetrate=44100*{pitch:.4f},aresample=44100,atempo={1/pitch:.4f}")
    if cfg.get("voiceover", "loudnorm", default=True):
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    out = work / "narration_proc.wav"
    if not filters:
        _run(["ffmpeg", "-y", "-i", str(narration), "-ar", "44100", "-ac", "2", str(out)])
        return out
    try:
        _run([
            "ffmpeg", "-y", "-i", str(narration),
            "-af", ",".join(filters), "-ar", "44100", "-ac", "2", str(out),
        ])
        return out
    except Exception as exc:
        print(f"  ! narration processing failed ({exc}); using raw audio.")
        _run(["ffmpeg", "-y", "-i", str(narration), "-ar", "44100", "-ac", "2", str(out)])
        return out


def _add_sfx(audio: Path, cut_times: list[float], work: Path, cfg: Config) -> Path:
    if not cfg.get("sfx", "enabled", default=True) or not cut_times:
        return audio
    try:
        whoosh = _make_whoosh(work, cfg)
        vol = float(cfg.get("sfx", "volume", default=0.28))
        k = len(cut_times)
        split = f"[1:a]volume={vol},asplit={k}" + "".join(f"[s{i}]" for i in range(k)) + ";"
        delays = "".join(
            f"[s{i}]adelay={int(t*1000)}|{int(t*1000)}[d{i}];" for i, t in enumerate(cut_times)
        )
        mix_inputs = "[0:a]" + "".join(f"[d{i}]" for i in range(k))
        graph = split + delays + f"{mix_inputs}amix=inputs={k+1}:normalize=0[a]"
        out = work / "narration_sfx.wav"
        _run([
            "ffmpeg", "-y", "-i", str(audio), "-i", str(whoosh),
            "-filter_complex", graph, "-map", "[a]", str(out),
        ])
        return out
    except Exception as exc:
        print(f"  ! SFX stage skipped ({exc}).")
        return audio


def _make_whoosh(work: Path, cfg: Config) -> Path:
    """Generate a soft transition whoosh with ffmpeg (no asset file needed)."""
    out = work / "whoosh.wav"
    _run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "anoisesrc=d=0.35:c=pink:a=0.5",
        "-af", "highpass=f=250,lowpass=f=5000,"
               "afade=t=in:st=0:d=0.05,afade=t=out:st=0.12:d=0.23",
        str(out),
    ])
    return out


def _add_music(audio: Path, work: Path, cfg: Config) -> Path:
    if not cfg.get("music", "enabled", default=False):
        return audio
    music_file = cfg.path(cfg.get("music", "file", default=""))
    if not music_file.exists():
        print(f"  ! music enabled but file not found: {music_file}")
        return audio
    try:
        vol = float(cfg.get("music", "volume", default=0.12))
        # Sidechain-duck the music under the voice, then mix.
        graph = (
            f"[1:a]volume={vol}[m];"
            f"[m][0:a]sidechaincompress=threshold=0.03:ratio=8:attack=5:release=300[mduck];"
            f"[0:a][mduck]amix=inputs=2:normalize=0[a]"
        )
        out = work / "narration_music.wav"
        _run([
            "ffmpeg", "-y", "-i", str(audio),
            "-stream_loop", "-1", "-i", str(music_file),
            "-filter_complex", graph, "-map", "[a]", "-shortest", str(out),
        ])
        return out
    except Exception as exc:
        print(f"  ! music stage skipped ({exc}).")
        return audio


# --------------------------------------------------------------------------
# Subtitles
# --------------------------------------------------------------------------
def _burn_subtitles(video: Path, srt: Path, dest: Path, cfg: Config) -> None:
    fonts_dir = cfg.path("assets", "fonts")
    size = cfg.get("subtitles", "font_size", default=24)
    if cfg.is_short:
        size = int(size * 1.5)
    style = (
        f"FontName=Noto Sans Gujarati,"
        f"FontSize={size},Bold=1,"
        f"PrimaryColour={cfg.get('subtitles', 'primary_color', default='&H00FFFFFF')},"
        f"OutlineColour={cfg.get('subtitles', 'outline_color', default='&H00000000')},"
        f"BorderStyle=1,Outline={cfg.get('subtitles', 'outline', default=3)},Shadow=1,"
        f"Alignment=2,MarginV=70"
    )
    srt_arg = str(srt).replace("\\", "/").replace(":", r"\:")
    vf = f"subtitles='{srt_arg}':fontsdir='{fonts_dir}':force_style='{style}'"
    _run([
        "ffmpeg", "-y", "-i", str(video), "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", str(dest),
    ])


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _as_assets(images: list) -> list[SceneAsset]:
    out = []
    for item in images:
        if isinstance(item, SceneAsset):
            out.append(item)
        else:  # a bare Path -> treat by extension
            p = Path(item)
            kind = "video" if p.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv"} else "image"
            out.append(SceneAsset(p, kind))
    return out


def _cumulative(durations: list[float]) -> list[float]:
    times, acc = [], 0.0
    for d in durations:
        acc += d
        times.append(acc)
    return times
