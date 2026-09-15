"""Gujarati voiceover — implements the per-beat eleven_v3 recipe.

Pipeline (per the tested spec):
  1. Split the script into short BEATS (sentence/clause each).
  2. Generate each beat as its OWN eleven_v3 TTS call (natural Gujarati accent;
     avoids the drift/artifacts long single-call Gujarati TTS produces).
  3. Trim ElevenLabs' silence padding from each beat (uneven otherwise).
  4. Concatenate beats with a fixed inter-beat gap.
  5. Emit a timing MANIFEST — each beat's [start, end] on the final timeline —
     the single source of truth for scene cuts, captions and SFX.

v3 note: voice_settings are discrete (stability snaps to 0.0/0.5/1.0), and
`style`/`speed` are ignored by v3 (still sent for older models).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .config import Config

_TTS = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_VOICES_API = "https://api.elevenlabs.io/v1/voices"


@dataclass
class VoiceResult:
    audio_path: Path
    srt_path: Path | None
    duration_sec: float
    beats: list[dict] = field(default_factory=list)   # {index,text,start,end}
    scene_durations: list[float] = field(default_factory=list)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def synthesize(text: str, out_dir: Path, cfg: Config, make_srt: bool = True) -> VoiceResult:
    if not cfg.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set (see .env.example)")
    _ensure_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)

    per_beat = cfg.get("voiceover", "per_beat", default=True)
    beats_text = _split_beats(
        text,
        int(cfg.get("voiceover", "beat_min_chars", default=15)),
        int(cfg.get("voiceover", "beat_max_chars", default=240)),
    ) if per_beat else [text.strip()]

    voice_id = cfg.elevenlabs_voice_id or cfg.get(
        "voiceover", "default_voice_id", default="21m00Tcm4TlvDq8ikWAM"
    )
    gap = float(cfg.get("voiceover", "beat_gap_sec", default=0.32))

    beats_dir = out_dir / "beats"
    beats_dir.mkdir(exist_ok=True)
    gap_path = out_dir / "gap.mp3"
    _make_gap(gap_path, gap)

    clean_paths: list[Path] = []
    beat_meta: list[dict] = []
    t = 0.0
    for i, btext in enumerate(beats_text):
        raw = beats_dir / f"beat_{i:03d}_raw.mp3"
        clean = beats_dir / f"beat_{i:03d}.mp3"
        raw.write_bytes(_tts_beat(btext, voice_id, cfg))
        _trim_silence(raw, clean)
        dur = _duration(clean)
        start = t
        t += dur
        end = t
        is_last = i == len(beats_text) - 1
        scene_dur = dur + (0.0 if is_last else gap)
        if not is_last:
            t += gap
        clean_paths.append(clean)
        beat_meta.append({"index": i, "text": btext, "start": round(start, 3),
                          "end": round(end, 3), "scene_dur": round(scene_dur, 3)})

    audio_path = out_dir / "narration.mp3"
    _concat_with_gaps(clean_paths, gap_path, audio_path, out_dir)
    total = round(t, 3)

    # Manifest — the single source of truth for downstream timing.
    (out_dir / "manifest.json").write_text(
        json.dumps({"total_sec": total, "gap_sec": gap, "beats": beat_meta},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    srt_path: Path | None = None
    if make_srt:
        # Uniform, well-fitting bottom captions (the layout that worked before).
        srt_path = out_dir / "narration.srt"
        srt_path.write_text(_manifest_to_srt(beat_meta), encoding="utf-8")

    return VoiceResult(
        audio_path=audio_path, srt_path=srt_path, duration_sec=total,
        beats=beat_meta, scene_durations=[b["scene_dur"] for b in beat_meta],
    )


def list_voices(cfg: Config, match: str | None = None) -> list[dict]:
    if not cfg.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set (see .env.example)")
    resp = requests.get(_VOICES_API, headers={"xi-api-key": cfg.elevenlabs_api_key}, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs error {resp.status_code}: {resp.text[:400]}")
    voices = [
        {"voice_id": v["voice_id"], "name": v.get("name", ""), "category": v.get("category", "")}
        for v in resp.json().get("voices", [])
    ]
    if match:
        needle = match.lower()
        voices = [v for v in voices if needle in v["name"].lower()]
    return voices


# --------------------------------------------------------------------------
# TTS + voice settings
# --------------------------------------------------------------------------
def _tts_beat(text: str, voice_id: str, cfg: Config) -> bytes:
    model = cfg.get("voiceover", "model_id", default="eleven_v3")
    fmt = cfg.get("voiceover", "output_format", default="mp3_44100_128")
    url = _TTS.format(voice_id=voice_id)
    body = {"text": text, "model_id": model, "voice_settings": _voice_settings(cfg)}
    resp = requests.post(
        url, params={"output_format": fmt},
        headers={"xi-api-key": cfg.elevenlabs_api_key, "Content-Type": "application/json"},
        json=body, timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs error {resp.status_code}: {resp.text[:400]}")
    return resp.content


def _voice_settings(cfg: Config) -> dict:
    """v3 uses DISCRETE stability (0.0/0.5/1.0) and ignores style/speed.
    Older models (eleven_multilingual_v2) accept continuous stability + style + speed."""
    model = str(cfg.get("voiceover", "model_id", default="eleven_v3"))
    stability = float(cfg.get("voiceover", "stability", default=0.5))
    similarity = float(cfg.get("voiceover", "similarity_boost", default=0.8))
    boost = bool(cfg.get("voiceover", "use_speaker_boost", default=True))

    if model.startswith("eleven_v3"):
        # Snap stability to the nearest allowed discrete value.
        snapped = 0.0 if stability < 0.25 else (0.5 if stability < 0.75 else 1.0)
        return {"stability": snapped, "similarity_boost": similarity,
                "use_speaker_boost": boost}
    return {
        "stability": stability,
        "similarity_boost": similarity,
        "style": float(cfg.get("voiceover", "style", default=0.0)),
        "speed": float(cfg.get("voiceover", "speed", default=1.0)),
        "use_speaker_boost": boost,
    }


# --------------------------------------------------------------------------
# Beat splitting
# --------------------------------------------------------------------------
_SENT_SPLIT = re.compile(r"(?<=[।\.\!\?\n])")


def _split_beats(text: str, min_chars: int, max_chars: int) -> list[str]:
    """Split into sentence/clause beats; merge tiny fragments up to min_chars.
    Never force-splits mid-sentence (a long sentence stays one beat)."""
    raw = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    beats: list[str] = []
    buf = ""
    for part in raw:
        buf = (buf + " " + part).strip() if buf else part
        if len(buf) >= min_chars:
            beats.append(buf)
            buf = ""
    if buf:
        if beats and len(buf) < min_chars:
            beats[-1] = (beats[-1] + " " + buf).strip()
        else:
            beats.append(buf)
    return beats or [text.strip()]


# --------------------------------------------------------------------------
# ffmpeg helpers
# --------------------------------------------------------------------------
def _ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH (needed for voiceover assembly).")


def _run(args: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n  " + " ".join(args) + f"\n{proc.stderr[-800:]}")
    return proc


def _trim_silence(src: Path, dest: Path) -> None:
    """Trim ElevenLabs' leading/trailing silence padding (end padded more)."""
    af = (
        "silenceremove=start_periods=1:start_silence=0.06:start_threshold=-45dB:detection=peak,"
        "areverse,"
        "silenceremove=start_periods=1:start_silence=0.10:start_threshold=-45dB:detection=peak,"
        "areverse"
    )
    try:
        _run(["ffmpeg", "-y", "-i", str(src), "-af", af,
              "-c:a", "libmp3lame", "-b:a", "192k", str(dest)])
    except Exception:
        shutil.copyfile(src, dest)  # never lose a beat over trimming


