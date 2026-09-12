"""ElevenLabs text-to-speech for Gujarati narration.

Uses the /with-timestamps endpoint so we get per-character timings, which we
turn into an SRT subtitle file synced to the audio.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import Config

_API = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"


@dataclass
class VoiceResult:
    audio_path: Path
    srt_path: Path | None
    duration_sec: float


def synthesize(text: str, out_dir: Path, cfg: Config, make_srt: bool = True) -> VoiceResult:
    if not cfg.elevenlabs_api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set (see .env.example)")

    voice_id = cfg.elevenlabs_voice_id or cfg.get(
        "voiceover", "default_voice_id", default="21m00Tcm4TlvDq8ikWAM"
    )
    url = _API.format(voice_id=voice_id)
    body = {
        "text": text,
        "model_id": cfg.get("voiceover", "model_id", default="eleven_multilingual_v2"),
        "voice_settings": {
            "stability": cfg.get("voiceover", "stability", default=0.5),
            "similarity_boost": cfg.get("voiceover", "similarity_boost", default=0.75),
        },
    }
    headers = {"xi-api-key": cfg.elevenlabs_api_key, "Content-Type": "application/json"}

    resp = requests.post(url, json=body, headers=headers, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs error {resp.status_code}: {resp.text[:400]}")
    data = resp.json()

    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir / "narration.mp3"
    audio_path.write_bytes(base64.b64decode(data["audio_base64"]))

    alignment = data.get("alignment") or data.get("normalized_alignment")
    duration = _alignment_duration(alignment)

    srt_path: Path | None = None
    if make_srt and alignment:
        srt_path = out_dir / "narration.srt"
        srt_path.write_text(_alignment_to_srt(alignment), encoding="utf-8")

    return VoiceResult(audio_path=audio_path, srt_path=srt_path, duration_sec=duration)


def _alignment_duration(alignment: dict | None) -> float:
    if not alignment:
        return 0.0
    ends = alignment.get("character_end_times_seconds", [])
    return float(ends[-1]) if ends else 0.0


def _alignment_to_srt(alignment: dict, max_chars: int = 42) -> str:
    """Group characters into readable caption lines, breaking on punctuation
    or length, and emit SRT with the ElevenLabs timings."""
    chars: list[str] = alignment["characters"]
    starts: list[float] = alignment["character_start_times_seconds"]
    ends: list[float] = alignment["character_end_times_seconds"]

    cues: list[tuple[float, float, str]] = []
    buf: list[str] = []
    cue_start: float | None = None

    breakers = set("।.!?\n")  # includes the Gujarati/Devanagari danda
    for ch, st, en in zip(chars, starts, ends):
        if cue_start is None:
            cue_start = st
        buf.append(ch)
        text = "".join(buf).strip()
        if ch in breakers or len(text) >= max_chars:
            if text:
                cues.append((cue_start, en, text))
            buf, cue_start = [], None
    if buf and cue_start is not None:
        text = "".join(buf).strip()
        if text:
            cues.append((cue_start, ends[-1], text))

    lines: list[str] = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{_ts(start)} --> {_ts(max(end, start + 0.3))}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
