#!/usr/bin/env python3
"""Preflight check — run this to verify your setup before the first video.

    python check_setup.py

Prints a pass/fail checklist for Python, ffmpeg, dependencies, your .env keys,
and the Gujarati subtitle font. Exit code 0 = ready to go.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OK = "[ OK ]"
FAIL = "[FAIL]"
WARN = "[WARN]"

results: list[bool] = []


def check(ok: bool, label: str, hint: str = "", warn_only: bool = False) -> None:
    tag = OK if ok else (WARN if warn_only else FAIL)
    print(f"{tag}  {label}")
    if not ok and hint:
        print(f"        -> {hint}")
    if not warn_only:
        results.append(ok)


def main() -> int:
    print("=" * 60)
    print(" Gujarati YouTube automation — setup check")
    print("=" * 60)

    # 1. Python version -----------------------------------------------------
    v = sys.version_info
    check(
        v >= (3, 10),
        f"Python {v.major}.{v.minor}.{v.micro}",
        "Install Python 3.10+ from python.org and re-run.",
    )

    # 2. Are we in a virtualenv? (nice to have) -----------------------------
    in_venv = sys.prefix != sys.base_prefix
    check(in_venv, "Running inside a virtual environment",
          "Recommended: python -m venv .venv && .venv\\Scripts\\activate",
          warn_only=True)

    # 3. ffmpeg on PATH -----------------------------------------------------
    check(
        shutil.which("ffmpeg") is not None,
        "ffmpeg is installed and on PATH",
        "Install it (winget install Gyan.FFmpeg) then REOPEN your terminal.",
    )

    # 4. Python dependencies ------------------------------------------------
    deps = {
        "anthropic": "anthropic",
        "requests": "requests",
        "yaml": "PyYAML",
        "dotenv": "python-dotenv",
        "googleapiclient": "google-api-python-client",
        "google_auth_oauthlib": "google-auth-oauthlib",
    }
    missing = [pip_name for mod, pip_name in deps.items() if not _importable(mod)]
    check(
        not missing,
        "Python dependencies installed",
        f"Run: pip install -r requirements.txt  (missing: {', '.join(missing)})",
    )

    # 5. .env exists + keys present ----------------------------------------
    env_path = ROOT / ".env"
    check(env_path.exists(), ".env file exists",
          "Run: copy .env.example .env   then edit it.")
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except Exception:
            pass
        _reload_env(env_path)

    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    eleven_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    check(
        anthropic_key.startswith("sk-ant-"),
        "ANTHROPIC_API_KEY is set",
        "Add ANTHROPIC_API_KEY=sk-ant-... to .env",
    )
    check(
        eleven_key.startswith("sk_") and len(eleven_key) > 20,
        "ELEVENLABS_API_KEY is set",
        "Add ELEVENLABS_API_KEY=sk_... to .env",
    )

    # 6. Optional keys ------------------------------------------------------
    has_stock = bool(
        os.getenv("PEXELS_API_KEY", "").strip() or os.getenv("PIXABAY_API_KEY", "").strip()
    )
    check(
        has_stock,
        "PEXELS_API_KEY or PIXABAY_API_KEY is set (optional — real stock photos)",
        "Free keys at pexels.com/api / pixabay.com/api; without them you get color slides.",
        warn_only=True,
    )

    # 7. Subtitle font ------------------------------------------------------
    font_ok = _font_present()
    check(
        font_ok,
        "Gujarati subtitle font present in assets/fonts/",
        "Download Noto Sans Gujarati (.ttf) into assets/fonts/",
    )

    # 8. config.yaml loads --------------------------------------------------
    cfg_ok = True
    try:
        sys.path.insert(0, str(ROOT))
        from src.config import Config
        cfg = Config.load()
        voice = cfg.get("voiceover", "default_voice_id")
        print(f"        (voice id: {voice}, format: {cfg.get('channel','format')})")
    except Exception as exc:
        cfg_ok = False
        print(f"        config error: {exc}")
    check(cfg_ok, "config.yaml loads")

    # 9. YouTube client secrets (only needed for upload) -------------------
    secrets = ROOT / os.getenv("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")
    check(
        secrets.exists(),
        "YouTube client_secrets.json present (needed only for upload)",
        "See README 'YouTube setup'. Not needed for --no-upload test runs.",
        warn_only=True,
    )

    # Summary ---------------------------------------------------------------
    print("-" * 60)
    if all(results):
        print("✅ All required checks passed — you're ready!")
        print('   Try:  python main.py --topic "સાચી મહેનતનું ફળ" --no-upload')
        return 0
    n_fail = results.count(False)
    print(f"❌ {n_fail} required check(s) failed. Fix the [FAIL] items above and re-run.")
    return 1


def _importable(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except Exception:
        return False


def _reload_env(env_path: Path) -> None:
    """Load .env manually too, in case python-dotenv isn't installed."""
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def _font_present() -> bool:
    fonts = ROOT / "assets" / "fonts"
    if not fonts.exists():
        return False
    return any(p.suffix.lower() in {".ttf", ".otf"} for p in fonts.iterdir())


if __name__ == "__main__":
    raise SystemExit(main())