def _make_gap(path: Path, seconds: float) -> None:
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
          "-t", f"{seconds:.3f}", "-q:a", "9", str(path)])


def _concat_with_gaps(beats: list[Path], gap: Path, dest: Path, work: Path) -> None:
    listfile = work / "concat_vo.txt"
    lines = []
    for i, b in enumerate(beats):
        lines.append(f"file '{b.resolve().as_posix()}'")
        if i != len(beats) - 1:
            lines.append(f"file '{gap.resolve().as_posix()}'")
    listfile.write_text("\n".join(lines), encoding="utf-8")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
          "-c:a", "libmp3lame", "-b:a", "192k", str(dest)])


def _duration(path: Path) -> float:
    """Media duration in seconds (ffprobe if present, else parse ffmpeg)."""
    if shutil.which("ffprobe"):
        p = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
            capture_output=True, text=True)
        try:
            return float(p.stdout.strip())
        except ValueError:
            pass
    p = subprocess.run(["ffmpeg", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", p.stderr)
    if m:
        h, mm, ss = m.groups()
        return int(h) * 3600 + int(mm) * 60 + float(ss)
    return 0.0


# --------------------------------------------------------------------------
# Subtitles from the manifest (beat-level, perfectly synced)
# --------------------------------------------------------------------------
def _manifest_to_srt(beats: list[dict]) -> str:
    lines = []
    for i, b in enumerate(beats, 1):
        lines.append(str(i))
        lines.append(f"{_ts(b['start'])} --> {_ts(max(b['end'], b['start'] + 0.4))}")
        lines.append(b["text"])
        lines.append("")
    return "\n".join(lines)


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_ts(seconds: float) -> str:
    cs = int(round(seconds * 100))  # centiseconds
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _manifest_to_ass(beats: list[dict], w: int, h: int, cfg: Config) -> str:
    """Build an ASS subtitle file. Beat 0 (the hook) shows BIG and CENTERED as a
    scroll-stopping on-screen hook; the rest show as normal bottom captions.
    Sizes are in pixels because PlayResX/Y match the real video size."""
    cap = int(round(h * float(cfg.get("subtitles", "caption_scale", default=0.030))))
    hook = int(round(h * float(cfg.get("subtitles", "hook_scale", default=0.055))))
    marginv = int(round(h * 0.12))
    side = int(round(w * 0.08))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Noto Sans Gujarati,{cap},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,3,1,2,{side},{side},{marginv},1
Style: Hook,Noto Sans Gujarati,{hook},&H0000FFFF,&H0000FFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,1,5,2,5,{side},{side},{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for i, b in enumerate(beats):
        style = "Hook" if i == 0 else "Cap"
        text = b["text"].replace("\n", r"\N")
        start = _ass_ts(b["start"])
        end = _ass_ts(max(b["end"], b["start"] + 0.5))
        lines.append(f"Dialogue: 0,{start},{end},{style},,0,0,0,,{text}")
    return "\n".join(lines)
