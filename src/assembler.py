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
from collections import Counter
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
    scene_durations: list[float] | None = None,
) -> Path:
    ensure_ffmpeg()
    w, h = cfg.resolution
    work = out_path.parent / "_work"
    work.mkdir(parents=True, exist_ok=True)

    assets = _as_assets(images)
    n = max(1, len(assets))
    if scene_durations and len(scene_durations) == n:
        # Beat-aligned durations from the voiceover manifest: each scene cut
        # lands exactly on a spoken beat, so voice and edit stay in sync.
        durations = list(scene_durations)
    else:
        # Fallback: distribute the total duration evenly across scenes.
        total = max(duration_sec, 3.0)
        per = total / n
        durations = [per] * n
        durations[-1] = total - per * (n - 1)  # last absorbs rounding

    # Non-repeating motion effect per scene (never the same as the previous).
    effects = _effect_sequence(n)

    # 1) Build normalized per-scene clips (video only) --------------------
    scene_files: list[Path] = []
    for i, (asset, dur) in enumerate(zip(assets, durations)):
        scene = work / f"scene_{i:02d}.mp4"
        first, last = (i == 0), (i == n - 1)
        _build_scene(asset, scene, dur, w, h, first, last, effects[i], cfg)
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
        try:
            _burn_subtitles(muxed, srt_path, out_path, cfg)
        except Exception as exc:
            # Never throw away a good render (and the paid voiceover) over a
            # caption error — keep the video, just without burned-in captions.
            print(f"  ! Caption burn failed ({exc}). Saving video WITHOUT captions.")
            shutil.move(str(muxed), str(out_path))
    else:
        shutil.move(str(muxed), str(out_path))

    shutil.rmtree(work, ignore_errors=True)
    return out_path


# --------------------------------------------------------------------------
# Scene clips
# --------------------------------------------------------------------------
# A varied library of motion effects (not just zoom in/out).
MOTION_EFFECTS = [
    "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down",
    "zoom_in_tl", "zoom_in_br", "zoom_out_tr", "zoom_out_bl",
]


def _effect_sequence(n: int) -> list[str]:
    """A motion effect per scene, never repeating the previous one."""
    seq: list[str] = []
    prev = None
    for _ in range(n):
        choices = [e for e in MOTION_EFFECTS if e != prev]
        pick = random.choice(choices)
        seq.append(pick)
        prev = pick
    return seq


def _build_scene(asset: SceneAsset, dest: Path, dur: float, w: int, h: int,
                 first: bool, last: bool, effect: str, cfg: Config) -> None:
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
        # Video already moves; scale/crop to fill, loop if short, trim to dur.
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

    # Image -> apply the chosen motion effect.
    frames = int(math.ceil(dur * FPS))
    if cfg.get("visuals", "motion", default=True):
        chain = _motion_chain(effect, w, h, frames)
    else:
        chain = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    if tail:
        chain += "," + tail
    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(asset.path),
        "-t", f"{dur:.2f}", "-vf", chain,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), str(dest),
    ])


