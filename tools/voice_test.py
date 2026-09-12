#!/usr/bin/env python3
"""Quickly A/B ElevenLabs voices & expressiveness settings on ONE short line,
so you can dial in emotion cheaply before rendering full videos.

Examples
--------
  # Test the current config voice with different emotion settings:
  python tools/voice_test.py --stability 0.3 --style 0.6
  python tools/voice_test.py --stability 0.5 --style 0.2

  # Try a specific voice id and model:
  python tools/voice_test.py --voice 21m00Tcm4TlvDq8ikWAM --model eleven_turbo_v2_5

  # List your voices to get ids:
  python tools/voice_test.py --list

Each run writes an mp3 to output/voice_tests/ named after the settings, so you
can listen side by side and pick the best. Uses only your ElevenLabs key.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests  # noqa: E402
from src.config import Config  # noqa: E402
from src.voiceover import list_voices  # noqa: E402

# A short, emotional Gujarati line (question + feeling) — good for judging tone.
DEFAULT_LINE = (
    "શું તમે જાણો છો? એક નાનકડી ભૂલે તેનું આખું જીવન બદલી નાખ્યું... "
    "પણ તેણે હાર ન માની!"
)


def main() -> int:
    ap = argparse.ArgumentParser(description="ElevenLabs voice/emotion tester")
    ap.add_argument("--list", action="store_true", help="List your voices and exit")
    ap.add_argument("--text", default=DEFAULT_LINE, help="Text to speak")
    ap.add_argument("--voice", default=None, help="Voice id (default: config voice)")
    ap.add_argument("--model", default=None, help="Model id (default: config model)")
    ap.add_argument("--stability", type=float, default=None)
    ap.add_argument("--style", type=float, default=None)
    ap.add_argument("--similarity", type=float, default=None)
    ap.add_argument("--speaker-boost", dest="boost", action="store_true", default=None)
    args = ap.parse_args()

    cfg = Config.load()
    if not cfg.elevenlabs_api_key:
        print("ELEVENLABS_API_KEY not set (see .env).", file=sys.stderr)
        return 1

    if args.list:
        for v in list_voices(cfg):
            print(f"{v['voice_id']:24}  {v['name']}  ({v['category']})")
        return 0

    voice = args.voice or cfg.elevenlabs_voice_id or cfg.get("voiceover", "default_voice_id")
    model = args.model or cfg.get("voiceover", "model_id", default="eleven_multilingual_v2")
    settings = {
        "stability": args.stability if args.stability is not None
        else cfg.get("voiceover", "stability", default=0.35),
        "style": args.style if args.style is not None
        else cfg.get("voiceover", "style", default=0.45),
        "similarity_boost": args.similarity if args.similarity is not None
        else cfg.get("voiceover", "similarity_boost", default=0.80),
        "use_speaker_boost": args.boost if args.boost is not None
        else cfg.get("voiceover", "use_speaker_boost", default=True),
    }

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    r = requests.post(
        url,
        headers={"xi-api-key": cfg.elevenlabs_api_key, "Content-Type": "application/json"},
        json={"text": args.text, "model_id": model, "voice_settings": settings},
        timeout=120,
    )
    if r.status_code != 200:
        print(f"ElevenLabs error {r.status_code}: {r.text[:300]}", file=sys.stderr)
        return 1

    out_dir = cfg.path("output", "voice_tests")
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{model}_stab{settings['stability']}_style{settings['style']}.mp3"
    dest = out_dir / name
    dest.write_bytes(r.content)
    print(f"✓ Wrote {dest}")
    print(f"  voice={voice} model={model} settings={settings}")
    print("  Listen, then set the winning values in config.yaml (voiceover:).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