def _motion_chain(effect: str, w: int, h: int, frames: int) -> str:
    """Build a zoompan filter for a named motion effect. The source is scaled
    up 2x first so the pan/zoom stays sharp."""
    prefix = (
        f"scale={w*2}:{h*2}:force_original_aspect_ratio=increase,"
        f"crop={w*2}:{h*2},"
    )
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    step, zmax = 0.0009, 1.20
    zin = f"min(zoom+{step},{zmax})"
    zout = f"if(eq(on,0),{zmax},max(zoom-{step},1.0))"
    zc = "1.12"  # constant zoom for pans
    px_r = f"(iw-iw/zoom)*(on/{frames})"   # left -> right
    px_l = f"(iw-iw/zoom)*(1-on/{frames})" # right -> left
    py_d = f"(ih-ih/zoom)*(on/{frames})"   # top -> bottom
    py_u = f"(ih-ih/zoom)*(1-on/{frames})" # bottom -> top

    table = {
        "zoom_in":    (zin, cx, cy),
        "zoom_out":   (zout, cx, cy),
        "zoom_in_tl": (zin, "0", "0"),
        "zoom_in_br": (zin, "iw-iw/zoom", "ih-ih/zoom"),
        "zoom_out_tr":(zout, "iw-iw/zoom", "0"),
        "zoom_out_bl":(zout, "0", "ih-ih/zoom"),
        "pan_left":   (zc, px_l, cy),
        "pan_right":  (zc, px_r, cy),
        "pan_up":     (zc, cx, py_u),
        "pan_down":   (zc, cx, py_d),
    }
    z, x, y = table.get(effect, (zin, cx, cy))
    return (
        f"{prefix}zoompan=z='{z}':d={frames}:x='{x}':y='{y}':s={w}x{h}:fps={FPS}"
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
        library = _make_sfx_library(work)
        variety = cfg.get("sfx", "variety", default=True)
        k = len(cut_times)
        # Choose a sound per cut (non-repeating). Whoosh-only if variety off.
        if variety:
            choices = _sfx_sequence(k, len(library))
        else:
            choices = [0] * k

        vol = float(cfg.get("sfx", "volume", default=0.30))
        used_libs = sorted(set(choices))
        # ffmpeg inputs: 0 = narration, then one per used library sound.
        inputs = ["-i", str(audio)]
        lib_input = {}
        for pos, m in enumerate(used_libs):
            inputs += ["-i", str(library[m])]
            lib_input[m] = pos + 1

        usage = Counter(choices)
        graph = ""
        # Split each used sound into as many copies as it's used, at target vol.
        for m in used_libs:
            n = usage[m]
            base = f"[{lib_input[m]}:a]volume={vol}"
            if n == 1:
                graph += f"{base}[m{m}_0];"
            else:
                graph += base + f",asplit={n}" + "".join(f"[m{m}_{r}]" for r in range(n)) + ";"
        # Delay each copy to its cut time.
        counters: dict[int, int] = {m: 0 for m in used_libs}
        delayed = []
        for j, t in enumerate(cut_times):
            m = choices[j]
            r = counters[m]; counters[m] += 1
            ms = int(t * 1000)
            graph += f"[m{m}_{r}]adelay={ms}|{ms}[c{j}];"
            delayed.append(f"[c{j}]")
        graph += "[0:a]" + "".join(delayed) + f"amix=inputs={len(delayed)+1}:normalize=0[a]"

        out = work / "narration_sfx.wav"
        _run(["ffmpeg", "-y", *inputs, "-filter_complex", graph, "-map", "[a]", str(out)])
        return out
    except Exception as exc:
        print(f"  ! SFX stage skipped ({exc}).")
        return audio


def _sfx_sequence(k: int, m: int) -> list[int]:
    """Pick a sound index per cut, never the same as the previous cut."""
    seq: list[int] = []
    prev = None
    for _ in range(k):
        opts = [i for i in range(m) if i != prev] or list(range(m))
        pick = random.choice(opts)
        seq.append(pick)
        prev = pick
    return seq


def _make_sfx_library(work: Path) -> list[Path]:
    """Synthesize a variety of transition sounds with ffmpeg (no asset files).

    Order matters: index 0 is the whoosh (used when variety is off)."""
    sr = 44100
    specs = [
        # (name, lavfi source, audio filter)
        ("whoosh", f"anoisesrc=d=0.35:c=pink:a=0.6:r={sr}",
         "highpass=f=250,lowpass=f=5000,afade=t=in:st=0:d=0.05,afade=t=out:st=0.12:d=0.23"),
        ("swoosh", f"anoisesrc=d=0.45:c=white:a=0.5:r={sr}",
         "highpass=f=600,lowpass=f=9000,afade=t=in:st=0:d=0.08,afade=t=out:st=0.15:d=0.3"),
        ("click", f"sine=frequency=1400:duration=0.05:sample_rate={sr}",
         "afade=t=out:st=0.01:d=0.04,volume=0.9"),
        ("pop", f"sine=frequency=520:duration=0.08:sample_rate={sr}",
         "afade=t=out:st=0.02:d=0.06,volume=0.9"),
        ("ding", f"sine=frequency=1568:duration=0.30:sample_rate={sr}",
         "afade=t=out:st=0.05:d=0.25,volume=0.7"),
        ("hit", f"sine=frequency=120:duration=0.18:sample_rate={sr}",
         "afade=t=out:st=0.03:d=0.15,volume=1.0"),
        ("riser", f"anoisesrc=d=0.5:c=brown:a=0.5:r={sr}",
         "highpass=f=200,lowpass=f=6000,afade=t=in:st=0:d=0.42,afade=t=out:st=0.44:d=0.06"),
    ]
    paths: list[Path] = []
    for name, src, af in specs:
        out = work / f"sfx_{name}.wav"
        _run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", src,
            "-af", af, "-ac", "1", "-ar", str(sr), str(out),
        ])
        paths.append(out)
    return paths


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
def _escape_filter_path(p: Path) -> str:
    """Make a filesystem path safe for an ffmpeg filter argument (Windows-safe):
    forward slashes, and the drive-letter colon escaped."""
    return str(p).replace("\\", "/").replace(":", r"\:")


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
    # ffmpeg's filter parser treats ':' and '\' specially, so paths (with a
    # Windows drive letter like D:\...) must use forward slashes and an
    # escaped colon. Applies to BOTH the srt file and the fonts dir.
    srt_arg = _escape_filter_path(srt)
    fonts_arg = _escape_filter_path(fonts_dir)
    vf = f"subtitles='{srt_arg}':fontsdir='{fonts_arg}':force_style='{style}'"
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
